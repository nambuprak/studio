
from flask import Flask, jsonify, request
from flask_cors import CORS
from pydantic import BaseModel, ValidationError, validator
from typing import List, Dict, Optional, Any
import uuid
import json
import threading
import os

# Azure OpenAI specific imports
from openai import AzureOpenAI
import httpx
import certifi

# Relative imports for services within the same package
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

class ChatWithTutorInput(BaseModel):
    tutor_id: str
    user_query: str
    # conversation_history: Optional[List[Dict[str,str]]] = None # For future enhancement

class ChatWithTutorOutput(BaseModel):
    ai_response: str


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
    if progress_detail: 
        status_dict["progress_detail"] = progress_detail
        current_msg_lower = status_dict.get("message", "").lower()
        if not current_msg_lower or "processing" in current_msg_lower or "embedding" in current_msg_lower or "starting" in current_msg_lower or "cloning" in current_msg_lower:
            status_dict["message"] = progress_detail


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
                status_message="Processing completed. Embedding skipped.",
                discovered_files_count=None, 
                processing_error=None
            )
            if tutor_id in TUTOR_PROCESSING_STATUS:
                TUTOR_PROCESSING_STATUS[tutor_id]["status"] = "COMPLETED"
                TUTOR_PROCESSING_STATUS[tutor_id]["message"] = "Processing completed. Embedding skipped."
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
    conn = None
    try:
        print(f"Attempting to delete ChromaDB collection for tutor_id: {tutor_id}")
        delete_chroma_collection_for_tutor(tutor_id)
        print(f"Successfully requested deletion of ChromaDB collection for tutor_id: {tutor_id} (or it didn't exist).")

        from .services.database_service import get_db_connection 
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tutors WHERE id = ?", (tutor_id,))
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "Tutor not found in database or already deleted"}), 404

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
                initial_status_message="Configuration saved." 
            )
            final_status_message = "Processing completed. Embedding skipped."
            update_tutor_processing_details(
                tutor_id=tutor_id,
                status_message=final_status_message,
                discovered_files_count=None, 
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
        conn = None
        try:
            from .services.database_service import get_db_connection 
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
                if db_processing_error or "failed" in (db_status_message or "").lower():
                    current_status_from_db = "FAILED"
                elif (db_status_message or "").lower().startswith("processing completed."):
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
        context = query_chroma_for_tutor(
            tutor_id=data.tutor_id,
            query_text=data.query_text,
            n_results=data.n_results
        )
        if context is not None: 
            return jsonify({"context": context}), 200
        else: 
            return jsonify({"context": "", "message": "No relevant context found or error in query."}), 200
    except Exception as e:
        print(f"Error during ChromaDB query for tutor {data.tutor_id}: {e}")
        return jsonify({"error": f"Failed to query ChromaDB: {str(e)}"}), 500

@app.route('/api/chat-with-tutor', methods=['POST'])
def chat_with_tutor_route():
    try:
        data = ChatWithTutorInput(**request.json)
    except ValidationError as e:
        return jsonify({"error": "Invalid input for chat", "details": e.errors()}), 400
    except Exception as e:
        return jsonify({"error": f"Error parsing chat request JSON: {str(e)}"}), 400

    try:
        # 1. Get context from ChromaDB
        print(f"Chat: Getting context for tutor {data.tutor_id} with query '{data.user_query[:50]}...'")
        context = query_chroma_for_tutor(
            tutor_id=data.tutor_id,
            query_text=data.user_query,
            n_results=5 # Or make this configurable
        )
        if context is None: # query_chroma_for_tutor returns "" on error/no results
            context = "" 
            print(f"Chat: No context found for tutor {data.tutor_id}, query '{data.user_query[:50]}...'")
        else:
            print(f"Chat: Retrieved context for tutor {data.tutor_id} (length: {len(context)})")


        # 2. Call Azure OpenAI
        azure_api_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        azure_api_key = os.getenv("AZURE_OPENAI_API_KEY")
        azure_deployment_name = os.getenv("DEPLOYMENT_NAME", "gpt-4") # Default to gpt-4 if not set

        if not all([azure_api_endpoint, azure_api_key, azure_deployment_name]):
            missing_vars = [
                var for var, val in {
                    "AZURE_OPENAI_ENDPOINT": azure_api_endpoint,
                    "AZURE_OPENAI_API_KEY": azure_api_key,
                    "DEPLOYMENT_NAME": azure_deployment_name
                }.items() if not val
            ]
            error_msg_env = f"Azure OpenAI environment variables missing: {', '.join(missing_vars)}"
            print(f"Chat Error: {error_msg_env}")
            return jsonify({"error": error_msg_env}), 500
        
        try:
            cacert_path = certifi.where()
            azure_client = AzureOpenAI(
                azure_endpoint=azure_api_endpoint,
                api_key=azure_api_key,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"), # Use a default or env var
                http_client=httpx.Client(verify=cacert_path)
            )
        except Exception as e_client_init:
            print(f"Chat Error: Failed to initialize AzureOpenAI client: {e_client_init}")
            return jsonify({"error": f"Azure OpenAI client initialization failed: {str(e_client_init)}"}), 500

        system_prompt_content = "You are an AI assistant for Self Tutor. Your goal is to answer the user's questions based *primarily* on the context provided from the repository's documentation and codebase. If the context is insufficient or irrelevant, state that you cannot answer based on the provided information. Do not make assumptions beyond the context."
        
        messages_for_openai = [
            {"role": "system", "content": system_prompt_content},
            {"role": "user", "content": f"Based on the following context, please answer my question.\n\nContext:\n---\n{context}\n---\n\nQuestion: {data.user_query}"}
        ]
        
        # Add conversation history if provided - for future enhancement
        # if data.conversation_history:
        #   history_messages = [{"role": item["role"], "content": item["content"]} for item in data.conversation_history]
        #   messages_for_openai = history_messages[:-1] + messages_for_openai # Insert system and user query+context after history

        print(f"Chat: Sending request to Azure OpenAI for tutor {data.tutor_id} with prompt based on query '{data.user_query[:50]}...'")

        try:
            completion = azure_client.chat.completions.create(
                model=azure_deployment_name,
                messages=messages_for_openai,
                max_tokens=1000, # Increased max_tokens
                temperature=0.5, # Slightly lower temperature for more factual answers
                top_p=0.95,
                frequency_penalty=0,
                presence_penalty=0,
                stop=None,
                stream=False
            )
            ai_response_content = completion.choices[0].message.content
            print(f"Chat: Received response from Azure OpenAI for tutor {data.tutor_id}")
            return jsonify(ChatWithTutorOutput(ai_response=ai_response_content).model_dump()), 200
        except Exception as e_openai:
            print(f"Chat Error: Azure OpenAI API call failed: {e_openai}")
            # Check for specific OpenAI error types if needed for more granular feedback
            return jsonify({"error": f"Azure OpenAI API call failed: {str(e_openai)}"}), 500

    except Exception as e:
        print(f"Chat Error: Unexpected error during chat processing for tutor {data.tutor_id}: {e}")
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001, debug=True)
