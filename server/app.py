
from flask import Flask, jsonify, request
from flask_cors import CORS
from pydantic import BaseModel, ValidationError, validator
from typing import List, Dict, Optional
import uuid
import json
import threading # For background tasks

# Refactored service imports
from server.services.database_service import init_db, save_tutor_config, get_all_tutors, get_tutor_by_id, update_tutor_processing_details
from server.services.processing_service import process_repository_content
from server.services.utils import extract_project_name_from_url, extract_project_name_from_path

app = Flask(__name__)
CORS(app)

# Initialize database on startup
init_db()

# --- In-memory store for processing status (POC only) ---
# This will store status updates for ongoing processing jobs.
# Key: tutor_id, Value: {"status": "PROCESSING/COMPLETED/FAILED", "message": "...", "project_name": "...", "tutor_id": "...", "discovered_files_count": 0, "error": None}
TUTOR_PROCESSING_STATUS: Dict[str, Dict] = {}


# --- Pydantic Models ---
class AdditionalInfoItemInput(BaseModel):
    title: str
    description: str

class CreateTutorInput(BaseModel):
    project_name: str # Now explicitly provided by user
    input_type: str # 'folder' or 'url'
    source_location: str # Can be a local path or a Git URL
    repo_overview: str = ""
    tap_bap: str = ""
    file_types: str = ""
    exclude_folders: str = ""
    additional_info_list: List[AdditionalInfoItemInput] = []
    embed_repo: bool = False # Checkbox from frontend

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
    """
    This function runs in a background thread to handle repository processing and embedding.
    It updates the TUTOR_PROCESSING_STATUS dictionary and the database.
    """
    with app_context: # Ensures Flask app context is available in the thread
        project_name_from_data = data.project_name
        print(f"Background task started for tutor_id: {tutor_id}, project: {project_name_from_data}")

        # Initial status update
        current_status = {
            "status": "PROCESSING_DB_SAVE", # More granular status
            "message": f"Saving initial configuration for {project_name_from_data}...",
            "project_name": project_name_from_data,
            "tutor_id": tutor_id,
            "discovered_files_count": 0, # Will be updated by processing_service
            "error": None
        }
        TUTOR_PROCESSING_STATUS[tutor_id] = current_status
        
        try:
            # 1. Save initial tutor configuration to DB
            save_tutor_config(
                tutor_id=tutor_id,
                project_name=project_name_from_data, # Use user-provided name
                input_type=data.input_type,
                source_location=data.source_location,
                repo_overview=data.repo_overview,
                tap_bap=data.tap_bap,
                file_types_str=data.file_types,
                exclude_folders_str=data.exclude_folders,
                # Pydantic model data.additional_info_list is already List[AdditionalInfoItemInput]
                # We need to convert it to list of dicts for json.dumps
                additional_info_list_json=json.dumps([item.model_dump() for item in data.additional_info_list]),
                embed_repo_flag=data.embed_repo,
                initial_status_message="Configuration saved. Awaiting embedding if requested." # Initial DB status
            )
            _update_status_safely(current_status, message="Configuration saved. Starting repository processing if embedding is enabled...")
            print(f"Configuration saved for tutor_id: {tutor_id}")

            discovered_files_count = 0
            processing_message = "Self Tutor configuration saved." # Default message
            
            # 2. Process repository content (cloning, file walking, embedding)
            # This part is conditional on data.embed_repo
            if data.embed_repo:
                print(f"Starting repository content processing (including embedding) for tutor_id: {tutor_id}")
                _update_status_safely(current_status, status="PROCESSING_EMBEDDING", message=f"Processing and embedding repository content for {project_name_from_data}...")
                
                # Convert Pydantic AdditionalInfoItemInput to simple dicts for processing_service
                additional_info_dicts = [item.model_dump() for item in data.additional_info_list]

                # process_repository_content will update current_status (via status_dict)
                # and will handle embedding via embedding_service
                discovered_files_count, processing_message_from_service = process_repository_content(
                    input_type=data.input_type,
                    source_location=data.source_location,
                    file_types_str=data.file_types,
                    exclude_folders_str=data.exclude_folders,
                    tutor_id=tutor_id,
                    embed_repo_flag=data.embed_repo, # Pass this down
                    repo_overview=data.repo_overview,
                    additional_info_list=additional_info_dicts,
                    status_dict=current_status # Pass the shared status dict for updates
                )
                # Update current_status with results from processing
                current_status["discovered_files_count"] = discovered_files_count
                current_status["message"] = processing_message_from_service # Use message from service
                processing_message = processing_message_from_service # For DB update later
                print(f"Repository processing completed for {tutor_id}. Files: {discovered_files_count}. Msg: {processing_message}")
            else:
                processing_message = "Self Tutor configuration saved. Embedding skipped by user."
                _update_status_safely(current_status, message=processing_message)
                print(f"Embedding skipped for tutor_id: {tutor_id}")

            # 3. Update database with final processing details
            update_tutor_processing_details(
                tutor_id=tutor_id,
                status_message=processing_message, # Final message for DB
                discovered_files_count=discovered_files_count if data.embed_repo else None,
                processing_error=current_status.get("error") # Get error from status_dict if any
            )
            _update_status_safely(current_status, status="COMPLETED", message=processing_message) # Final in-memory status
            
        except Exception as e:
            print(f"Error during background processing for tutor_id {tutor_id}: {e}")
            error_message_for_status = f"Background processing failed for {project_name_from_data}: {str(e)}"
            _update_status_safely(current_status, status="FAILED", message=error_message_for_status, error=str(e))
            
            # Attempt to update DB with failure status
            try:
                update_tutor_processing_details(
                    tutor_id=tutor_id,
                    status_message="Processing failed.", # Simplified DB error message
                    discovered_files_count=current_status.get("discovered_files_count", 0), # Get count if available
                    processing_error=str(e)
                )
            except Exception as db_error:
                print(f"Critical: Failed to update DB with error status for {tutor_id}: {db_error}")
        
        print(f"Background task finished for {tutor_id}. Final Status: {TUTOR_PROCESSING_STATUS.get(tutor_id, {}).get('status')}")

