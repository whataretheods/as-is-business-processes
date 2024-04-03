from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_jwt_extended import JWTManager, jwt_required, create_access_token, get_jwt_identity
import bcrypt
import psycopg2
import pandas as pd
from datetime import datetime, timedelta, timezone
from database import get_db_connection
import tempfile
import csv
import io
from dotenv import load_dotenv
import os

# Load environment variables from .env file to access your own RDS database
load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": os.getenv('APP_FRONT_END_URL')}})

# Configure JWT
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_KEY')  # Replace with your own secret key
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=2) # Set the token expiration time
jwt = JWTManager(app)

#This function checks the token's validity against the database
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
        token = user[3] # Make sure token is the 4th column of your table
        token_expiration = user[4] #Make sure token_expiration is the 5th column of your table

        if token_expiration:
            token_expiration = token_expiration.replace(tzinfo=timezone.utc)

        if token and token_expiration and token_expiration > datetime.now(timezone.utc):
            return {'username': identity}
    return None

'''
# Dummy user for demonstration purposes
users = {
    'admin': {'password': '$2a$12$nDec2tkyQ3IAcw8iNqxwD.8jX3lJoT8errspcsD7gSkTn5g3.p532'},  # Password: 'password'
    'testuser': {'password': '$2b$12$testusertestusertestus.UjH7pAoLdqkpnD8Bx1qYd/djECJ5i'}  # Password: 'testpassword'
}
'''

@app.route('/login', methods=['POST'])
def login():
    username = request.json.get('username', None)
    password = request.json.get('password', None)
    print(f"Received login request with username: {username} and password: {password}")

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cur.fetchone()

    if user and bcrypt.checkpw(password.encode('utf-8'), user[2].encode('utf-8')):
        access_token = create_access_token(identity=username)
        token_expiration = datetime.utcnow() + app.config['JWT_ACCESS_TOKEN_EXPIRES']

        cur.execute("UPDATE users SET token = %s, token_expiration = %s WHERE id = %s", (access_token, token_expiration, user[0]))

        if cur.rowcount == 0: # Check to see if there is no token for the user, since the Update step above did not work.
            cur.execute("INSERT INTO users (username, password, token, token_expiration) VALUES (%s, %s, %s, %s)", (username, user[2], access_token, token_expiration))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({'token': access_token}), 200
    else:
        cur.close()
        conn.close()
        return jsonify({'message': 'Invalid username or password'}), 401


# Global variable to store the uniques_list DataFrame
uniques_list_df = None

@app.route('/process_spreadsheets', methods=['POST'])
@jwt_required()
def process_spreadsheets():
    # Get the current user's ID
    current_user_id = get_jwt_identity()

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
                df[col] = df[col].astype(pd.Int64Dtype()) #converts the column values to integers and invalid or missing values to NaN
                max_val = df[col].max()
                min_val = df[col].min()
                print(f"Column '{col}' max value: {max_val}")
                print(f"Column '{col}' min value: {min_val}")

        integer_columns = ['low_property_avm','final_property_avm','high_property_avm','lot_size','sqft','sale_price','mortgage_past_due_amount','mortgage_unpaid_balance_amount']
        
        for col in integer_columns:
            if col in df.columns:
                df[col] = df[col].astype(pd.Int64Dtype()) #converts the column values to integers and invalid or missing values to NaN

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

        # Store the uniques_list DataFrame
        global uniques_list_df
        uniques_list_df = pd.read_sql_query("SELECT * FROM uniques_list", conn)

        json_data = uniques_list_df.to_json(orient = 'records')
        binary_data = json_data.encode()

        cur.execute("INSERT INTO processed_files (username, file_data) VALUES (%s, %s)", (current_user_id, binary_data))

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
        # Get the current user's ID
        current_user_id = get_jwt_identity()

        # Fetch the data from the uniques_list table
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
            json_data = file_data.tobytes().decode() # convert data type from RDS (stored as bytea) to JSON
            df = pd.read_json(json_data)

            # Create a temporary file and write the DataFrame to it
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_file:
                df.to_csv(temp_file, index=False)
                temp_file_path = temp_file.name

            return send_file(temp_file_path, as_attachment=True, download_name='uniques_list.csv')
        else:
            return jsonify({'message': 'No processed file found for the user.'}), 404

    except Exception as e:
        print(f"Error downloading uniques list: {str(e)}")
        return jsonify({'message': 'An error occurred while downloading the uniques list.', 'error': str(e)}), 500


