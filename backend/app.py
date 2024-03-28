from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import pandas as pd
from database import get_db_connection
import io

app = Flask(__name__)
CORS(app)

@app.route('/process_spreadsheets', methods=['POST'])
def process_spreadsheets():
    uploaded_files = request.files.getlist('files')
    source_name = request.form.get('source_name')
    list_name = request.form.get('list_name')

    if not uploaded_files:
        return jsonify({'message': 'No files uploaded.'}), 400

    if not source_name or not list_name:
        return jsonify({'message': 'Source name or list name not provided.'}), 400

    processed_files = []

    for file in uploaded_files:
        df = pd.read_csv(file)

        if len(df.columns) != 70:
            return jsonify({'message': 'The spreadsheet must contain exactly 70 columns.'}), 400

        df.insert(0, 'source_name', source_name)
        df.insert(1, 'list', list_name)
        df.columns = [col.lower().replace(" ", "_").replace("%", "percent").replace("-", "") for col in df.columns]
        column_renames = {
            'property_county': 'county',
            'rank': 'rank_number',
            'tax_delinquent_year': 'tax_delinquency_year',
            'tax_delinquent_first_seen': 'tax_delinquency_first_seen',
            'tax_delinquent_last_updated': 'tax_delinquency_last_updated'
        }
        df.rename(columns=column_renames, inplace=True)

        processed_files.append(df)

    if not processed_files:
        return jsonify({'message': 'No valid files processed.'}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()

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

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({'message': 'Spreadsheets processed successfully.', 'unique_count': unique_count}), 200

    except Exception as e:
        return jsonify({'message': 'An error occurred while processing the spreadsheets.', 'error': str(e)}), 500

@app.route('/download_uniques_list', methods=['GET'])
def download_uniques_list():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT * FROM uniques_list")
        data = cur.fetchall()
        columns = [desc[0] for desc in cur.description]

        cur.close()
        conn.close()

        df = pd.DataFrame(data, columns=columns)

        # Create a BytesIO object to store the CSV data
        csv_buffer = io.BytesIO()
        df.to_csv(csv_buffer, index=False)
        csv_buffer.seek(0)

        # Return the CSV file as a download attachment
        return send_file(csv_buffer, mimetype='text/csv', as_attachment=True, attachment_filename='uniques_list.csv')

    except Exception as e:
        return jsonify({'message': 'An error occurred while downloading the uniques list.', 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
