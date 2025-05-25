
from flask import Flask, jsonify, request
from flask_cors import CORS
from pydantic import BaseModel, ValidationError, validator
from typing import List, Dict, Optional, Any
import uuid
import json
import threading
import os

# Use relative imports for services within the same package
from .services.database_service import init_db, save_tutor_config, get_all_tutors, get_tutor_by_id, update_tutor_processing_details
from .services.processing_service import process_repository_content
from .services.utils import extract_project_name_from_url, extract_project_name_from_path
from .services.embedding_service import query_chroma_for_tutor, delete_chroma_collection_for_tutor

app = Flask(__name__)
CORS(app)

init_db() # Ensures DB and table are created on startup

# In-memory store for processing status (POC only)
TUTOR_PROCESSING_STATUS: Dict[str, Dict[str, Any]] = {}


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

    @validator('project_name', pre=True, always=True)
    def project_name_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Project name cannot be empty')
        return v

    @validator('source_location', pre=True, always=True)
    def source_location_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Source location (folder path or URL) cannot be empty')
        return v

    @validator('input_type', pre=True, always=True)
    def input_type_must_be_valid(cls, v: str) -> str:
        if v not in ['folder', 'url']:
            raise ValueError("Input type must be 'folder' or 'url'")
        return v

class QueryChromaInput(BaseModel):
    tutor_id: str
    query_text: str
    n_results: int = 5


def _perform_long_repository_processing(tutor_id: str, data: CreateTutorInput, app_context: Any):
    with app_context:
        project_name_from_data = data.project_name
        print(f"Background task started for tutor_id: {tutor_id}, project: {project_name_from_data}")

        current_status: Dict[str, Any] = {
            "status": "PROCESSING_DB_SAVE",
            "message": f"Saving initial configuration for {project_name_from_data}...",
            "project_name": project_name_from_data,
            "tutor_id": tutor_id,
            "discovered_files_count": 0,
            "error": None
        }
        TUTOR_PROCESSING_STATUS[tutor_id] = current_status

        try:
            parsed_additional_info_list = [item.model_dump() for item in data.additional_info_list]
            save_tutor_config(
                tutor_id=tutor_id,
                project_name=project_name_from_data,
                input_type=data.input_type,
                source_location=data.source_location,
                repo_overview=data.repo_overview,
                tap_bap=data.tap_bap,
                file_types_str=data.file_types,
                exclude_folders_str=data.exclude_folders,
                additional_info_list_json=json.dumps(parsed_additional_info_list),
                embed_repo_flag=data.embed_repo,
                initial_status_message="Configuration saved. Awaiting processing."
            )
            _update_status_safely(current_status, message="Configuration saved. Starting repository processing if embedding is enabled...")
            print(f"Configuration saved for tutor_id: {tutor_id}")

            discovered_files_count = 0
            final_status_message = ""

            if data.embed_repo:
                print(f"Starting repository content processing (including embedding) for tutor_id: {tutor_id}")
                _update_status_safely(current_status, status="PROCESSING_EMBEDDING", message=f"Processing and embedding repository content for {project_name_from_data}...")

                discovered_files_count, processing_message_from_service = process_repository_content(
                    input_type=data.input_type,
                    source_location=data.source_location,
                    file_types_str=data.file_types,
                    exclude_folders_str=data.exclude_folders,
                    tutor_id=tutor_id,
                    embed_repo_flag=data.embed_repo,
                    repo_overview=data.repo_overview,
                    additional_info_list=parsed_additional_info_list,
                    status_dict=current_status # Pass the status dict here
                )
                current_status["discovered_files_count"] = discovered_files_count
                final_status_message = "Processing completed. Repository embedded."
                _update_status_safely(current_status, message=final_status_message)
                print(f"Repository processing completed for {tutor_id}. Files: {discovered_files_count}. Msg: {final_status_message}")
            else:
                final_status_message = "Processing completed. Embedding skipped."
                _update_status_safely(current_status, message=final_status_message)
                print(f"Embedding skipped for tutor_id: {tutor_id}")

            update_tutor_processing_details(
                tutor_id=tutor_id,
                status_message=final_status_message,
                discovered_files_count=discovered_files_count if data.embed_repo else None,
                processing_error=current_status.get("error")
            )
            _update_status_safely(current_status, status="COMPLETED", message=final_status_message)

        except Exception as e:
            print(f"Error during background processing for tutor_id {tutor_id}: {e}")
            error_message_for_status = f"Processing failed for {project_name_from_data}: {str(e)}"
            _update_status_safely(current_status, status="FAILED", message=error_message_for_status, error=str(e))

            try:
                update_tutor_processing_details(
                    tutor_id=tutor_id,
                    status_message="Processing failed.",
                    discovered_files_count=current_status.get("discovered_files_count", 0),
                    processing_error=str(e)
                )
            except Exception as db_error:
                print(f"Critical: Failed to update DB with error status for {tutor_id}: {db_error}")

        print(f"Background task finished for {tutor_id}. Final Status: {TUTOR_PROCESSING_STATUS.get(tutor_id, {}).get('status')}")

