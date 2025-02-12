# backend/app.py
import os
import io
import csv
import tempfile
import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import bcrypt
import psycopg2
from psycopg2 import extras
from psycopg2.extras import execute_batch
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_jwt_extended import JWTManager, jwt_required, create_access_token, get_jwt_identity
from dotenv import load_dotenv

from database import get_db_connection

# Load environment variables from .env
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s:%(lineno)d] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": os.getenv("APP_FRONT_END_URL")}})

# Configure JWT with timezone-aware expiration
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_KEY")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=2)
jwt = JWTManager(app)

@jwt.user_lookup_loader
def custom_user_loader_callback(jwt_header, jwt_data):
    identity = jwt_data["sub"]
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = %s", (identity,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    if user:
        token = user[3]  # Ensure this index matches your table schema
        token_expiration = user[4]
        if token_expiration:
            token_expiration = token_expiration.replace(tzinfo=timezone.utc)
        if token and token_expiration and token_expiration > datetime.now(timezone.utc):
            return {"username": identity}
    return None

@app.route("/login", methods=["POST"])
def login():
    username = request.json.get("username", None)
    password = request.json.get("password", None)
    logger.info(f"Received login request with username: {username}")
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cur.fetchone()
    
    if user and bcrypt.checkpw(password.encode("utf-8"), user[2].encode("utf-8")):
        access_token = create_access_token(identity=username)
        # Use timezone-aware token expiration
        token_expiration = datetime.now(timezone.utc) + app.config["JWT_ACCESS_TOKEN_EXPIRES"]
        cur.execute("UPDATE users SET token = %s, token_expiration = %s WHERE id = %s",
                    (access_token, token_expiration, user[0]))
        if cur.rowcount == 0:
            cur.execute("INSERT INTO users (username, password, token, token_expiration) VALUES (%s, %s, %s, %s)",
                        (username, user[2], access_token, token_expiration))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"token": access_token}), 200
    else:
        cur.close()
        conn.close()
        return jsonify({"message": "Invalid username or password"}), 401

# Global variable to store the uniques_list DataFrame
uniques_list_df = None

@app.route("/process_spreadsheets", methods=["POST"])
@jwt_required()
def process_spreadsheets():
    current_user_id = get_jwt_identity()
    logger.info("Processing spreadsheets...")
    uploaded_files = request.files.getlist("files")
    source_name = request.form.get("source_name")
    list_name = request.form.get("list_name")
    
    logger.info(f"Uploaded files: {len(uploaded_files)}")
    logger.info(f"Source Name: {source_name}")
    logger.info(f"List Name: {list_name}")
    
    if not uploaded_files:
        return jsonify({"message": "No files uploaded."}), 400
    if not source_name or not list_name:
        return jsonify({"message": "Source name or list name not provided."}), 400

    processed_files = []
    for file in uploaded_files:
        try:
            # Optimize CSV reading with low_memory=False
            df = pd.read_csv(file, low_memory=False)
        except Exception as e:
            logger.error(f"Error reading CSV file: {e}")
            return jsonify({"message": "Error reading CSV file", "error": str(e)}), 400
        
        if len(df.columns) != 70:
            return jsonify({"message": "The spreadsheet must contain exactly 70 columns."}), 400

        df.insert(0, "source_name", source_name)
        df.insert(1, "list", list_name)
        # Normalize column names
        df.columns = [col.lower().replace(" ", "_").replace("%", "percent").replace("-", "") for col in df.columns]
        renames = {
            "property_county": "county",
            "rank": "rank_number",
            "tax_delinquent_year": "tax_delinquency_year",
            "tax_delinquent_first_seen": "tax_delinquency_first_seen",
            "tax_delinquent_last_updated": "tax_delinquency_last_updated"
        }
        df.rename(columns=renames, inplace=True)
        # Replace empty strings with None (like the original code)
        df.replace({"": None}, inplace=True)
        df.replace({"NaN": None}, inplace=True)
        # (Avoid any conversion to nullable types that would produce NAType values.)
        processed_files.append(df)
    
    if not processed_files:
        return jsonify({"message": "No valid files processed."}), 400
    
    try:
        combined_df = pd.concat(processed_files, ignore_index=True)
        # Ensure missing values remain as np.nan or None (as in the original)
        combined_df = combined_df.where(pd.notnull(combined_df), None)
        
        conn = get_db_connection()
        cur = conn.cursor()
        # Empty the audantic_raw_list table
        cur.execute("TRUNCATE TABLE audantic_raw_list")
        conn.commit()
        # Use faster bulk insert via execute_batch
        columns = combined_df.columns.tolist()
        placeholders = ",".join(["%s"] * len(columns))
        insert_query = f"INSERT INTO audantic_raw_list ({','.join(columns)}) VALUES ({placeholders})"
        data = combined_df.values.tolist()  # Original code simply used values.tolist()
        extras.execute_batch(cur, insert_query, data, page_size=1000)
        conn.commit()
        
        # Count unique rows (same query as original)
        unique_count_query = """
        SELECT COUNT(*)
        FROM audantic_raw_list arl
        WHERE NOT EXISTS (
            SELECT 1
            FROM my_master_list mml
            WHERE arl.property_street_address = mml.property_street_address
              AND arl.property_city = mml.property_city
              AND arl.owner_1_first_name = mml.owner_1_first_name
              AND mml.phone1 IS NOT NULL
        )
        """
        cur.execute(unique_count_query)
        unique_count = cur.fetchone()[0]
        
        # Recreate the uniques_list table
        cur.execute("DROP TABLE IF EXISTS uniques_list")
        unique_list_query = """
        CREATE TABLE uniques_list AS
        SELECT *
        FROM audantic_raw_list
        WHERE NOT EXISTS (
            SELECT 1
            FROM my_master_list
            WHERE audantic_raw_list.property_street_address = my_master_list.property_street_address
              AND audantic_raw_list.property_city = my_master_list.property_city
              AND audantic_raw_list.owner_1_first_name = my_master_list.owner_1_first_name
              AND my_master_list.phone1 IS NOT NULL
        )
        """
        cur.execute(unique_list_query)
        
        # Store the uniques_list DataFrame for download
        global uniques_list_df
        uniques_list_df = pd.read_sql_query("SELECT * FROM uniques_list", conn)
        json_data = uniques_list_df.to_json(orient="records")
        binary_data = json_data.encode()
        cur.execute("INSERT INTO processed_files (username, file_data) VALUES (%s, %s)", (current_user_id, binary_data))
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info("Spreadsheets processed successfully.")
        return jsonify({"message": "Spreadsheets processed successfully.", "unique_count": unique_count}), 200
        
    except psycopg2.errors.NumericValueOutOfRange as e:
        logger.error(f"Numeric value out of range error: {e}")
        return jsonify({"message": "Numeric value out of range error.", "error": str(e)}), 400
    except psycopg2.DataError as e:
        logger.error(f"Data error occurred: {e.pgerror}")
        return jsonify({"message": "Data error occurred while processing the spreadsheets.", "error": str(e.pgerror)}), 400
    except Exception as e:
        logger.error(f"An error occurred while processing the spreadsheets: {str(e)}")
        return jsonify({"message": "An error occurred while processing the spreadsheets.", "error": str(e)}), 500

