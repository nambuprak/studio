
from flask import Flask, jsonify, request
from flask_cors import CORS
from pydantic import BaseModel, ValidationError, validator
from typing import List, Dict, Optional
import uuid
import json
import threading # For background tasks

# Refactored service imports
from services.database_service import init_db, save_tutor_config, get_all_tutors, get_tutor_by_id, update_tutor_processing_details
from services.processing_service import process_repository_content
from services.utils import extract_project_name_from_url, extract_project_name_from_path

app = Flask(__name__)
CORS(app)

# Initialize database on startup
init_db()

# --- In-memory store for processing status (POC only) ---
TUTOR_PROCESSING_STATUS: Dict[str, Dict] = {}


# --- Pydantic Models ---
class AdditionalInfoItemInput(BaseModel):
    title: str
    description: str

class CreateTutorInput(BaseModel):
    project_name: str
    input_type: str
    source_location: str
    repo_overview: str = ""
    tap_bap: str = ""
    file_types: str = ""
    exclude_folders: str = ""
    additional_info_list: List[AdditionalInfoItemInput] = []
    embed_repo: bool = False

    @validator('project_name')
    def project_name_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Project name cannot be empty')
        return v

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
    with app_context: 
        project_name_from_data = data.project_name # Use user-provided project name
        print(f"Background task started for tutor_id: {tutor_id}, project: {project_name_from_data}")

        TUTOR_PROCESSING_STATUS[tutor_id] = {
            "status": "PROCESSING_DB_SAVE",
            "message": f"Saving initial configuration for {project_name_from_data}...",
            "project_name": project_name_from_data,
            "tutor_id": tutor_id,
            "discovered_files_count": 0,
            "error": None
        }
        
        try:
            save_tutor_config(
                tutor_id=tutor_id,
                project_name=project_name_from_data,
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
            
            if data.embed_repo:
                print(f"Starting repository content processing for tutor_id: {tutor_id}")
                TUTOR_PROCESSING_STATUS[tutor_id]["status"] = "PROCESSING_EMBEDDING"
                TUTOR_PROCESSING_STATUS[tutor_id]["message"] = f"Embedding repository content for {project_name_from_data}..."
                
                discovered_files_count, processing_message = process_repository_content(
                    input_type=data.input_type,
                    source_location=data.source_location,
                    file_types_str=data.file_types,
                    exclude_folders_str=data.exclude_folders,
                    tutor_id=tutor_id,
                    status_dict=TUTOR_PROCESSING_STATUS.get(tutor_id, {}) 
                )
                TUTOR_PROCESSING_STATUS[tutor_id]["discovered_files_count"] = discovered_files_count
                TUTOR_PROCESSING_STATUS[tutor_id]["message"] = processing_message
                print(f"Repository processing completed for {tutor_id}. Files: {discovered_files_count}. Msg: {processing_message}")
            else:
                processing_message = "Self Tutor configuration saved. Embedding skipped by user."
                TUTOR_PROCESSING_STATUS[tutor_id]["message"] = processing_message
                print(f"Embedding skipped for tutor_id: {tutor_id}")

            update_tutor_processing_details(
                tutor_id=tutor_id,
                status_message=processing_message,
                discovered_files_count=discovered_files_count if data.embed_repo else None,
                processing_error=None
            )
            TUTOR_PROCESSING_STATUS[tutor_id]["status"] = "COMPLETED"
            TUTOR_PROCESSING_STATUS[tutor_id]["message"] = processing_message
            
        except Exception as e:
            print(f"Error during background processing for tutor_id {tutor_id}: {e}")
            error_message = f"Background processing failed for {project_name_from_data}: {str(e)}"
            TUTOR_PROCESSING_STATUS[tutor_id]["status"] = "FAILED"
            TUTOR_PROCESSING_STATUS[tutor_id]["message"] = error_message
            TUTOR_PROCESSING_STATUS[tutor_id]["error"] = str(e)
            try:
                update_tutor_processing_details(
                    tutor_id=tutor_id,
                    status_message="Processing failed.",
                    discovered_files_count=TUTOR_PROCESSING_STATUS[tutor_id].get("discovered_files_count", 0),
                    processing_error=str(e)
                )
            except Exception as db_error:
                print(f"Critical: Failed to update DB with error status for {tutor_id}: {db_error}")
        
        print(f"Background task finished for {tutor_id}. Final Status: {TUTOR_PROCESSING_STATUS[tutor_id]['status']}")


# --- API Endpoints ---
@app.route('/api/repos', methods=['GET'])
def get_repos_from_db_route():
    try:
        repos = get_all_tutors() # Fetches {id, name, source_location, input_type, status_message, discovered_files_count}
        return jsonify(repos)
    except Exception as e:
        print(f"Error fetching repos: {e}")
        return jsonify({"error": "Failed to fetch repositories"}), 500

@app.route('/api/tutor-details/<string:tutor_id>', methods=['GET'])
def get_tutor_details_route(tutor_id: str):
    try:
        tutor = get_tutor_by_id(tutor_id)
        if tutor:
            return jsonify(tutor)
        else:
            return jsonify({"error": "Tutor not found"}), 404
    except Exception as e:
        print(f"Error fetching tutor details for {tutor_id}: {e}")
        return jsonify({"error": f"Failed to fetch tutor details: {str(e)}"}), 500

@app.route('/api/tutor-details/<string:tutor_id>', methods=['PUT'])
def update_tutor_details_route(tutor_id: str):
    try:
        data = CreateTutorInput(**request.json) # Use the same model for validation
    except ValidationError as e:
        return jsonify({"error": "Invalid input", "details": e.errors()}), 400
    except Exception as e:
        return jsonify({"error": f"Error parsing request: {str(e)}"}), 400

    try:
        # For PUT, we might re-trigger embedding if embed_repo is true and source_location changed
        # For simplicity, this example directly updates the config.
        # A more robust solution would compare old and new values to decide if re-embedding is needed
        # or handle it similarly to the POST /api/analyze-repo with background processing.
        
        # For now, let's assume PUT updates metadata and doesn't re-trigger long processing.
        # If embed_repo is true and details impacting embedding change, you might want a separate flow.
        save_tutor_config( # This will effectively UPSERT or you might want a dedicated update function
            tutor_id=tutor_id,
            project_name=data.project_name,
            input_type=data.input_type,
            source_location=data.source_location,
            repo_overview=data.repo_overview,
            tap_bap=data.tap_bap,
            file_types_str=data.file_types,
            exclude_folders_str=data.exclude_folders,
            additional_info_list_json=json.dumps([item.model_dump() for item in data.additional_info_list]),
            embed_repo_flag=data.embed_repo,
            initial_status_message="Configuration updated." # Or reflect current embedding status
        )
        # If embed_repo is true, and source_location or other critical params changed,
        # you would re-initiate background processing similar to POST.
        # For this example, we'll assume metadata update mostly.
        
        # If embedding settings changed and embed_repo is true, you might want to re-process
        if data.embed_repo:
             # This is a simplified re-process trigger. Consider if full re-embedding is desired on PUT.
             # It might be better to have a separate endpoint or more granular logic.
            TUTOR_PROCESSING_STATUS[tutor_id] = {
                "status": "PENDING_REPROCESS", 
                "message": "Re-processing initiated due to update...", 
                "project_name": data.project_name,
                "tutor_id": tutor_id
            }
            thread = threading.Thread(target=_perform_long_repository_processing, args=(tutor_id, data, app.app_context()))
            thread.start()
            return jsonify({
                "message": "Self Tutor update accepted. Re-processing initiated if embedding is enabled.",
                "tutor_id": tutor_id,
                "project_name": data.project_name
            }), 202
        else:
            # Update processing details for non-embedding case
            update_tutor_processing_details(
                tutor_id=tutor_id,
                status_message="Configuration updated. Embedding not requested or re-processing skipped.",
                discovered_files_count=None, # Or fetch existing if not re-embedding
                processing_error=None
            )
            return jsonify({
                "message": "Self Tutor configuration updated successfully.",
                "tutor_id": tutor_id,
                "project_name": data.project_name
            }), 200

    except Exception as e:
        print(f"Error updating tutor {tutor_id}: {e}")
        return jsonify({"error": f"Database error during update: {str(e)}"}), 500


@app.route('/api/tutor-details/<string:tutor_id>', methods=['DELETE'])
def delete_tutor_route(tutor_id: str):
    conn = None
    try:
        from services.database_service import get_db_connection # Local import
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tutors WHERE id = ?", (tutor_id,))
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "Tutor not found or already deleted"}), 404
        
        # Clean up from in-memory status if it exists
        if tutor_id in TUTOR_PROCESSING_STATUS:
            del TUTOR_PROCESSING_STATUS[tutor_id]
            
        return jsonify({"message": "Tutor deleted successfully"}), 200
    except Exception as e:
        if conn: conn.rollback()
        print(f"Error deleting tutor {tutor_id}: {e}")
        return jsonify({"error": f"Failed to delete tutor: {str(e)}"}), 500
    finally:
        if conn: conn.close()