def _update_status_safely(status_dict: Optional[Dict[str, Any]], message: Optional[str] = None, status: Optional[str] = None, error: Optional[str] = None, progress_detail: Optional[str] = None):
    if status_dict is None:
        return
    if message:
        status_dict["message"] = message
    if status:
        status_dict["status"] = status
    if error:
        status_dict["error"] = error
    if progress_detail: # New logic for progress_detail
        status_dict["progress_detail"] = progress_detail
        # If a specific message isn't already error/completion, or if it's a generic processing message, update with detail
        current_msg_lower = status_dict.get("message", "").lower()
        if not current_msg_lower or "processing" in current_msg_lower or "embedding" in current_msg_lower or "starting" in current_msg_lower or "cloning" in current_msg_lower:
            status_dict["message"] = progress_detail


@app.route('/api/repos', methods=['GET'])
def get_repos_from_db_route():
    try:
        repos = get_all_tutors() # This now returns project_name, id, status_message, discovered_files_count
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
        data = CreateTutorInput(**request.json)
    except ValidationError as e:
        return jsonify({"error": "Invalid input", "details": e.errors()}), 400
    except Exception as e: # Catch non-Pydantic JSON parsing errors
        return jsonify({"error": f"Error parsing request: {str(e)}"}), 400

    try:
        # Save updated configuration
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
            initial_status_message="Configuration updated. Awaiting re-processing if embedding enabled."
        )

        if data.embed_repo:
            # If embedding is enabled (or re-enabled), start background processing
            TUTOR_PROCESSING_STATUS[tutor_id] = {
                "status": "PENDING_REPROCESS", # Indicate it's a reprocess
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
            }), 202 # Accepted for background processing
        else:
            # If embedding is not enabled, update status to completed (skipped)
            update_tutor_processing_details(
                tutor_id=tutor_id,
                status_message="Processing completed. Embedding skipped.",
                discovered_files_count=None, # No files processed if embedding skipped
                processing_error=None
            )
            # Also update in-memory status if it exists
            if tutor_id in TUTOR_PROCESSING_STATUS:
                TUTOR_PROCESSING_STATUS[tutor_id]["status"] = "COMPLETED"
                TUTOR_PROCESSING_STATUS[tutor_id]["message"] = "Processing completed. Embedding skipped."
                if "discovered_files_count" in TUTOR_PROCESSING_STATUS[tutor_id]: # Should not happen if embedding skipped
                    TUTOR_PROCESSING_STATUS[tutor_id]["discovered_files_count"] = None


            return jsonify({
                "message": "Self Tutor configuration updated successfully. Embedding not enabled.",
                "tutor_id": tutor_id,
                "project_name": data.project_name
            }), 200

    except Exception as e:
        print(f"Error updating tutor {tutor_id}: {e}")
        return jsonify({"error": f"Database or processing error during update: {str(e)}"}), 500


@app.route('/api/tutor-details/<string:tutor_id>', methods=['DELETE'])
def delete_tutor_route(tutor_id: str):
    conn = None
    try:
        # Attempt to delete ChromaDB collection first
        print(f"Attempting to delete ChromaDB collection for tutor_id: {tutor_id}")
        delete_chroma_collection_for_tutor(tutor_id)
        print(f"Successfully requested deletion of ChromaDB collection for tutor_id: {tutor_id} (or it didn't exist).")

        # Then delete from SQLite
        from .services.database_service import get_db_connection # Local import to avoid circular if any
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tutors WHERE id = ?", (tutor_id,))
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "Tutor not found in database or already deleted"}), 404

        # Remove from in-memory status if present
        if tutor_id in TUTOR_PROCESSING_STATUS:
            del TUTOR_PROCESSING_STATUS[tutor_id]

        return jsonify({"message": "Tutor and associated data deleted successfully"}), 200
    except Exception as e:
        if conn: conn.rollback()
        print(f"Error deleting tutor {tutor_id}: {e}")
        return jsonify({"error": f"Failed to delete tutor or its associated data: {str(e)}"}), 500
    finally:
        if conn: conn.close()


