
from flask import Flask, jsonify, request
from flask_cors import CORS
from pydantic import BaseModel, ValidationError, validator
from typing import List, Dict, Optional, Any 
import uuid
import json
import threading 
import os 

from services.database_service import init_db, save_tutor_config, get_all_tutors, get_tutor_by_id, update_tutor_processing_details
from services.processing_service import process_repository_content
from services.utils import extract_project_name_from_url, extract_project_name_from_path
from services.embedding_service import query_chroma_for_tutor # New import

app = Flask(__name__)
CORS(app)

init_db()

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

    @validator('project_name')
    def project_name_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Project name cannot be empty')
        return v

    @validator('source_location')
    def source_location_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Source location (folder path or URL) cannot be empty')
        return v

    @validator('input_type')
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
                initial_status_message="Configuration saved. Awaiting embedding if requested." 
            )
            _update_status_safely(current_status, message="Configuration saved. Starting repository processing if embedding is enabled...")
            print(f"Configuration saved for tutor_id: {tutor_id}")

            discovered_files_count = 0
            processing_message = "Self Tutor configuration saved." 
            
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
                    status_dict=current_status 
                )
                current_status["discovered_files_count"] = discovered_files_count
                current_status["message"] = processing_message_from_service 
                processing_message = processing_message_from_service 
                print(f"Repository processing completed for {tutor_id}. Files: {discovered_files_count}. Msg: {processing_message}")
            else:
                processing_message = "Self Tutor configuration saved. Embedding skipped by user."
                _update_status_safely(current_status, message=processing_message)
                print(f"Embedding skipped for tutor_id: {tutor_id}")

            update_tutor_processing_details(
                tutor_id=tutor_id,
                status_message=processing_message, 
                discovered_files_count=discovered_files_count if data.embed_repo else None,
                processing_error=current_status.get("error") 
            )
            _update_status_safely(current_status, status="COMPLETED", message=processing_message) 
            
        except Exception as e:
            print(f"Error during background processing for tutor_id {tutor_id}: {e}")
            error_message_for_status = f"Background processing failed for {project_name_from_data}: {str(e)}"
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
    if progress_detail:
        status_dict["progress_detail"] = progress_detail


@app.route('/api/repos', methods=['GET'])
def get_repos_from_db_route():
    try:
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
    except Exception as e: 
        return jsonify({"error": f"Error parsing request: {str(e)}"}), 400

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
            initial_status_message="Configuration updated. Awaiting re-processing if embedding enabled." 
        )
        
        if data.embed_repo:
            TUTOR_PROCESSING_STATUS[tutor_id] = {
                "status": "PENDING_REPROCESS", 
                "message": "Re-processing initiated due to update...", 
                "project_name": data.project_name,
                "tutor_id": tutor_id,
                "error": None
            }
            # Use current_app.app_context() if available, or app.app_context()
            thread = threading.Thread(target=_perform_long_repository_processing, args=(tutor_id, data, app.app_context()))
            thread.start()
            return jsonify({
                "message": "Self Tutor update accepted. Re-processing initiated as embedding is enabled.",
                "tutor_id": tutor_id,
                "project_name": data.project_name
            }), 202 
        else:
            update_tutor_processing_details(
                tutor_id=tutor_id,
                status_message="Configuration updated. Embedding not requested or re-processing skipped.",
                discovered_files_count=None, 
                processing_error=None
            )
            if tutor_id in TUTOR_PROCESSING_STATUS:
                TUTOR_PROCESSING_STATUS[tutor_id]["status"] = "COMPLETED"
                TUTOR_PROCESSING_STATUS[tutor_id]["message"] = "Configuration updated. Embedding disabled."
                if "discovered_files_count" in TUTOR_PROCESSING_STATUS[tutor_id]:
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
    # TODO: Implement actual deletion from ChromaDB collection for the tutor
    # from services.embedding_service import delete_chroma_collection_for_tutor
    # delete_chroma_collection_for_tutor(tutor_id)
    conn = None
    try:
        from services.database_service import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tutors WHERE id = ?", (tutor_id,))
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "Tutor not found or already deleted"}), 404
        
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
    project_name_to_use = data.project_name
    
    if data.embed_repo:
        TUTOR_PROCESSING_STATUS[tutor_id] = {
            "status": "PENDING", 
            "message": f"Processing initiated for {project_name_to_use}...", 
            "project_name": project_name_to_use,
            "tutor_id": tutor_id,
            "error": None
        }
        thread = threading.Thread(target=_perform_long_repository_processing, args=(tutor_id, data, app.app_context()))
        thread.start()
        print(f"Background processing thread started for tutor_id: {tutor_id}")
        return jsonify({
            "message": "Self Tutor processing initiated. Check status for updates.",
            "tutor_id": tutor_id,
            "project_name": project_name_to_use
        }), 202
    else:
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
        conn = None
        try:
            from services.database_service import get_db_connection
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT project_name, status_message, discovered_files_count, processing_error FROM tutors WHERE id = ?", (tutor_id,))
            row = cursor.fetchone()
            if row:
                db_project_name: str = row["project_name"]
                db_status_message: Optional[str] = row["status_message"]
                db_discovered_files: Optional[int] = row["discovered_files_count"] 
                db_processing_error: Optional[str] = row["processing_error"] 
                
                current_status_from_db = "UNKNOWN_COMPLETED" 
                if "failed" in (db_status_message or "").lower() or db_processing_error:
                    current_status_from_db = "FAILED"
                elif ("saved" in (db_status_message or "").lower() or "complete" in (db_status_message or "").lower()) and db_discovered_files is not None :
                     current_status_from_db = "COMPLETED" 
                elif "skipped" in (db_status_message or "").lower() and db_discovered_files is None :
                     current_status_from_db = "COMPLETED" 

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

@app.route('/api/query-chroma', methods=['POST'])
def query_chroma_route():
    try:
        data = QueryChromaInput(**request.json)
    except ValidationError as e:
        return jsonify({"error": "Invalid input", "details": e.errors()}), 400
    except Exception as e:
        return jsonify({"error": f"Error parsing request JSON: {str(e)}"}), 400

    try:
        # For now, status_dict is not passed to query_chroma_for_tutor, but can be added if needed for logging.
        context = query_chroma_for_tutor(
            tutor_id=data.tutor_id,
            query_text=data.query_text,
            n_results=data.n_results
        )
        if context:
            return jsonify({"context": context}), 200
        else:
            return jsonify({"context": "", "message": "No relevant context found or error in query."}), 200 # Return empty context
    except Exception as e:
        print(f"Error during ChromaDB query for tutor {data.tutor_id}: {e}")
        return jsonify({"error": f"Failed to query ChromaDB: {str(e)}"}), 500


if __name__ == '__main__':
    from services.embedding_service import PERSIST_DIR_BASE as chroma_persist_dir
    os.makedirs(chroma_persist_dir, exist_ok=True)
    app.run(host='127.0.0.1', port=5001, debug=True)
