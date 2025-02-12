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

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
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

# Create a SQLAlchemy engine.
# The database URL format is: "postgresql+psycopg2://user:password@host/dbname"
db_url = f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}/{os.getenv('DB_NAME')}"
engine = create_engine(db_url)

# Using SQLAlchemy’s engine and Pandas to_sql() avoids issues with NAType.

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
            return {'username': identity}
    return None

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
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
        return jsonify({'message': 'Database error.'}), 500

    if user and bcrypt.checkpw(password.encode('utf-8'), user[2].encode('utf-8')):
        access_token = create_access_token(identity=username)
        token_expiration = datetime.now(timezone.utc) + app.config['JWT_ACCESS_TOKEN_EXPIRES']
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE users SET token = :token, token_expiration = :token_expiration WHERE id = :id"),
                    {"token": access_token, "token_expiration": token_expiration, "id": user[0]}
                )
        except Exception as e:
            logger.error(f"Error updating token: {e}")
            return jsonify({'message': 'Error processing login.'}), 500
        return jsonify({'token': access_token}), 200
    else:
        return jsonify({'message': 'Invalid username or password'}), 401

# Global variable for storing the uniques_list DataFrame for downloads
uniques_list_df = None

@app.route('/process_spreadsheets', methods=['POST'])
@jwt_required()
def process_spreadsheets():
    current_user_id = get_jwt_identity()
    logger.info("Starting processing of spreadsheets.")

    uploaded_files = request.files.getlist('files')
    source_name = request.form.get('source_name')
    list_name = request.form.get('list_name')

    if not uploaded_files:
        return jsonify({'message': 'No files uploaded.'}), 400
    if not source_name or not list_name:
        return jsonify({'message': 'Source name or list name not provided.'}), 400

    processed_files = []
    # Process each uploaded CSV file
    for file in uploaded_files:
        try:
            df = pd.read_csv(file, low_memory=False)
        except Exception as e:
            logger.error(f"Error reading CSV file: {e}")
            return jsonify({'message': 'Error reading CSV file', 'error': str(e)}), 400

        if len(df.columns) != 70:
            return jsonify({'message': 'The spreadsheet must contain exactly 70 columns.'}), 400

        # Add metadata and normalize column names
        df.insert(0, 'source_name', source_name)
        df.insert(1, 'list', list_name)
        df.columns = [col.lower().replace(" ", "_").replace("%", "percent").replace("-", "") for col in df.columns]
        df.rename(columns={
            'property_county': 'county',
            'rank': 'rank_number',
            'tax_delinquent_year': 'tax_delinquency_year',
            'tax_delinquent_first_seen': 'tax_delinquency_first_seen',
            'tax_delinquent_last_updated': 'tax_delinquency_last_updated'
        }, inplace=True)

        # Replace empty strings with None
        df.replace({"": None, "NaN": None}, inplace=True)

        # Convert columns to numeric types (if present)
        for col in ['tax_delinquency_year', 'tax_delinquency', 'prior_deed_transfer', 'preforeclosure', 'phantom', 'invol_lien', 'stack_count', 'rank_number', 'year_built', 'baths', 'beds', 'vacant']:
            if col in df.columns:
                try:
                    df[col] = df[col].astype(pd.Int64Dtype())
                except Exception as e:
                    logger.warning(f"Conversion error for column {col}: {e}")
        for col in ['low_property_avm', 'final_property_avm', 'high_property_avm', 'lot_size', 'sqft', 'sale_price', 'mortgage_past_due_amount', 'mortgage_unpaid_balance_amount']:
            if col in df.columns:
                try:
                    df[col] = df[col].astype(pd.Int64Dtype())
                except Exception as e:
                    logger.warning(f"Conversion error for column {col}: {e}")

        # Convert date columns to string format or None
        for col in ['prediction_date', 'last_sale_date', 'first_seen', 'last_updated', 'invol_lien_first_seen', 'invol_lien_last_updated', 'phantom_first_seen', 'phantom_last_updated', 'mortgage_original_due_date', 'mortgage_default_date', 'notice_of_sale_auction_date', 'preforeclosure_first_seen', 'preforeclosure_last_updated', 'prior_deed_transfer_first_seen', 'prior_deed_transfer_last_updated', 'tax_delinquent_last_updated', 'vacancy_date', 'vacancy_first_seen', 'vacancy_last_updated', 'owner_last_exported_date', 'property_last_exported_date']:
            if col in df.columns:
                try:
                    df[col] = pd.to_datetime(df[col], format='%Y-%m-%d', errors='coerce')
                    df[col] = df[col].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isna(x) else None)
                except Exception as e:
                    logger.warning(f"Date conversion error for column {col}: {e}")

        # Ensure any remaining missing values become None
        df = df.where(pd.notnull(df), None)
        processed_files.append(df)

    if not processed_files:
        return jsonify({'message': 'No valid files processed.'}), 400

    try:
        combined_df = pd.concat(processed_files, ignore_index=True)
        logger.debug(f"Combined DF shape: {combined_df.shape}")

        # Use SQLAlchemy and Pandas to_sql() to insert into audantic_raw_list.
        # This method handles missing values by converting them to SQL NULL.
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE audantic_raw_list"))
            combined_df.to_sql('audantic_raw_list', con=conn, if_exists='append', index=False, method='multi')

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

            # Save the uniques_list data for download.
            uniques_df = pd.read_sql_query("SELECT * FROM uniques_list", conn)
            json_data = uniques_df.to_json(orient='records')
            binary_data = json_data.encode()
            conn.execute(
                text("INSERT INTO processed_files (username, file_data) VALUES (:username, :file_data)"),
                {"username": current_user_id, "file_data": binary_data}
            )

        logger.info("Spreadsheets processed successfully.")
        return jsonify({'message': 'Spreadsheets processed successfully.', 'unique_count': unique_count}), 200

    except Exception as e:
        logger.error(f"General error in processing spreadsheets: {e}")
        return jsonify({'message': 'An error occurred while processing the spreadsheets.', 'error': str(e)}), 500

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
                # file_data is expected to be bytes; decode it to a string.
                json_data = file_data.decode()
                uniques_df = pd.read_json(json_data)
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as temp_file:
                    uniques_df.to_csv(temp_file, index=False)
                    temp_file_path = temp_file.name
                return send_file(temp_file_path, as_attachment=True, download_name='uniques_list.csv')
            else:
                return jsonify({'message': 'No processed file found for the user.'}), 404
    except Exception as e:
        logger.error(f"Error downloading uniques list: {e}")
        return jsonify({'message': 'An error occurred while downloading the uniques list.', 'error': str(e)}), 500