@app.route('/process_skiptraced', methods=['POST'])
@jwt_required()
def process_skiptraced():
    uploaded_files = request.files.getlist('files')
    skip_traced_date = request.form.get('skip_traced_date')
    upload_date = str(datetime.now().date())

    if not uploaded_files:
        return jsonify({'message': 'No files uploaded.'}), 400
    
    try:
        processed_files = []

        for file in uploaded_files:
            df = pd.read_csv(file)
            # Verify the number of columns is what we expect
            num_col = len(df.columns)
            if num_col != 91:
                return jsonify({'message': f'Number of columns is not what we expect. Should be 91 but is {num_col}'}), 400
            else:

                # Modify column names
                df.columns = [col.lower().replace(" ", "_").replace("%", "percent").replace("-", "") for col in df.columns]

                # Column specific modifications
                df.rename(columns={'full_address': 'full_skiptrace_address'}, inplace=True)
                df.drop(columns=['has_duplicates'], inplace=True)

                # Add new columns with specified values at the end
                df["last_skiptraced_date"] = skip_traced_date
                df["sql_last_update_date"] = upload_date
                df["sql_added_date"] = upload_date

                df.insert(df.columns.get_loc("list")+1, "original_name", "")

                # Move specified owner-related columns
                owner_columns = df[['owner_1_name', 'owner_1_first_name', 'owner_1_last_name', 'owner_2_name', 'owner_2_first_name', 'owner_2_last_name']]
                df.drop(columns=owner_columns.columns, inplace=True)
                insert_index = df.columns.get_loc('original_name') + 1
                for col in owner_columns.columns:
                    df.insert(insert_index, col, owner_columns[col])
                    insert_index += 1

                # Insert new columns
                df.insert(df.columns.get_loc("owner_1_first_name")+1, 'owner_1_middle_name', '')
                df.insert(df.columns.get_loc("owner_2_first_name")+1, 'owner_2_middle_name', '')

                county_column = df.pop('county')
                df.insert(df.columns.get_loc("owner_2_last_name")+1, 'county', county_column)
                df.insert(df.columns.get_loc("county")+1, 'property_class', '')

                property_info_columns = df.loc[:, 'dob':'sql_added_date']
                df.drop(columns=property_info_columns.columns, inplace=True)
                df = pd.concat([df.iloc[:, :df.columns.get_loc("property_class")+1], property_info_columns, df.iloc[:, df.columns.get_loc("property_class")+1:]], axis=1)

                # Insert dispositions
                df.insert(df.columns.get_loc("phone1")+1, "phone1_cc_disposition", "")
                df.insert(df.columns.get_loc("phone1_cc_disposition")+1, "phone1_sms_disposition", "")
                df.insert(df.columns.get_loc("phone2_company")+1, "phone2_cc_disposition", "")
                df.insert(df.columns.get_loc("phone2_cc_disposition")+1, "phone2_sms_disposition", "")
                df.insert(df.columns.get_loc("phone3_company")+1, "phone3_cc_disposition", "")
                df.insert(df.columns.get_loc("phone3_cc_disposition")+1, "phone3_sms_disposition", "")

                # Move owner address details
                owner_columns = df[['owner_street_address', 'owner_city', 'owner_state', 'owner_zip_code']]
                df.drop(columns=owner_columns.columns, inplace=True)
                insert_index = df.columns.get_loc('sql_added_date') + 1
                for col in owner_columns.columns:
                    df.insert(insert_index, col, owner_columns[col])
                    insert_index += 1

                # Delete vacancy_description
                df.drop(columns=['vacancy_description'], inplace=True)

                # After all modifications, verify the number of columns again
                if len(df.columns) != 102:
                    return jsonify({'message': f'After modifications, the number of columns is not as expected: {len(df.columns)}'}), 400
                else:
                    processed_files.append(df)
                
                if not processed_files:
                    return jsonify({'message': 'No valid files processed.'}), 400
                
                conn = get_db_connection()
                cur = conn.cursor()

                for df in processed_files:
                    # Prepare the data for insertion
                    columns = df.columns.tolist()

                    # Merge the data with the my_master_list table
                    merge_query = f"""
                    INSERT INTO my_master_list ({','.join(columns)})
                    SELECT {','.join(columns)}
                    FROM (VALUES {','.join([str(tuple(row)) for row in df.itertuples(index=False)])}) AS new_data ({','.join(columns)})
                    ON CONFLICT (property_street_address, property_city, owner_1_first_name, owner_1_last_name)
                    DO UPDATE SET
                        phone1 = COALESCE(NULLIF(my_master_list.phone1, ''), NULLIF(new_data.phone1, '')),
                        phone2 = COALESCE(NULLIF(my_master_list.phone2, ''), NULLIF(new_data.phone2, '')),
                        phone3 = COALESCE(NULLIF(my_master_list.phone3, ''), NULLIF(new_data.phone3, '')),
                        email1 = COALESCE(NULLIF(my_master_list.email1, ''), NULLIF(new_data.email1, '')),
                        email2 = COALESCE(NULLIF(my_master_list.email2, ''), NULLIF(new_data.email2, '')),
                        last_skiptraced_date = NULLIF(new_data.last_skiptraced_date, ''),
                        sql_last_update_date = new_data.sql_last_update_date;
                    """

                    try:
                        cur.execute(merge_query)
                    except psycopg2.errors.UniqueViolation:
                        conn.rollback()
                        print(f"Duplicate key violation encountered. Skipping the insertion of duplicate records.")
                    except psycopg2.errors.InFailedSqlTransaction:
                        conn.rollback()
                        print(f"Transaction failed. Rolling back the changes.")
                    except Exception as e:
                        conn.rollback()
                        print(f"An error occurred while merging the data: {str(e)}")
                        raise
                
                conn.commit()
                cur.close()
                conn.close()

                return jsonify({
                    'message': 'Skiptraced data processed and merged successfully.',
                    'standardization': 'Successful',
                    'mergeStatus': 'Completed'
                }), 200
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        return jsonify({'message': 'An error occurred while processing the skiptraced data.', 'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
