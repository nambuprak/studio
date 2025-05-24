
import sqlite3
import json

DATABASE_URL = "self_tutor.db" 

def get_db_connection():
    conn = sqlite3.connect(DATABASE_URL) 
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Ensure project_name is not null. Add status_message, discovered_files_count, processing_error
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tutors (
            id TEXT PRIMARY KEY,
            project_name TEXT NOT NULL,
            input_type TEXT NOT NULL, 
            source_location TEXT NOT NULL, 
            repo_overview TEXT,
            tap_bap TEXT,
            file_types TEXT,
            exclude_folders TEXT,
            additional_info_list TEXT, 
            embed_repo INTEGER, 
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status_message TEXT,
            discovered_files_count INTEGER,
            processing_error TEXT 
        )
    ''')
    conn.commit()
    conn.close()
    print(f"Database initialization complete: '{DATABASE_URL}' ensured to have 'tutors' table with updated schema.")

def save_tutor_config(tutor_id: str, project_name: str, input_type: str, source_location: str,
                        repo_overview: str, tap_bap: str, file_types_str: str,
                        exclude_folders_str: str, additional_info_list_json: str,
                        embed_repo_flag: bool, initial_status_message: str = "Pending"):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Using INSERT OR REPLACE for simplicity in a PUT scenario,
        # though a dedicated UPDATE would be more standard for PUT.
        cursor.execute('''
            INSERT OR REPLACE INTO tutors (
                id, project_name, input_type, source_location, repo_overview, tap_bap, 
                file_types, exclude_folders, additional_info_list, embed_repo,
                status_message, created_at, discovered_files_count, processing_error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 
                    COALESCE((SELECT created_at FROM tutors WHERE id = ?), CURRENT_TIMESTAMP),
                    COALESCE((SELECT discovered_files_count FROM tutors WHERE id = ?), NULL),
                    COALESCE((SELECT processing_error FROM tutors WHERE id = ?), NULL)
            )
        ''', (
            tutor_id, project_name, input_type, source_location, repo_overview, tap_bap,
            file_types_str, exclude_folders_str, additional_info_list_json,
            1 if embed_repo_flag else 0, initial_status_message,
            tutor_id, tutor_id, tutor_id # For COALESCE to preserve existing values on REPLACE
        ))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        print(f"Error during save_tutor_config for {tutor_id} (Project: {project_name}): {e}") 
        raise e
    finally:
        conn.close()

def update_tutor_processing_details(tutor_id: str, status_message: str, discovered_files_count: int = None, processing_error: str = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        print(f"Updating DB for {tutor_id}: status='{status_message}', files={discovered_files_count}, error='{processing_error}'")
        cursor.execute('''
            UPDATE tutors 
            SET status_message = ?, discovered_files_count = ?, processing_error = ?
            WHERE id = ?
        ''', (status_message, discovered_files_count, processing_error, tutor_id))
        conn.commit()
        if cursor.rowcount == 0:
            print(f"Warning: No rows updated for tutor_id {tutor_id} during update_tutor_processing_details. Record might not exist.")
    except sqlite3.Error as e:
        conn.rollback()
        print(f"Error during update_tutor_processing_details for {tutor_id}: {e}")
        raise e
    finally:
        conn.close()


def get_all_tutors() -> list:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Fetch all relevant fields for the tutor list display
        cursor.execute("SELECT id, project_name as name, source_location, input_type, status_message, discovered_files_count FROM tutors ORDER BY created_at DESC")
        repos = cursor.fetchall()
        if not repos:
            print("No tutors found in the database.")
        return [dict(row) for row in repos]
    except sqlite3.Error as e:
        print(f"Error during get_all_tutors: {e}") 
        return [] 
    finally:
        conn.close()

def get_tutor_by_id(tutor_id: str) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM tutors WHERE id = ?", (tutor_id,))
        row = cursor.fetchone()
        if row:
            tutor_data = dict(row)
            # Parse additional_info_list from JSON string to Python list
            if tutor_data.get('additional_info_list'):
                try:
                    tutor_data['additional_info_list'] = json.loads(tutor_data['additional_info_list'])
                except json.JSONDecodeError:
                    print(f"Warning: Could not parse additional_info_list for tutor {tutor_id}")
                    tutor_data['additional_info_list'] = [] # Default to empty list on error
            else:
                tutor_data['additional_info_list'] = []
            return tutor_data
        return None
    except sqlite3.Error as e:
        print(f"Error during get_tutor_by_id for {tutor_id}: {e}")
        return None
    finally:
        conn.close()

    