def _update_status_safely(status_dict: Dict[str, Any], message: str = None, status: str = None, error: Optional[str] = None, progress_detail: Optional[str] = None):
    """Helper to safely update the shared status dictionary."""
    if status_dict is None:
        return
    if message:
        status_dict["message"] = message
    if status:
        status_dict["status"] = status
    if error: # Could be None
        status_dict["error"] = error
    if progress_detail:
        status_dict["progress_detail"] = progress_detail


# --- API Endpoints ---
@app.route('/api/repos', methods=['GET'])
def get_repos_from_db_route():
    try:
        # Fetches {id, name (project_name), source_location, input_type, status_message, discovered_files_count}
        repos = get_all_tutors() 
        return jsonify(repos)
    except Exception as e:
        print(f"Error fetching repos: {e}")
        return jsonify({"error": "Failed to fetch repositories"}), 500

@app.route('/api/tutor-details/<string:tutor_id>', methods=['GET'])
def get_tutor_details_route(tutor_id: str):
    try:
        tutor = get_tutor_by_id(tutor_id)
        if tutor:
            return jsonify(tutor) # get_tutor_by_id already converts additional_info_list
        else:
            return jsonify({"error": "Tutor not found"}), 404
    except Exception as e:
        print(f"Error fetching tutor details for {tutor_id}: {e}")
        return jsonify({"error": f"Failed to fetch tutor details: {str(e)}"}), 500

