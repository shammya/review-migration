import pandas as pd
import mysql.connector
import time

# Database connection details
DB_CONFIG = {
    "host": "",
    "user": "",
    "password": "",
    "database": "",
}

# Path to the CSV file
CSV_FILE_PATH = "deletion_ids.csv"

# Time delay between queries (in seconds)
DELAY_BETWEEN_BATCH_QUERIES = 10  # Adjust this based on server rate limits

# Batch size (number of records to delete at once)
BATCH_SIZE = 100  # Adjust based on performance needs

try:
    # Connect to the database
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()

    # Read CSV file
    df = pd.read_csv(CSV_FILE_PATH)

    # Ensure 'id' column exists in the CSV
    if "id" not in df.columns:
        raise ValueError("CSV file must contain an 'id' column.")

    # Prepare delete query
    delete_query = "DELETE FROM review_analysis WHERE id = %s"

    # Process in batches
    ids_to_delete = df["id"].tolist()

    for i in range(0, len(ids_to_delete), BATCH_SIZE):
        batch = ids_to_delete[i : i + BATCH_SIZE]

        # Execute delete query for each ID in batch
        for record_id in batch:
            cursor.execute(delete_query, (record_id,))

        time.sleep(DELAY_BETWEEN_BATCH_QUERIES)  # Respect rate limit

        # Commit batch deletion
        conn.commit()
        print(
            f"Deleted {len(batch)} records (Progress: {i + len(batch)}/{len(ids_to_delete)})"
        )

    print("All records deleted successfully.")

except mysql.connector.Error as err:
    print(f"Database Error: {err}")

except Exception as e:
    print(f"Error: {e}")

finally:
    # Close the connection
    if cursor:
        cursor.close()
    if conn:
        conn.close()
