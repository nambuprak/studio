
import sqlite3
import json

DATABASE_URL = "self_tutor.db" # Relative to where app.py is run (server folder)

def get_db_connection():
    conn = sqlite3.connect(DATABASE_URL) # SQLite creates the file if it doesn't exist
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Removed: cursor.execute("DROP TABLE IF EXISTS tutors")
    # This ensures the table is created if it doesn't exist,
    # and preserves existing data if the table is already there.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tutors (
            id TEXT PRIMARY KEY,
            project_name TEXT NOT NULL,
            input_type TEXT NOT NULL, -- 'folder' or 'url'
            source_location TEXT NOT NULL, -- Stores either folder path or repo URL
            repo_overview TEXT,
            tap_bap TEXT,
            file_types TEXT,
            exclude_folders TEXT,
            additional_info_list TEXT, -- Stored as JSON string
            embed_repo INTEGER, -- 0 for False, 1 for True
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    # Updated print statement for clarity
    print("Database initialization complete. 'tutors' table ensured to exist.")

def save_tutor_config(tutor_id: str, project_name: str, input_type: str, source_location: str,
                        repo_overview: str, tap_bap: str, file_types_str: str,
                        exclude_folders_str: str, additional_info_list_json: str,
                        embed_repo_flag: bool):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO tutors (id, project_name, input_type, source_location, repo_overview, tap_bap, file_types, exclude_folders, additional_info_list, embed_repo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            tutor_id,
            project_name,
            input_type,
            source_location,
            repo_overview,
            tap_bap,
            file_types_str,
            exclude_folders_str,
            additional_info_list_json,
            1 if embed_repo_flag else 0
        ))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        print(f"Error during save_tutor_config: {e}") # Added print for debugging
        raise e # Re-raise the exception to be caught by the caller
    finally:
        conn.close()

def get_all_tutors() -> list:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Return 'name' aliased as project_name for frontend compatibility
        # Also selecting source_location and input_type as they might be useful later for display
        cursor.execute("SELECT id, project_name as name, source_location, input_type FROM tutors ORDER BY created_at DESC")
        repos = cursor.fetchall()
        return [dict(row) for row in repos]
    except sqlite3.Error as e:
        print(f"Error during get_all_tutors: {e}") # Added print for debugging
        # If the table doesn't exist, this is where "no such table" would occur.
        # init_db() should prevent this.
        return [] # Return empty list on error
    finally:
        conn.close()

# Ensure DB is initialized when this module is loaded if app.py doesn't call it explicitly.
# However, it's better practice to call init_db() from the main app startup.
# app.py already calls init_db(), so this line is usually not strictly needed here
# but doesn't harm if called multiple times with "CREATE TABLE IF NOT EXISTS".
# init_db()