@app.route('/process_skiptraced', methods=['POST'])
@jwt_required()
def process_skiptraced():
    logger.info("Starting processing of skiptraced data.")
    uploaded_files = request.files.getlist('files')
    skip_traced_date = request.form.get('skip_traced_date')
    upload_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    if not uploaded_files:
        return jsonify({'message': 'No files uploaded.'}), 400

    processed_files = []
    for file in uploaded_files:
        try:
            df = pd.read_csv(file, low_memory=False)
        except Exception as e:
            logger.error(f"Error reading skiptraced CSV: {e}")
            continue

        if len(df.columns) != 91:
            logger.warning(f"Expected 91 columns but got {len(df.columns)}. Skipping file {file.filename}")
            continue

        df.columns = [col.lower().replace(" ", "_").replace("%", "percent").replace("-", "") for col in df.columns]
        df.rename(columns={'full_address': 'full_skiptrace_address'}, inplace=True)
        if 'has_duplicates' in df.columns:
            df.drop(columns=['has_duplicates'], inplace=True)

        df["last_skiptraced_date"] = skip_traced_date
        df["sql_last_update_date"] = upload_date
        df["sql_added_date"] = upload_date

        insert_idx = df.columns.get_loc("list") + 1 if "list" in df.columns else 1
        df.insert(insert_idx, "original_name", "")

        const_owner_cols = ['owner_1_name', 'owner_1_first_name', 'owner_1_last_name',
                              'owner_2_name', 'owner_2_first_name', 'owner_2_last_name']
        if all(col in df.columns for col in const_owner_cols):
            owner_data = df[const_owner_cols].fillna('')
            df.drop(columns=const_owner_cols, inplace=True)
            insert_index = df.columns.get_loc('original_name') + 1
            for col in const_owner_cols:
                df.insert(insert_index, col, owner_data[col])
                insert_index += 1

        if 'owner_1_first_name' in df.columns:
            df.insert(df.columns.get_loc("owner_1_first_name") + 1, 'owner_1_middle_name', '')
        if 'owner_2_first_name' in df.columns:
            df.insert(df.columns.get_loc("owner_2_first_name") + 1, 'owner_2_middle_name', '')

        if 'county' in df.columns:
            county_col = df.pop('county')
            if 'owner_2_last_name' in df.columns:
                df.insert(df.columns.get_loc("owner_2_last_name") + 1, 'county', county_col)
            else:
                df['county'] = county_col

        if 'county' in df.columns:
            df.insert(df.columns.get_loc("county") + 1, 'property_class', 0)

        phone_fields = [
            ("phone1", "phone1_cc_disposition", "phone1_sms_disposition"),
            ("phone2_company", "phone2_cc_disposition", "phone2_sms_disposition"),
            ("phone3_company", "phone3_cc_disposition", "phone3_sms_disposition")
        ]
        for base, cc, sms in phone_fields:
            if base in df.columns:
                base_idx = df.columns.get_loc(base)
                df.insert(base_idx + 1, cc, "")
                df.insert(base_idx + 2, sms, "")

        const_addr_cols = ['owner_street_address', 'owner_city', 'owner_state', 'owner_zip_code']
        if all(col in df.columns for col in const_addr_cols):
            addr_data = df[const_addr_cols]
            df.drop(columns=const_addr_cols, inplace=True)
            insert_index = df.columns.get_loc('sql_added_date') + 1
            for col in const_addr_cols:
                df.insert(insert_index, col, addr_data[col])
                insert_index += 1

        if 'vacancy_description' in df.columns:
            df.drop(columns=['vacancy_description'], inplace=True)

        for col in ['equity_percent', 'tax_improvement_percent', 'discount']:
            if col in df.columns:
                try:
                    df[col] = df[col].astype(pd.Float64Dtype()).fillna(0)
                except Exception as e:
                    logger.warning(f"Numeric conversion error for column {col}: {e}")
        for col in ['age', 'beds', 'baths', 'year_built', 'rank_number', 'stack_count', 'invol_lien', 'phantom', 'preforeclosure', 'prior_deed_transfer', 'tax_delinquency', 'tax_delinquency_year', 'vacant']:
            if col in df.columns:
                try:
                    df[col] = df[col].astype(pd.Int64Dtype()).fillna(0)
                except Exception as e:
                    logger.warning(f"Smallint conversion error for column {col}: {e}")
        for col in ['low_property_avm', 'final_property_avm', 'high_property_avm', 'lot_size', 'sqft', 'sale_price', 'mortgage_past_due_amount', 'mortgage_unpaid_balance_amount']:
            if col in df.columns:
                try:
                    df[col] = df[col].astype(pd.Int64Dtype()).fillna(0)
                except Exception as e:
                    logger.warning(f"Integer conversion error for column {col}: {e}")
        for col in ['phone1_lastreporteddate', 'phone2_lastreporteddate', 'phone3_lastreporteddate', 'last_skiptraced_date', 'last_sale_date', 'prediction_date', 'first_seen', 'last_updated', 'invol_lien_firstreporteddate', 'invol_lien_lastreporteddate', 'phantom_firstseen', 'phantom_lastreporteddate', 'mortgage_original_due_date', 'mortgage_default_date', 'notice_of_sale_auction_date', 'preforeclosure_first_seen', 'preforeclosure_last_updated', 'prior_deed_transfer_first_seen', 'prior_deed_transfer_last_updated', 'tax_delinquent_first_seen', 'tax_delinquent_last_updated', 'vacancy_date', 'vacancy_first_seen', 'vacancy_last_updated', 'property_last_exported_date', 'owner_last_exported_date']:
            if col in df.columns:
                try:
                    df[col] = pd.to_datetime(df[col], format='%Y-%m-%d', errors='coerce')
                    df[col] = df[col].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isna(x) else None)
                except Exception as e:
                    logger.warning(f"Error converting date column {col}: {e}")
        for col in ['source_name', 'list', 'original_name', 'owner_1_name', 'owner_1_first_name', 'owner_1_middle_name', 'owner_1_last_name', 'owner_2_name', 'owner_2_first_name', 'owner_2_middle_name', 'owner_2_last_name', 'county', 'property_class', 'dob', 'full_skiptrace_address', 'phone1', 'phone1_cc_disposition', 'phone1_sms_disposition', 'phone1_type', 'phone1_company', 'phone2', 'phone2_type', 'phone2_company', 'phone2_cc_disposition', 'phone2_sms_disposition', 'phone3', 'phone3_type', 'phone3_company', 'phone3_cc_disposition', 'phone3_sms_disposition', 'email1', 'email2', 'email3', 'owner_street_address', 'owner_city', 'owner_state', 'owner_zip_code', 'property_street_address', 'property_city', 'property_state', 'property_zip_code', 'property_type', 'school_district', 'all_active_invol_liens', 'latest_invol_lien', 'preforeclosure_type', 'deed_transfer_type']:
            if col in df.columns:
                df[col] = df[col].astype(str).fillna('')
        for col in ['owner_occupied', 'not_listed', 'active_lien']:
            if col in df.columns:
                df[col] = df[col].astype(bool)
        
        if len(df.columns) != 102:
            logger.error(f"After modifications, expected 102 columns but got {len(df.columns)}")
            return jsonify({'message': f'After modifications, the number of columns is not as expected: {len(df.columns)}'}), 400
        
        processed_files.append(df)

    if not processed_files:
        return jsonify({'message': 'No valid skiptraced files processed.'}), 400

    try:
        with engine.begin() as conn:
            for df in processed_files:
                # Use to_sql() to insert into my_master_list. We assume the table exists.
                df.to_sql('my_master_list', con=conn, if_exists='append', index=False, method='multi')
        return jsonify({
            'message': 'Skiptraced data processed and merged successfully.',
            'standardization': 'Successful',
            'mergeStatus': 'Completed'
        }), 200
    except Exception as e:
        logger.error(f"General error in processing skiptraced data: {e}")
        return jsonify({'message': 'An error occurred while processing the skiptraced data.', 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
