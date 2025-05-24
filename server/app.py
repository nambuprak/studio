
from flask import Flask, jsonify, request
from flask_cors import CORS
from pydantic import BaseModel, ValidationError, validator
from typing import List, Dict
import uuid
import json
import threading # For background tasks

# Refactored service imports
from services.database_service import init_db, save_tutor_config, get_all_tutors, update_tutor_processing_details
from services.processing_service import process_repository_content
from services.utils import extract_project_name_from_url, extract_project_name_from_path

app = Flask(__name__)
CORS(app)

# Initialize database on startup
init_db()

# --- In-memory store for processing status (POC only) ---
# For production, use Redis, a database table, or a proper task queue system
TUTOR_PROCESSING_STATUS: Dict[str, Dict] = {}


# --- Pydantic Models ---
class AdditionalInfoItemInput(BaseModel):
    title: str
    description: str

class CreateTutorInput(BaseModel):
    input_type: str
    source_location: str
    repo_overview: str = ""
    tap_bap: str = ""
    file_types: str = ""
    exclude_folders: str = ""
    additional_info_list: List[AdditionalInfoItemInput] = []
    embed_repo: bool = False

    @validator('source_location')
    def source_location_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Source location (folder path or URL) cannot be empty')
        return v

    @validator('input_type')
    def input_type_must_be_valid(cls, v):
        if v not in ['folder', 'url']:
            raise ValueError("Input type must be 'folder' or 'url'")
        return v

# --- Background Processing Function ---
def _perform_long_repository_processing(tutor_id: str, data: CreateTutorInput, app_context):
    with app_context: # Ensure Flask app context is available in the thread
        print(f"Background task started for tutor_id: {tutor_id}")
        project_name = ""
        if data.input_type == 'url':
            project_name = extract_project_name_from_url(data.source_location)
        elif data.input_type == 'folder':
            project_name = extract_project_name_from_path(data.source_location)

        TUTOR_PROCESSING_STATUS[tutor_id] = {
            "status": "PROCESSING_DB_SAVE",
            "message": f"Saving initial configuration for {project_name}...",
            "project_name": project_name,
            "tutor_id": tutor_id,
            "discovered_files_count": 0,
            "error": None
        }
        
        try:
            save_tutor_config(
                tutor_id=tutor_id,
                project_name=project_name,
                input_type=data.input_type,
                source_location=data.source_location,
                repo_overview=data.repo_overview,
                tap_bap=data.tap_bap,
                file_types_str=data.file_types,
                exclude_folders_str=data.exclude_folders,
                additional_info_list_json=json.dumps([item.model_dump() for item in data.additional_info_list]),
                embed_repo_flag=data.embed_repo,
                initial_status_message="Configuration saved. Awaiting embedding if requested."
            )
            TUTOR_PROCESSING_STATUS[tutor_id]["message"] = "Configuration saved. Starting repository processing..."
            print(f"Configuration saved for tutor_id: {tutor_id}")

            discovered_files_count = 0
            processing_message = "Self Tutor configuration saved."
            processing_error_detail = None

            if data.embed_repo:
                print(f"Starting repository content processing for tutor_id: {tutor_id}")
                TUTOR_PROCESSING_STATUS[tutor_id]["status"] = "PROCESSING_EMBEDDING"
                TUTOR_PROCESSING_STATUS[tutor_id]["message"] = "Embedding repository content..."
                
                discovered_files_count, processing_message = process_repository_content(
                    input_type=data.input_type,
                    source_location=data.source_location,
                    file_types_str=data.file_types,
                    exclude_folders_str=data.exclude_folders,
                    tutor_id=tutor_id,
                    status_dict=TUTOR_PROCESSING_STATUS.get(tutor_id, {}) # Pass status dict for updates
                )
                TUTOR_PROCESSING_STATUS[tutor_id]["discovered_files_count"] = discovered_files_count
                TUTOR_PROCESSING_STATUS[tutor_id]["message"] = processing_message
                print(f"Repository processing completed for tutor_id: {tutor_id}. Files: {discovered_files_count}. Msg: {processing_message}")
            else:
                processing_message = "Self Tutor configuration saved. Embedding skipped by user."
                TUTOR_PROCESSING_STATUS[tutor_id]["message"] = processing_message
                print(f"Embedding skipped for tutor_id: {tutor_id}")

            # Update DB with final status from processing
            update_tutor_processing_details(
                tutor_id=tutor_id,
                status_message=processing_message,
                discovered_files_count=discovered_files_count if data.embed_repo else None, # Store count only if embedded
                processing_error=None # No error in this path
            )
            TUTOR_PROCESSING_STATUS[tutor_id]["status"] = "COMPLETED"
            TUTOR_PROCESSING_STATUS[tutor_id]["message"] = processing_message # Final success message
            
        except Exception as e:
            print(f"Error during background processing for tutor_id {tutor_id}: {e}")
            error_message = f"Background processing failed: {str(e)}"
            TUTOR_PROCESSING_STATUS[tutor_id]["status"] = "FAILED"
            TUTOR_PROCESSING_STATUS[tutor_id]["message"] = error_message
            TUTOR_PROCESSING_STATUS[tutor_id]["error"] = str(e)
            try:
                # Attempt to update DB with error status
                update_tutor_processing_details(
                    tutor_id=tutor_id,
                    status_message="Processing failed.",
                    discovered_files_count=TUTOR_PROCESSING_STATUS[tutor_id].get("discovered_files_count", 0),
                    processing_error=str(e)
                )
            except Exception as db_error:
                print(f"Critical: Failed to update DB with error status for tutor_id {tutor_id}: {db_error}")
        
        print(f"Background task finished for tutor_id: {tutor_id}. Final Status: {TUTOR_PROCESSING_STATUS[tutor_id]['status']}")


