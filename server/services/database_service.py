
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
        cursor.execute('''
            INSERT INTO tutors (
                id, project_name, input_type, source_location, repo_overview, tap_bap, 
                file_types, exclude_folders, additional_info_list, embed_repo,
                status_message 
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            tutor_id, project_name, input_type, source_location, repo_overview, tap_bap,
            file_types_str, exclude_folders_str, additional_info_list_json,
            1 if embed_repo_flag else 0, initial_status_message
        ))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        print(f"Error during save_tutor_config: {e}") 
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
            print(f"Warning: No rows updated for tutor_id {tutor_id}. Record might not exist or ID is incorrect.")
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