@app.route('/api/analyze-repo', methods=['POST'])
def analyze_repo_route():
    try:
        data = CreateTutorInput(**request.json)
    except ValidationError as e:
        return jsonify({"error": "Invalid input", "details": e.errors()}), 400
    except Exception as e: # Catch non-Pydantic JSON parsing errors
        return jsonify({"error": f"Error parsing request JSON: {str(e)}"}), 400

    tutor_id = str(uuid.uuid4())
    # Project name is now directly from the form
    project_name_to_use = data.project_name

    if data.embed_repo:
        # Initialize status for background processing
        TUTOR_PROCESSING_STATUS[tutor_id] = {
            "status": "PENDING",
            "message": f"Processing initiated for {project_name_to_use}...",
            "project_name": project_name_to_use,
            "tutor_id": tutor_id,
            "error": None
        }
        # Start background thread
        thread = threading.Thread(target=_perform_long_repository_processing, args=(tutor_id, data, app.app_context()))
        thread.start()
        print(f"Background processing thread started for tutor_id: {tutor_id}")
        # Return 202 Accepted, client will poll for status
        return jsonify({
            "message": "Self Tutor processing initiated. Check status for updates.",
            "tutor_id": tutor_id,
            "project_name": project_name_to_use
        }), 202
    else: # Synchronous path if embed_repo is false
        try:
            parsed_additional_info_list = [item.model_dump() for item in data.additional_info_list]
            save_tutor_config(
                tutor_id=tutor_id,
                project_name=project_name_to_use,
                input_type=data.input_type,
                source_location=data.source_location,
                repo_overview=data.repo_overview,
                tap_bap=data.tap_bap,
                file_types_str=data.file_types,
                exclude_folders_str=data.exclude_folders,
                additional_info_list_json=json.dumps(parsed_additional_info_list),
                embed_repo_flag=data.embed_repo,
                initial_status_message="Configuration saved." # Will be overwritten by update_tutor_processing_details
            )
            # Explicitly set the final status for non-embedding cases
            final_status_message = "Processing completed. Embedding skipped."
            update_tutor_processing_details(
                tutor_id=tutor_id,
                status_message=final_status_message,
                discovered_files_count=None, # No files discovered if embedding skipped
                processing_error=None
            )
            return jsonify({
                "message": final_status_message,
                "tutor_id": tutor_id,
                "project_name": project_name_to_use,
                "discovered_files_count": "N/A (Embedding skipped)"
            }), 200
        except Exception as e:
            print(f"Database error during synchronous save_tutor_config for {tutor_id}: {e}")
            return jsonify({"error": f"Database error: {str(e)}"}), 500

@app.route('/api/tutor-status/<string:tutor_id>', methods=['GET'])
def get_tutor_status_route(tutor_id: str):
    status_info = TUTOR_PROCESSING_STATUS.get(tutor_id)

    if not status_info:
        # If not in memory (e.g., server restart), try to get from DB
        conn = None
        try:
            from .services.database_service import get_db_connection # Local import
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT project_name, status_message, discovered_files_count, processing_error FROM tutors WHERE id = ?", (tutor_id,))
            row = cursor.fetchone()
            if row:
                db_project_name: str = row["project_name"]
                db_status_message: Optional[str] = row["status_message"]
                db_discovered_files: Optional[int] = row["discovered_files_count"]
                db_processing_error: Optional[str] = row["processing_error"]

                # Determine status based on DB message
                current_status_from_db = "UNKNOWN_COMPLETED" # Default if status message is vague
                if db_processing_error or "failed" in (db_status_message or "").lower():
                    current_status_from_db = "FAILED"
                elif (db_status_message or "").lower().startswith("processing completed."): # Covers both embedded and skipped
                     current_status_from_db = "COMPLETED"
                # Add other conditions if needed to infer status from db_status_message

                # Re-populate in-memory status for subsequent polls if it wasn't there
                # This helps if the processing finished but server restarted before client polled final status
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
                 # Tutor ID not found in DB and not in memory
                 return jsonify({"error": "Tutor status not found for ID.", "tutor_id": tutor_id}), 404
        except Exception as e:
            print(f"Error fetching status from DB for tutor {tutor_id}: {e}")
            return jsonify({"error": "Error fetching tutor status from DB."}), 500
        finally:
            if conn: conn.close()

    return jsonify(status_info), 200

@app.route('/api/query-chroma', methods=['POST'])
def query_chroma_route():
    try:
        data = QueryChromaInput(**request.json)
    except ValidationError as e:
        return jsonify({"error": "Invalid input", "details": e.errors()}), 400
    except Exception as e: # Catch non-Pydantic JSON parsing errors
        return jsonify({"error": f"Error parsing request JSON: {str(e)}"}), 400

    try:
        context = query_chroma_for_tutor(
            tutor_id=data.tutor_id,
            query_text=data.query_text,
            n_results=data.n_results
            # status_dict could be passed if query_chroma_for_tutor is enhanced to update it
        )
        if context is not None: # Check if context is None, not just falsy (empty string is valid)
            return jsonify({"context": context}), 200
        else: # Should ideally not happen if query_chroma_for_tutor returns "" on error/no results
            return jsonify({"context": "", "message": "No relevant context found or error in query."}), 200
    except Exception as e:
        print(f"Error during ChromaDB query for tutor {data.tutor_id}: {e}")
        return jsonify({"error": f"Failed to query ChromaDB: {str(e)}"}), 500


if __name__ == '__main__':
    # Ensure ChromaDB persistence directory exists
    # from .services.embedding_service import PERSIST_DIR_BASE as chroma_persist_dir
    # os.makedirs(chroma_persist_dir, exist_ok=True) # PERSIST_DIR_BASE is already handled in embedding_service.py
    app.run(host='127.0.0.1', port=5001, debug=True)

    