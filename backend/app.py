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
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_jwt_extended import JWTManager, jwt_required, create_access_token, get_jwt_identity
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Configure logging (INFO level should be sufficient)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s:%(lineno)d] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": os.getenv('APP_FRONT_END_URL')}})

# Configure JWT
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_KEY')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=2)
jwt = JWTManager(app)

# Create SQLAlchemy engine.
# The URL format is "postgresql+psycopg2://user:password@host/dbname"
db_url = f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}/{os.getenv('DB_NAME')}"
engine = create_engine(db_url)

# --- JWT User Lookup ---
@jwt.user_lookup_loader
def custom_user_loader_callback(jwt_header, jwt_data):
    identity = jwt_data["sub"]
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM users WHERE username = :username"),
                {"username": identity}
            )
            user = result.fetchone()
    except Exception as e:
        logger.error(f"Error fetching user: {e}")
        return None

    if user:
        token = user[3]  # Adjust index if needed
        token_expiration = user[4]
        if token_expiration:
            token_expiration = token_expiration.replace(tzinfo=timezone.utc)
        if token and token_expiration and token_expiration > datetime.now(timezone.utc):
            return {"username": identity}
    return None

# --- Login Endpoint ---
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    logger.info(f"Login request for username: {username}")
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM users WHERE username = :username"),
                {"username": username}
            )
            user = result.fetchone()
    except Exception as e:
        logger.error(f"Database error during login: {e}")
        return jsonify({"message": "Database error."}), 500

    if user and bcrypt.checkpw(password.encode("utf-8"), user[2].encode("utf-8")):
        access_token = create_access_token(identity=username)
        token_expiration = datetime.utcnow() + app.config["JWT_ACCESS_TOKEN_EXPIRES"]
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE users SET token = :token, token_expiration = :token_expiration WHERE id = :id"),
                    {"token": access_token, "token_expiration": token_expiration, "id": user[0]}
                )
        except Exception as e:
            logger.error(f"Error updating token: {e}")
            return jsonify({"message": "Error processing login."}), 500
        return jsonify({"token": access_token}), 200
    else:
        return jsonify({"message": "Invalid username or password"}), 401

# Global variable to store the uniques_list DataFrame for downloads
uniques_list_df = None

# --- Process Spreadsheets Endpoint ---
@app.route('/process_spreadsheets', methods=['POST'])
@jwt_required()
def process_spreadsheets():
    current_user_id = get_jwt_identity()
    logger.info("Starting processing of spreadsheets.")
    uploaded_files = request.files.getlist("files")
    source_name = request.form.get("source_name")
    list_name = request.form.get("list_name")
    if not uploaded_files:
        return jsonify({"message": "No files uploaded."}), 400
    if not source_name or not list_name:
        return jsonify({"message": "Source name or list name not provided."}), 400

    processed_files = []
    for file in uploaded_files:
        try:
            df = pd.read_csv(file)
        except Exception as e:
            logger.error(f"Error reading CSV file: {e}")
            return jsonify({"message": "Error reading CSV file", "error": str(e)}), 400

        if len(df.columns) != 70:
            return jsonify({"message": "The spreadsheet must contain exactly 70 columns."}), 400

        # Add metadata and normalize column names
        df.insert(0, "source_name", source_name)
        df.insert(1, "list", list_name)
        df.columns = [col.lower().replace(" ", "_").replace("%", "percent").replace("-", "") for col in df.columns]
        renames = {
            "property_county": "county",
            "rank": "rank_number",
            "tax_delinquent_year": "tax_delinquency_year",
            "tax_delinquent_first_seen": "tax_delinquent_first_seen",
            "tax_delinquent_last_updated": "tax_delinquent_last_updated"
        }
        df.rename(columns=renames, inplace=True)
        # Replace empty strings with None (to become SQL NULL)
        df.replace({"": None}, inplace=True)
        df.replace({"NaN": None}, inplace=True)

        # (The original code did not perform explicit type conversions that introduced NAType.)
        processed_files.append(df)

    if not processed_files:
        return jsonify({"message": "No valid files processed."}), 400

    try:
        combined_df = pd.concat(processed_files, ignore_index=True)
        # Ensure missing values remain as np.nan or None
        combined_df = combined_df.where(pd.notnull(combined_df), None)
        with engine.begin() as conn:
            # Truncate the raw table
            conn.execute(text("TRUNCATE TABLE audantic_raw_list"))
            # Use Pandas to_sql() for bulk insertion.
            # Pandas automatically converts np.nan to SQL NULL.
            combined_df.to_sql("audantic_raw_list", con=conn, if_exists="append", index=False, method="multi")
            # Count unique rows using a raw SQL query.
            result = conn.execute(text("""
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
            """))
            unique_count = result.fetchone()[0]
            # Recreate uniques_list table.
            conn.execute(text("DROP TABLE IF EXISTS uniques_list"))
            conn.execute(text("""
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
            """))
            uniques_df = pd.read_sql_query("SELECT * FROM uniques_list", conn)
            json_data = uniques_df.to_json(orient="records")
            binary_data = json_data.encode()
            conn.execute(
                text("INSERT INTO processed_files (username, file_data) VALUES (:username, :file_data)"),
                {"username": current_user_id, "file_data": binary_data}
            )
        logger.info("Spreadsheets processed successfully.")
        return jsonify({"message": "Spreadsheets processed successfully.", "unique_count": unique_count}), 200
    except Exception as e:
        logger.error(f"General error in processing spreadsheets: {e}")
        return jsonify({"message": "An error occurred while processing the spreadsheets.", "error": str(e)}), 500