@app.route('/api/tutor-details/<string:tutor_id>', methods=['PUT'])
def update_tutor_details_route(tutor_id: str):
    try:
        data = CreateTutorInput(**request.json) # Use the same model for validation & structure
    except ValidationError as e:
        return jsonify({"error": "Invalid input", "details": e.errors()}), 400
    except Exception as e: # Catch other parsing errors
        return jsonify({"error": f"Error parsing request: {str(e)}"}), 400

    try:
        # For PUT, if embed_repo is true and source_location or other embedding params change,
        # we might want to re-trigger the background processing.
        # For now, we'll save the config. If embed_repo is true, we re-start processing.
        
        # Update the configuration in the database
        save_tutor_config( # This will effectively UPSERT
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
            # Fetch existing status message or set to "Updated, awaiting re-processing"
            initial_status_message="Configuration updated. Awaiting re-processing if embedding enabled." 
        )
        
        if data.embed_repo:
            # If embedding is enabled, (re)start the background processing task
            TUTOR_PROCESSING_STATUS[tutor_id] = {
                "status": "PENDING_REPROCESS", 
                "message": "Re-processing initiated due to update...", 
                "project_name": data.project_name,
                "tutor_id": tutor_id,
                "error": None
            }
            thread = threading.Thread(target=_perform_long_repository_processing, args=(tutor_id, data, app.app_context()))
            thread.start()
            return jsonify({
                "message": "Self Tutor update accepted. Re-processing initiated as embedding is enabled.",
                "tutor_id": tutor_id,
                "project_name": data.project_name
            }), 202 # Accepted
        else:
            # If embedding is not requested, just update details and mark as completed (no embedding)
            update_tutor_processing_details(
                tutor_id=tutor_id,
                status_message="Configuration updated. Embedding not requested or re-processing skipped.",
                discovered_files_count=None, # Or fetch existing if not re-embedding
                processing_error=None
            )
            # Clear from in-memory processing status if it exists and embedding is now off
            if tutor_id in TUTOR_PROCESSING_STATUS:
                TUTOR_PROCESSING_STATUS[tutor_id]["status"] = "COMPLETED"
                TUTOR_PROCESSING_STATUS[tutor_id]["message"] = "Configuration updated. Embedding disabled."
                TUTOR_PROCESSING_STATUS[tutor_id]["discovered_files_count"] = None


            return jsonify({
                "message": "Self Tutor configuration updated successfully. Embedding not enabled.",
                "tutor_id": tutor_id,
                "project_name": data.project_name
            }), 200

    except Exception as e:
        print(f"Error updating tutor {tutor_id}: {e}")
        # Ensure this error is not from Pydantic validation if it's a DB error
        return jsonify({"error": f"Database or processing error during update: {str(e)}"}), 500