# --- API Endpoints ---
@app.route('/api/repos', methods=['GET'])
def get_repos_from_db_route():
    try:
        repos = get_all_tutors()
        return jsonify(repos)
    except Exception as e:
        print(f"Error fetching repos: {e}")
        return jsonify({"error": "Failed to fetch repositories"}), 500

@app.route('/api/analyze-repo', methods=['POST'])
def analyze_repo_route():
    try:
        data = CreateTutorInput(**request.json)
    except ValidationError as e:
        return jsonify({"error": "Invalid input", "details": e.errors()}), 400
    except Exception as e:
        print(f"Error parsing request: {e}")
        return jsonify({"error": f"Error parsing request JSON: {str(e)}"}), 400

    tutor_id = str(uuid.uuid4())
    project_name = ""
    if data.input_type == 'url':
        project_name = extract_project_name_from_url(data.source_location)
    elif data.input_type == 'folder':
        project_name = extract_project_name_from_path(data.source_location)
    
    if data.embed_repo:
        # Initiate background processing
        TUTOR_PROCESSING_STATUS[tutor_id] = {
            "status": "PENDING", 
            "message": "Processing initiated...", 
            "project_name": project_name,
            "tutor_id": tutor_id
        }
        # Pass Flask app context to the new thread
        thread = threading.Thread(target=_perform_long_repository_processing, args=(tutor_id, data, app.app_context()))
        thread.start()
        print(f"Background processing thread started for tutor_id: {tutor_id}")
        return jsonify({
            "message": "Self Tutor processing initiated. Check status for updates.",
            "tutor_id": tutor_id,
            "project_name": project_name
        }), 202  # HTTP 202 Accepted
    else:
        # Synchronous processing if not embedding
        try:
            save_tutor_config(
                tutor_id=tutor_id,
                project_name=project_name,
                input_type=data.input_type,
                source_location=data.source_location,
                repo_overview=data.repo_overview,
                tap_bap=data.tap_bap,
                file_types_str=data.file_types,
                exclude_folders_str=data.exclude_folders,
                additional_info_list_json=json.dumps([item.model_dump() for item in data.additional_info_list]),
                embed_repo_flag=data.embed_repo,
                initial_status_message="Configuration saved. Embedding skipped."
            )
            # Update DB directly as it's synchronous
            update_tutor_processing_details(
                tutor_id=tutor_id,
                status_message="Self Tutor configuration saved. Embedding skipped.",
                discovered_files_count=None, # No files processed if embedding is skipped
                processing_error=None
            )
            return jsonify({
                "message": "Self Tutor configuration saved. Embedding skipped.",
                "tutor_id": tutor_id,
                "project_name": project_name,
                "discovered_files_count": "N/A (Embedding skipped)"
            }), 200
        except Exception as e:
            print(f"Database error during synchronous save_tutor_config for {tutor_id}: {e}")
            return jsonify({"error": f"Database error: {str(e)}"}), 500

@app.route('/api/tutor-status/<string:tutor_id>', methods=['GET'])
def get_tutor_status_route(tutor_id: str):
    status_info = TUTOR_PROCESSING_STATUS.get(tutor_id)
    if not status_info:
        # Check DB if not in memory (e.g., after server restart, or if processing finished before first poll)
        conn = None
        try:
            from services.database_service import get_db_connection # Local import to avoid circular if any
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT status_message, discovered_files_count, processing_error FROM tutors WHERE id = ?", (tutor_id,))
            row = cursor.fetchone()
            if row:
                db_status_message = row["status_message"]
                db_discovered_files = row["discovered_files_count"]
                db_processing_error = row["processing_error"]
                
                current_status = "UNKNOWN_COMPLETED" # Default if we only have DB record
                if "failed" in (db_status_message or "").lower() or db_processing_error:
                    current_status = "FAILED"
                elif "saved" in (db_status_message or "").lower() and "skipped" not in (db_status_message or "").lower() and db_discovered_files is not None : # simple heuristic
                     current_status = "COMPLETED"
                elif "skipped" in (db_status_message or "").lower():
                     current_status = "COMPLETED" # Embedding skipped is a form of completion

                return jsonify({
                    "status": current_status, 
                    "message": db_status_message or "Status not found in memory, retrieved from DB.",
                    "discovered_files_count": db_discovered_files,
                    "error": db_processing_error
                }), 200
            else:
                 return jsonify({"error": "Tutor status not found."}), 404
        except Exception as e:
            print(f"Error fetching status from DB for tutor {tutor_id}: {e}")
            return jsonify({"error": "Error fetching tutor status from DB."}), 500
        finally:
            if conn:
                conn.close()
    
    return jsonify(status_info), 200


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001, debug=True)