@app.route("/download_uniques_list", methods=["GET"])
@jwt_required()
def download_uniques_list():
    try:
        current_user_id = get_jwt_identity()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT file_data
            FROM processed_files
            WHERE username = %s
            ORDER BY timestamp DESC
            LIMIT 1
        """, (current_user_id,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        if result:
            file_data = result[0]
            # Convert bytea to JSON string
            json_data = file_data.tobytes().decode()
            df = pd.read_json(json_data)
            with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
                df.to_csv(temp_file, index=False)
                temp_file_path = temp_file.name
            return send_file(temp_file_path, as_attachment=True, download_name="uniques_list.csv")
        else:
            return jsonify({"message": "No processed file found for the user."}), 404
    except Exception as e:
        logger.error(f"Error downloading uniques list: {e}")
        return jsonify({"message": "An error occurred while downloading the uniques list.", "error": str(e)}), 500

@app.route("/process_skiptraced", methods=["POST"])
@jwt_required()
def process_skiptraced():
    logger.info("Skiptrace sheet process initiated")
    uploaded_files = request.files.getlist("files")
    skip_traced_date = request.form.get("skip_traced_date")
    upload_date = str(datetime.now().date())
    logger.info(f"Uploaded files received: {len(uploaded_files)}; skiptraced date: {skip_traced_date}")
    if not uploaded_files:
        return jsonify({"message": "No files uploaded."}), 400
    try:
        processed_files = []
        for file in uploaded_files:
            df = pd.read_csv(file)
            if len(df.columns) != 91:
                logger.warning(f"Expected 91 columns but got {len(df.columns)}; skipping file.")
                continue
            df.columns = [col.lower().replace(" ", "_").replace("%", "percent").replace("-", "") for col in df.columns]
            df.rename(columns={"full_address": "full_skiptrace_address"}, inplace=True)
            df.drop(columns=["has_duplicates"], inplace=True)
            df["last_skiptraced_date"] = skip_traced_date
            df["sql_last_update_date"] = upload_date
            df["sql_added_date"] = upload_date
            df.insert(df.columns.get_loc("list") + 1, "original_name", "")
            # Additional processing steps as in your original code for skiptraced data...
            processed_files.append(df)
        if not processed_files:
            return jsonify({"message": "No valid files processed."}), 400
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            for df in processed_files:
                columns = df.columns.tolist()
                placeholders = ", ".join(["%s"] * len(columns))
                insert_query = f"""
                INSERT INTO my_master_list ({", ".join(columns)})
                VALUES ({placeholders})
                ON CONFLICT (property_street_address, property_city, owner_1_first_name, owner_1_last_name)
                DO UPDATE SET
                    phone1 = EXCLUDED.phone1,
                    phone2 = EXCLUDED.phone2,
                    phone3 = EXCLUDED.phone3,
                    email1 = EXCLUDED.email1,
                    email2 = EXCLUDED.email2,
                    email3 = EXCLUDED.email3,
                    last_updated = EXCLUDED.last_updated;
                """
                data = [tuple(row) for row in df.itertuples(index=False)]
                extras.execute_batch(cur, insert_query, data, page_size=100)
                conn.commit()
            cur.close()
            conn.close()
            return jsonify({
                "message": "Skiptraced data processed and merged successfully.",
                "standardization": "Successful",
                "mergeStatus": "Completed"
            }), 200
        except Exception as e:
            logger.error(f"Error processing skiptraced data: {e}")
            return jsonify({"message": "An error occurred while processing the skiptraced data.", "error": str(e)}), 500
    except Exception as e:
        logger.error(f"General error processing skiptraced data: {e}")
        return jsonify({"message": "An error occurred while processing the skiptraced data.", "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