@app.route('/api/tutor-details/<string:tutor_id>', methods=['DELETE'])
def delete_tutor_route(tutor_id: str):
    # TODO: Also delete associated ChromaDB collection if it exists
    # collection_name_to_delete = f"tutor_{tutor_id.replace('-', '_')}"
    # try:
    #   chroma_client = chromadb.PersistentClient(path=PERSIST_DIR_BASE) # from embedding_service
    #   chroma_client.delete_collection(name=collection_name_to_delete)
    #   print(f"Deleted ChromaDB collection: {collection_name_to_delete}")
    # except Exception as e_chroma_del:
    #   print(f"Warning: Could not delete ChromaDB collection {collection_name_to_delete}: {e_chroma_del}")
    
    conn = None
    try:
        from server.services.database_service import get_db_connection # Local import for clarity
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
    except Exception as e: # Catch other JSON parsing errors
        return jsonify({"error": f"Error parsing request JSON: {str(e)}"}), 400

    tutor_id = str(uuid.uuid4())
    
    # Use user-provided project name directly
    project_name_to_use = data.project_name
    
    if data.embed_repo:
        # Initialize status for this new tutor_id before starting the thread
        TUTOR_PROCESSING_STATUS[tutor_id] = {
            "status": "PENDING", # Initial status before thread picks it up
            "message": f"Processing initiated for {project_name_to_use}...", 
            "project_name": project_name_to_use,
            "tutor_id": tutor_id,
            "error": None
        }
        # Start background thread for processing
        thread = threading.Thread(target=_perform_long_repository_processing, args=(tutor_id, data, app.app_context()))
        thread.start()
        print(f"Background processing thread started for tutor_id: {tutor_id}")
        # Return 202 Accepted immediately
        return jsonify({
            "message": "Self Tutor processing initiated. Check status for updates.",
            "tutor_id": tutor_id,
            "project_name": project_name_to_use
        }), 202
    else:
        # Synchronous path: Save config, no embedding
        try:
            save_tutor_config(
                tutor_id=tutor_id,
                project_name=project_name_to_use,
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
            # Also update processing details in DB for consistency
            update_tutor_processing_details(
                tutor_id=tutor_id,
                status_message="Self Tutor configuration saved. Embedding skipped.",
                discovered_files_count=None, # No files processed for embedding
                processing_error=None
            )
            return jsonify({
                "message": "Self Tutor configuration saved. Embedding skipped.",
                "tutor_id": tutor_id,
                "project_name": project_name_to_use,
                "discovered_files_count": "N/A (Embedding skipped)" # Provide clear info
            }), 200
        except Exception as e:
            print(f"Database error during synchronous save_tutor_config for {tutor_id}: {e}")
            return jsonify({"error": f"Database error: {str(e)}"}), 500

@app.route('/api/tutor-status/<string:tutor_id>', methods=['GET'])
def get_tutor_status_route(tutor_id: str):
    status_info = TUTOR_PROCESSING_STATUS.get(tutor_id)
    
    if not status_info:
        # If not in memory (e.g., server restart), try to fetch from DB
        conn = None
        try:
            from server.services.database_service import get_db_connection # Local import
            conn = get_db_connection()
            cursor = conn.cursor()
            # Fetch relevant fields to reconstruct a status-like object
            cursor.execute("SELECT project_name, status_message, discovered_files_count, processing_error FROM tutors WHERE id = ?", (tutor_id,))
            row = cursor.fetchone()
            if row:
                db_project_name = row["project_name"]
                db_status_message = row["status_message"]
                db_discovered_files = row["discovered_files_count"] # Could be None
                db_processing_error = row["processing_error"] # Could be None
                
                # Determine a 'status' field based on DB info
                current_status_from_db = "UNKNOWN_COMPLETED" # Default if status_message is vague
                if "failed" in (db_status_message or "").lower() or db_processing_error:
                    current_status_from_db = "FAILED"
                elif ("saved" in (db_status_message or "").lower() or "complete" in (db_status_message or "").lower()) and db_discovered_files is not None :
                     current_status_from_db = "COMPLETED" # If files processed, it implies embedding happened
                elif "skipped" in (db_status_message or "").lower() and db_discovered_files is None :
                     current_status_from_db = "COMPLETED" # Embedding skipped is a form of completion

                # Populate in-memory store if it was missed (e.g. server restart, or never started async)
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
                 # If not in memory and not in DB, it's a 404
                 return jsonify({"error": "Tutor status not found for ID. Record may not exist or processing never started.", "tutor_id": tutor_id}), 404
        except Exception as e:
            print(f"Error fetching status from DB for tutor {tutor_id}: {e}")
            # Return a generic error but don't assume it's a 404 for the tutor ID itself
            return jsonify({"error": "Error fetching tutor status from DB."}), 500
        finally:
            if conn: conn.close()
    
    # If found in memory, return it
    return jsonify(status_info), 200


if __name__ == '__main__':
    # Ensure PERSIST_DIR_BASE exists before ChromaDB tries to use it
    from server.services.embedding_service import PERSIST_DIR_BASE as chroma_persist_dir
    os.makedirs(chroma_persist_dir, exist_ok=True)
    
    app.run(host='127.0.0.1', port=5001, debug=True)

    
