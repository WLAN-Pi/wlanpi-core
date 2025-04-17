import sqlite3


def list_all_tables(db_path):
    """
    Retrieves all table names from the SQLite database.

    :param db_path: Path to the SQLite database file.
    :return: List of table names.
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        table_names = [table[0] for table in tables]
        return table_names

    except sqlite3.Error as e:
        print(f"An error occurred while retrieving table names: {e}")
        return []

    finally:
        if conn:
            conn.close()


def list_table_records(db_path, table_name):
    """
    Retrieves and prints all records from a specified table.

    :param db_path: Path to the SQLite database file.
    :param table_name: Name of the table to retrieve records from.
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM {table_name};")
        records = cursor.fetchall()
        column_names = [description[0] for description in cursor.description]
        if records:
            header = " | ".join(column_names)
            print(header)
            print("-*" * (len(header) // 2))
            for record in records:
                record_str = " | ".join(str(item) for item in record)
                print(record_str)
        else:
            print("No records found.")
    except sqlite3.Error as e:
        print(f"An error occurred while accessing the '{table_name}' table: {e}")

    finally:
        if conn:
            conn.close()


def main():
    database_path = "/home/wlanpi/.local/share/wlanpi-core/secrets/tokens.db"
    tables = list_all_tables(database_path)
    if not tables:
        print("No tables found in the database.")
        return
    for table in tables:
        print(f"\n\\\\\ Records in '{table}' ///")
        list_table_records(database_path, table)


if __name__ == "__main__":
    main()