@app.route('/api/analyze-repo', methods=['POST'])
def analyze_repo_route():
    try:
        data = CreateTutorInput(**request.json)
    except ValidationError as e:
        return jsonify({"error": "Invalid input", "details": e.errors()}), 400
    except Exception as e:
        return jsonify({"error": f"Error parsing request JSON: {str(e)}"}), 400

    tutor_id = str(uuid.uuid4())
    
    if data.embed_repo:
        TUTOR_PROCESSING_STATUS[tutor_id] = {
            "status": "PENDING", 
            "message": f"Processing initiated for {data.project_name}...", 
            "project_name": data.project_name,
            "tutor_id": tutor_id,
            "error": None
        }
        thread = threading.Thread(target=_perform_long_repository_processing, args=(tutor_id, data, app.app_context()))
        thread.start()
        print(f"Background processing thread started for tutor_id: {tutor_id}")
        return jsonify({
            "message": "Self Tutor processing initiated. Check status for updates.",
            "tutor_id": tutor_id,
            "project_name": data.project_name
        }), 202
    else:
        try:
            save_tutor_config(
                tutor_id=tutor_id,
                project_name=data.project_name,
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
            update_tutor_processing_details(
                tutor_id=tutor_id,
                status_message="Self Tutor configuration saved. Embedding skipped.",
                discovered_files_count=None, 
                processing_error=None
            )
            return jsonify({
                "message": "Self Tutor configuration saved. Embedding skipped.",
                "tutor_id": tutor_id,
                "project_name": data.project_name,
                "discovered_files_count": "N/A (Embedding skipped)"
            }), 200
        except Exception as e:
            print(f"Database error during synchronous save_tutor_config for {tutor_id}: {e}")
            return jsonify({"error": f"Database error: {str(e)}"}), 500

@app.route('/api/tutor-status/<string:tutor_id>', methods=['GET'])
def get_tutor_status_route(tutor_id: str):
    status_info = TUTOR_PROCESSING_STATUS.get(tutor_id)
    if not status_info:
        conn = None
        try:
            from services.database_service import get_db_connection 
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT project_name, status_message, discovered_files_count, processing_error FROM tutors WHERE id = ?", (tutor_id,))
            row = cursor.fetchone()
            if row:
                db_project_name = row["project_name"]
                db_status_message = row["status_message"]
                db_discovered_files = row["discovered_files_count"]
                db_processing_error = row["processing_error"]
                
                current_status_from_db = "UNKNOWN_COMPLETED" 
                if "failed" in (db_status_message or "").lower() or db_processing_error:
                    current_status_from_db = "FAILED"
                elif "saved" in (db_status_message or "").lower() and db_discovered_files is not None:
                     current_status_from_db = "COMPLETED" # If files processed, it implies embedding happened
                elif "skipped" in (db_status_message or "").lower() and db_discovered_files is None:
                     current_status_from_db = "COMPLETED" # Embedding skipped is a form of completion

                # Populate in-memory store if it was missed (e.g. server restart)
                TUTOR_PROCESSING_STATUS[tutor_id] = {
                    "status": current_status_from_db,
                    "message": db_status_message or "Status retrieved from DB.",
                    "project_name": db_project_name,
                    "tutor_id": tutor_id,
                    "discovered_files_count": db_discovered_files,
                    "error": db_processing_error
                }
                return jsonify(TUTOR_PROCESSING_STATUS[tutor_id]), 200
            else:
                 return jsonify({"error": "Tutor status not found for ID.", "tutor_id": tutor_id}), 404
        except Exception as e:
            print(f"Error fetching status from DB for tutor {tutor_id}: {e}")
            return jsonify({"error": "Error fetching tutor status from DB."}), 500
        finally:
            if conn: conn.close()
    
    return jsonify(status_info), 200


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001, debug=True)

    