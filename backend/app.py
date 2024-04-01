from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_jwt_extended import JWTManager, jwt_required, create_access_token
import bcrypt
import psycopg2
import pandas as pd
from datetime import datetime
from database import get_db_connection
import io
from dotenv import load_dotenv
import os

# Load environment variables from .env file to access your own RDS database
load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": os.getenv('APP_FRONT_END_URL')}})

# Configure JWT
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_KEY')  # Replace with your own secret key
jwt = JWTManager(app)

# Dummy user for demonstration purposes
users = {
    'admin': {'password': '$2a$12$nDec2tkyQ3IAcw8iNqxwD.8jX3lJoT8errspcsD7gSkTn5g3.p532'},  # Password: 'password'
    'testuser': {'password': '$2b$12$testusertestusertestus.UjH7pAoLdqkpnD8Bx1qYd/djECJ5i'}  # Password: 'testpassword'
}

@app.route('/login', methods=['POST'])
def login():
    username = request.json.get('username', None)
    password = request.json.get('password', None)
    print(f"Received login request with username: {username} and password: {password}")

    if username in users and bcrypt.checkpw(password.encode('utf-8'), users[username]['password'].encode('utf-8')):
        access_token = create_access_token(identity=username)
        return jsonify({'token': access_token}), 200
    else:
        return jsonify({'message': 'Invalid username or password'}), 401



# Global variable to store the uniques_list DataFrame
uniques_list_df = None

@app.route('/process_spreadsheets', methods=['POST'])
@jwt_required()

def process_spreadsheets():
    print("Processing spreadsheets...")
    uploaded_files = request.files.getlist('files')
    source_name = request.form.get('source_name')
    list_name = request.form.get('list_name')

    print(f"Uploaded files: {len(uploaded_files)}")
    print(f"Source Name: {source_name}")
    print(f"List Name: {list_name}")

    if not uploaded_files:
        return jsonify({'message': 'No files uploaded.'}), 400

    if not source_name or not list_name:
        return jsonify({'message': 'Source name or list name not provided.'}), 400

    processed_files = []

    for file in uploaded_files:
        df = pd.read_csv(file)
        #df = df.astype(str)

        if len(df.columns) != 70:
            return jsonify({'message': 'The spreadsheet must contain exactly 70 columns.'}), 400

        df.insert(0, 'source_name', source_name)
        df.insert(1, 'list', list_name)
        df.columns = [col.lower().replace(" ", "_").replace("%", "percent").replace("-", "") for col in df.columns]
        column_renames = {
            'property_county': 'county',
            'rank': 'rank_number',
            'tax_delinquent_year': 'tax_delinquency_year',
            'tax_delinquent_first_seen': 'tax_delinquent_first_seen',
            'tax_delinquent_last_updated': 'tax_delinquent_last_updated'
        }
        df.rename(columns=column_renames, inplace=True)

        # Replace empty strings with None (which will become NULL in SQL)
        df.replace({"": None}, inplace=True)
        df.replace({"NaN": None}, inplace=True)
        
        smallint_columns = ['tax_delinquency_year','tax_delinquency','prior_deed_transfer','preforeclosure','phantom','invol_lien',
            'stack_count','rank_number','year_built','baths','beds','vacant'] 
 
        for col in smallint_columns:
            if col in df.columns:
                df[col] = df[col].astype('Int64')
                max_val = df[col].max()
                min_val = df[col].min()
                print(f"Column '{col}' max value: {max_val}")
                print(f"Column '{col}' min value: {min_val}")
                if max_val > 32767 or min_val < -32768:
                    print(f"Value out of range for smallint in column: {col}")        

        integer_columns = ['low_property_avm','final_property_avm','high_property_avm','lot_size','sqft','sale_price','mortgage_past_due_amount','mortgage_unpaid_balance_amount']
        
        for col in integer_columns:
            if col in df.columns:
                df[col] = df[col].astype('Int64')

        date_columns = ['prediction_date', 'last_sale_date', 'first_seen', 'last_updated','invol_lien_first_seen','invol_lien_last_updated',
            'phantom_first_seen','phantom_last_updated','mortgage_original_due_date','mortgage_default_date',
            'notice_of_sale_auction_date','preforeclosure_first_seen','preforeclosure_last_updated','prior_deed_transfer_first_seen',
            'prior_deed_transfer_last_updated','tax_delinquent_last_updated','vacancy_date','vacancy_first_seen','vacancy_last_updated',
            'owner_last_exported_date','property_last_exported_date']  
        for column in date_columns:
            df[column] = pd.to_datetime(df[column], format='%Y-%m-%d', errors='coerce')
            df[column] = df[column].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isna(x) else None)
        
        # Assuming `df` is your DataFrame
        df = df.replace({pd.NA: None})
        df = df.where(pd.notnull(df), None)

        processed_files.append(df)

    if not processed_files:
        return jsonify({'message': 'No valid files processed.'}), 400

    try:
        print("Connecting to the database...")
        conn = get_db_connection()
        cur = conn.cursor()
        
        print("Processing and inserting data...")
        
        # Empty the audantic_raw_list table
        cur.execute("TRUNCATE TABLE audantic_raw_list")
        
        # Concatenate all processed files into a single DataFrame
        combined_df = pd.concat(processed_files, ignore_index=True)

        # Insert the combined data into the audantic_raw_list table
        columns = combined_df.columns.tolist()
        placeholders = ','.join(['%s'] * len(columns))
        insert_query = f"INSERT INTO audantic_raw_list ({','.join(columns)}) VALUES ({placeholders})"
        cur.executemany(insert_query, combined_df.values.tolist())

        # Count unique rows
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

        # Clear the unique_list table
        cur.execute("DROP TABLE IF EXISTS uniques_list")

        # Generate a new unique_list table
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

        # Store the uniques_list DataFrame in a global variable
        global uniques_list_df
        uniques_list_df = pd.read_sql_query("SELECT * FROM uniques_list", conn)

        conn.commit()
        cur.close()
        conn.close()

        print("Spreadsheets processed successfully.")
        return jsonify({'message': 'Spreadsheets processed successfully.', 'unique_count': unique_count}), 200

    except psycopg2.errors.NumericValueOutOfRange as e:
        print(f"Numeric value out of range error: {e}")
        return jsonify({'message': 'Numeric value out of range error.', 'error': str(e)}), 400
    except psycopg2.DataError as e:
        print(f"Data error occurred: {e.pgerror}")
        return jsonify({'message': 'Data error occurred while processing the spreadsheets.', 'error': str(e.pgerror)}), 400
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        return jsonify({'message': 'An error occurred while processing the spreadsheets.', 'error': str(e)}), 500

@app.route('/download_uniques_list', methods=['GET'])
@jwt_required()

def download_uniques_list():
    try:
        if uniques_list_df is not None:
            # Create a BytesIO object to store the CSV data
            csv_buffer = io.BytesIO()
            uniques_list_df.to_csv(csv_buffer, index=False)
            csv_buffer.seek(0)

            # Return the CSV file as a download attachment
            return send_file(csv_buffer, mimetype='text/csv', as_attachment=True, attachment_filename='uniques_list.csv')
        else:
            return jsonify({'message': 'No uniques list available.'}), 404

    except Exception as e:
        return jsonify({'message': 'An error occurred while downloading the uniques list.', 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
