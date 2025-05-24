
from flask import Flask, jsonify, request
from flask_cors import CORS
import git # For Git operations
import os # For file system operations like walking directories
import shutil # For removing directories
import sqlite3
import json
import uuid
from pydantic import BaseModel, ValidationError, validator
from typing import List, Dict
from urllib.parse import urlparse

app = Flask(__name__)
CORS(app)

DATABASE_URL = "self_tutor.db"

# --- Pydantic Models ---
class AdditionalInfoItemInput(BaseModel):
    title: str
    description: str

class CreateTutorInput(BaseModel):
    repo_url: str
    repo_overview: str = ""
    tap_bap: str = ""
    file_types: str = ""
    exclude_folders: str = ""
    additional_info_list: List[AdditionalInfoItemInput] = []
    embed_repo: bool = False

    @validator('repo_url')
    def repo_url_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Repository URL cannot be empty')
        return v

# --- Database Helper Functions ---
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
            repo_url TEXT NOT NULL,
            repo_overview TEXT,
            tap_bap TEXT,
            file_types TEXT,
            exclude_folders TEXT,
            additional_info_list TEXT,
            embed_repo INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db() # Initialize database on startup

# --- Helper to extract project name from URL ---
def extract_project_name_from_url(repo_url: str) -> str:
    try:
        path = urlparse(repo_url).path
        name_with_ext = os.path.basename(path)
        project_name, _ = os.path.splitext(name_with_ext)
        return project_name if project_name else "untitled_project"
    except Exception:
        return "untitled_project"

# --- API Endpoints ---
@app.route('/api/repos', methods=['GET'])
def get_repos_from_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, project_name as name FROM tutors ORDER BY created_at DESC")
    repos = cursor.fetchall()
    conn.close()
    return jsonify([dict(row) for row in repos])

@app.route('/api/analyze-repo', methods=['POST'])
def analyze_repo():
    try:
        data = CreateTutorInput(**request.json)
    except ValidationError as e:
        return jsonify({"error": "Invalid input", "details": e.errors()}), 400
    except Exception as e:
        return jsonify({"error": f"Error parsing request JSON: {str(e)}"}), 400

    tutor_id = str(uuid.uuid4())
    project_name = extract_project_name_from_url(data.repo_url)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO tutors (id, project_name, repo_url, repo_overview, tap_bap, file_types, exclude_folders, additional_info_list, embed_repo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            tutor_id,
            project_name,
            data.repo_url,
            data.repo_overview,
            data.tap_bap,
            data.file_types,
            data.exclude_folders,
            json.dumps([item.model_dump() for item in data.additional_info_list]), # Pydantic v2 uses model_dump()
            1 if data.embed_repo else 0
        ))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        conn.close()
        print(f"Database error: {e}")
        return jsonify({"error": f"Database error: {str(e)}"}), 500
    finally:
        conn.close()

    analysis_result = {
        "message": "Self Tutor configuration saved.",
        "tutor_id": tutor_id,
        "project_name": project_name,
        "repo_url": data.repo_url,
    }

    if data.embed_repo:
        temp_clone_dir = f"temp_repo_clone_{tutor_id}" # Unique temp dir
        
        try:
            if os.path.exists(temp_clone_dir):
                print(f"Cleaning up pre-existing temporary directory: {temp_clone_dir}")
                shutil.rmtree(temp_clone_dir)
            os.makedirs(temp_clone_dir, exist_ok=True)

            print(f"Cloning repository: {data.repo_url} into {temp_clone_dir}")
            git.Repo.clone_from(data.repo_url, temp_clone_dir)
            print("Repository cloned successfully.")

            processed_files = []
            file_types_to_include = [ft.strip() for ft in data.file_types.split(',') if ft.strip() and ft.startswith('.')]
            folders_to_exclude = {fd.strip() for fd in data.exclude_folders.split(',') if fd.strip()}
            
            print(f"Including file types: {file_types_to_include}")
            print(f"Excluding folders: {folders_to_exclude}")

            for root, dirs, files in os.walk(temp_clone_dir, topdown=True):
                dirs[:] = [d for d in dirs if d not in folders_to_exclude]
                
                for file_name in files:
                    if not file_types_to_include:
                        processed_files.append(os.path.join(root, file_name))
                    else:
                        _, ext = os.path.splitext(file_name)
                        if ext in file_types_to_include:
                            processed_files.append(os.path.join(root, file_name))
            
            analysis_result["message"] = "Self Tutor configuration saved and repository processed."
            analysis_result["discovered_files_count"] = len(processed_files)
            print(f"Discovered {len(processed_files)} files after filtering.")
            # Actual file content processing would go here.

        except git.exc.GitCommandError as e:
            print(f"Git cloning error: {e}")
            # Update DB to indicate embedding failed? Or just return error.
            # For now, just return error in response, data is already saved.
            analysis_result["embedding_error"] = f"Failed to clone repository: {e.stderr}"
        except Exception as e:
            print(f"Error processing repository: {e}")
            analysis_result["embedding_error"] = f"An unexpected error occurred during embedding: {str(e)}"
        finally:
            if os.path.exists(temp_clone_dir):
                print(f"Cleaning up temporary directory: {temp_clone_dir}")
                try:
                    shutil.rmtree(temp_clone_dir)
                    print(f"Successfully removed {temp_clone_dir}")
                except Exception as e_rm:
                    print(f"Error removing temporary directory {temp_clone_dir}: {e_rm}")
            else:
                print(f"Temporary directory {temp_clone_dir} not found for cleanup.")
    else:
        print("Repository embedding skipped by user.")
        analysis_result["discovered_files_count"] = "N/A (Embedding skipped)"


    return jsonify(analysis_result), 200


if __name__ == '__main__':
    init_db() # Ensure DB is initialized when run directly
    app.run(host='127.0.0.1', port=5001, debug=True)