# --- Download Uniques List Endpoint ---
@app.route('/download_uniques_list', methods=['GET'])
@jwt_required()
def download_uniques_list():
    current_user_id = get_jwt_identity()
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT file_data
                    FROM processed_files
                    WHERE username = :username
                    ORDER BY timestamp DESC
                    LIMIT 1
                """), {"username": current_user_id}
            )
            row = result.fetchone()
            if row:
                file_data = row[0]
                # file_data is stored as bytes; decode it to a string.
                json_data = file_data.decode()
                df = pd.read_json(json_data)
                with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv") as temp_file:
                    df.to_csv(temp_file, index=False)
                    temp_file_path = temp_file.name
                return send_file(temp_file_path, as_attachment=True, download_name="uniques_list.csv")
            else:
                return jsonify({"message": "No processed file found for the user."}), 404
    except Exception as e:
        logger.error(f"Error downloading uniques list: {e}")
        return jsonify({"message": "An error occurred while downloading the uniques list.", "error": str(e)}), 500

# --- Process Skiptraced Endpoint ---
@app.route('/process_skiptraced', methods=['POST'])
@jwt_required()
def process_skiptraced():
    uploaded_files = request.files.getlist("files")
    skip_traced_date = request.form.get("skip_traced_date")
    upload_date = str(datetime.now().date())
    if not uploaded_files:
        return jsonify({"message": "No files uploaded."}), 400
    try:
        processed_files = []
        for file in uploaded_files:
            df = pd.read_csv(file)
            if len(df.columns) != 91:
                continue
            df.columns = [col.lower().replace(" ", "_").replace("%", "percent").replace("-", "") for col in df.columns]
            df.rename(columns={"full_address": "full_skiptrace_address"}, inplace=True)
            df.drop(columns=["has_duplicates"], inplace=True)
            df["last_skiptraced_date"] = skip_traced_date
            df["sql_last_update_date"] = upload_date
            df["sql_added_date"] = upload_date
            df.insert(df.columns.get_loc("list") + 1, "original_name", "")
            # (Perform any additional column reordering/processing as needed)
            # In this version, we rely on the original code’s processing.
            processed_files.append(df)
        if not processed_files:
            return jsonify({"message": "No valid files processed."}), 400
        # For skiptraced data, we use psycopg2 executemany (as in your original code)
        # because you mentioned that only the Format Data & Get Unique Rows process had the NAType issue.
        try:
            conn = engine.raw_connection()
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
                from psycopg2 import extras
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
            return jsonify({"message": "An error occurred while processing the skiptraced data.", "error": str(e)}), 500
    except Exception as e:
        return jsonify({"message": "An error occurred while processing the skiptraced data.", "error": str(e)}), 500

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000)
