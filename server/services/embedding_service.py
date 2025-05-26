
import os
import uuid
import time
import requests # For get_embedding_for_text_custom_api
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional

import shutil # For rmtree
import chromadb
from chromadb.api.models.Collection import Collection as ChromaCollection
# from langchain_community.document_loaders import TextLoader # Assuming this is used elsewhere or planned -> Not currently used.
from langchain.text_splitter import CharacterTextSplitter

# For Azure OpenAI Embeddings
from openai import AzureOpenAI
import httpx
import certifi

# Environment variables for the custom embedding API (renamed function)
CUSTOM_EMBEDDING_API_URL_ENV_VAR = "CUSTOM_EMBEDDING_API_URL"
CUSTOM_EMBEDDING_API_TOKEN_ENV_VAR = "CUSTOM_EMBEDDING_API_TOKEN"
# This EMBEDDING_MODEL_NAME is for the custom API payload
CUSTOM_EMBEDDING_API_MODEL_NAME_ENV_VAR = "CUSTOM_EMBEDDING_API_MODEL_NAME"


# Environment variables for Azure OpenAI Embeddings
AZURE_OPENAI_ENDPOINT_ENV_VAR = "AZURE_OPENAI_ENDPOINT"
AZURE_OPENAI_API_KEY_ENV_VAR = "AZURE_OPENAI_API_KEY"
AZURE_OPENAI_API_VERSION_ENV_VAR = "AZURE_OPENAI_API_VERSION"
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME_ENV_VAR = "AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME" # e.g., your deployment of text-embedding-ada-002

# Get custom embedding API URL and Token from environment variables for the old function
CUSTOM_EMBEDDING_API_URL = os.getenv(CUSTOM_EMBEDDING_API_URL_ENV_VAR, "https://aienablement-api.mycompany.com/embeddings") # Fallback for POC
CUSTOM_EMBEDDING_API_TOKEN_FROM_ENV = os.getenv(CUSTOM_EMBEDDING_API_TOKEN_ENV_VAR)
CUSTOM_EMBEDDING_API_MODEL_NAME = os.getenv(CUSTOM_EMBEDDING_API_MODEL_NAME_ENV_VAR, "text-embedding-ada-002")


# Use a placeholder if the token is not set in the environment
CUSTOM_EMBEDDING_API_TOKEN = CUSTOM_EMBEDDING_API_TOKEN_FROM_ENV if CUSTOM_EMBEDDING_API_TOKEN_FROM_ENV else "Bearer placeholder_token_custom_api"
if CUSTOM_EMBEDDING_API_TOKEN == "Bearer placeholder_token_custom_api":
    print(f"Warning: {CUSTOM_EMBEDDING_API_TOKEN_ENV_VAR} environment variable is not set. Using placeholder token for get_embedding_for_text_custom_api.")


# Base directory for ChromaDB persistence.
# Corrected to point to the project root's `server/chroma_db_store`
PERSIST_DIR_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chroma_db_store")


# Embedding API call settings (can be reused for Azure)
MAX_RETRIES_EMBEDDING = 3 # Increased from 1
RETRY_BACKOFF_FACTOR_EMBEDDING = 2 # Seconds

# Ensure the ChromaDB persistence directory exists
os.makedirs(PERSIST_DIR_BASE, exist_ok=True)
print(f"ChromaDB persistence directory set to: {PERSIST_DIR_BASE}")


def _update_status_safely(status_dict: Optional[Dict[str, Any]], message: Optional[str] = None, status: Optional[str] = None, error: Optional[str] = None, progress_detail: Optional[str] = None):
    if status_dict is None:
        return

    if error:
        status_dict["error"] = error
        status_dict["message"] = f"Error: {error}" # Main message becomes the error
        status_dict["status"] = "FAILED" # CRITICAL: Always set status to FAILED if error is present
        if progress_detail: # e.g. "Error during embedding chunk X from Y"
            status_dict["progress_detail"] = progress_detail
        print(f"Status Update (Error): {status_dict['message']} - Detail: {progress_detail if progress_detail else 'N/A'}")
        return # Error takes precedence, further message/status updates for this call are ignored.

    # If no error, proceed with normal updates
    if message: # Can be a progress message or final success message
        status_dict["message"] = message
    
    if status: # Can be a specific processing step, or "COMPLETED"
        status_dict["status"] = status
    
    if progress_detail: 
        status_dict["progress_detail"] = progress_detail
        # Only update main message with progress_detail if it's not a final status already
        # and the current message seems like a generic "processing..." type message.
        current_msg_lower = status_dict.get("message", "").lower()
        is_final_status_msg = "completed" in current_msg_lower or \
                              "failed" in current_msg_lower or \
                              "error" in current_msg_lower 
        
        if not is_final_status_msg: 
            if not current_msg_lower or \
               any(kw in current_msg_lower for kw in ["processing", "embedding","starting","cloning", "initializing", "discovered", "split", "embedding chunk"]):
                 status_dict["message"] = progress_detail
    
    # Log non-error updates if a message or status was set
    if message or status or progress_detail:
        log_msg = f"Status: {status_dict.get('status', 'N/A')} - Msg: {status_dict.get('message', 'N/A')} - Detail: {status_dict.get('progress_detail', 'N/A')}"
        print(f"Status Update: {log_msg}")


def get_embedding_for_text_custom_api(text: str, status_dict: Optional[dict] = None) -> Optional[List[float]]:
    """
    Gets embedding for a single text string using the custom external API.
    Updates status_dict with errors if any.
    """
    url = CUSTOM_EMBEDDING_API_URL
    headers = {
        "accept": "application/json",
        "azure-deployment-version": os.getenv("EMBEDDING_API_VERSION", "2024-02-01"),
        "Authorization": CUSTOM_EMBEDDING_API_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {"model": CUSTOM_EMBEDDING_API_MODEL_NAME, "input": text}

    retry_count = 0
    while retry_count < MAX_RETRIES_EMBEDDING: 
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            embedding_data = response.json()

            if "data" in embedding_data and len(embedding_data["data"]) > 0 and "embedding" in embedding_data["data"][0]:
                return embedding_data["data"][0]["embedding"]
            else:
                err_msg = f"Invalid custom embedding API response format for text: '{text[:50]}...'"
                if retry_count + 1 >= MAX_RETRIES_EMBEDDING: 
                     _update_status_safely(status_dict, error=err_msg)
                else: 
                    _update_status_safely(status_dict, progress_detail=err_msg) # Log as progress for retries
        except requests.exceptions.RequestException as e:
            error_msg = f"Custom Embedding API request failed: {e}. Attempt {retry_count + 1}/{MAX_RETRIES_EMBEDDING}."
            if retry_count + 1 >= MAX_RETRIES_EMBEDDING: 
                _update_status_safely(status_dict, error=error_msg)
            else:
                _update_status_safely(status_dict, progress_detail=error_msg)
        except ValueError as ve: 
             error_msg_ve = f"Error parsing custom embedding API response: {ve} for text: '{text[:50]}...'"
             _update_status_safely(status_dict, error=error_msg_ve)
             return None 

        retry_count += 1
        if retry_count < MAX_RETRIES_EMBEDDING:
            time.sleep(RETRY_BACKOFF_FACTOR_EMBEDDING ** retry_count)
        else: 
            final_error_msg = f"Failed custom embedding API after {MAX_RETRIES_EMBEDDING} attempts for text: '{text[:50]}...'"
            if status_dict and not status_dict.get("error"): 
                _update_status_safely(status_dict, error=final_error_msg)
            return None
    return None 


def get_embedding_for_text(text: str, status_dict: Optional[dict] = None) -> Optional[List[float]]:
    """
    Gets embedding for a single text string using Azure OpenAI.
    Updates status_dict with errors if any.
    """
    azure_endpoint = os.getenv(AZURE_OPENAI_ENDPOINT_ENV_VAR)
    api_key = os.getenv(AZURE_OPENAI_API_KEY_ENV_VAR)
    api_version = os.getenv(AZURE_OPENAI_API_VERSION_ENV_VAR, "2024-02-01") 
    embedding_deployment_name = os.getenv(AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME_ENV_VAR)

    missing_vars = []
    if not azure_endpoint: missing_vars.append(AZURE_OPENAI_ENDPOINT_ENV_VAR)
    if not api_key: missing_vars.append(AZURE_OPENAI_API_KEY_ENV_VAR)
    if not embedding_deployment_name: missing_vars.append(AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME_ENV_VAR)

    if missing_vars:
        err_msg_env = f"Azure OpenAI embedding configuration error: Missing environment variable(s): {', '.join(missing_vars)}."
        _update_status_safely(status_dict, error=err_msg_env, message="Azure Configuration Error")
        return None

    try:
        cacert_path = certifi.where()
        azure_client = AzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=api_key,
            api_version=api_version,
            http_client=httpx.Client(verify=cacert_path)
        )
    except Exception as e_client_init:
        err_msg_client = f"Failed to initialize AzureOpenAI client for embeddings: {e_client_init}"
        _update_status_safely(status_dict, error=err_msg_client, message="Azure Client Init Error")
        return None

    retry_count = 0
    processed_text = text.replace("\n", " ").replace("\r", " ").strip() 
    if not processed_text: 
        _update_status_safely(status_dict, progress_detail=f"Skipped embedding for empty text.")
        return None


    while retry_count < MAX_RETRIES_EMBEDDING:
        try:
            response = azure_client.embeddings.create(
                model=embedding_deployment_name,
                input=processed_text
            )
            if response.data and len(response.data) > 0:
                return response.data[0].embedding
            else: 
                err_msg_format = f"Invalid Azure OpenAI embedding response format for text: '{processed_text[:50]}...'"
                if retry_count + 1 >= MAX_RETRIES_EMBEDDING:
                     _update_status_safely(status_dict, error=err_msg_format)
                else:
                     _update_status_safely(status_dict, progress_detail=err_msg_format)
        except Exception as e: 
            error_detail = str(e)
            error_msg_api_call = f"Azure OpenAI Embedding API call failed: {error_detail}. Attempt {retry_count + 1}/{MAX_RETRIES_EMBEDDING} for text: '{processed_text[:50]}...'."
            if retry_count + 1 >= MAX_RETRIES_EMBEDDING:
                _update_status_safely(status_dict, error=error_msg_api_call)
            else:
                _update_status_safely(status_dict, progress_detail=error_msg_api_call)
        
        retry_count += 1
        if retry_count < MAX_RETRIES_EMBEDDING:
            time.sleep(RETRY_BACKOFF_FACTOR_EMBEDDING ** retry_count)
        else: 
            final_error_msg = f"Failed Azure OpenAI embedding after {MAX_RETRIES_EMBEDDING} attempts for text: '{processed_text[:50]}...'"
            if status_dict and not status_dict.get("error"): # Only set error if not already set by a more specific previous error
                 _update_status_safely(status_dict, error=final_error_msg)
            return None # Explicitly return None if all retries fail
            
    return None # Should be unreachable if MAX_RETRIES_EMBEDDING > 0


def initialize_chroma_collection(tutor_id: str, status_dict: Optional[dict] = None) -> Optional[ChromaCollection]:
    """Initializes or gets a ChromaDB collection for a given tutor_id."""
    collection_name = f"tutor_{tutor_id.replace('-', '_')}"
    try:
        _update_status_safely(status_dict, progress_detail=f"Initializing ChromaDB client at {PERSIST_DIR_BASE}...")
        chroma_client = chromadb.PersistentClient(path=PERSIST_DIR_BASE)

        _update_status_safely(status_dict, progress_detail=f"Getting or creating ChromaDB collection: {collection_name}...")
        collection = chroma_client.get_or_create_collection(name=collection_name)
        _update_status_safely(status_dict, progress_detail=f"ChromaDB collection '{collection_name}' ready.")
        return collection
    except Exception as e:
        error_msg_chroma = f"Error initializing ChromaDB for tutor {tutor_id}: {e}"
        _update_status_safely(status_dict, error=error_msg_chroma, message="ChromaDB initialization failed.")
        return None

def delete_chroma_collection_for_tutor(tutor_id: str):
    """Deletes the ChromaDB collection associated with a given tutor_id, including its physical directory."""
    collection_name = f"tutor_{tutor_id.replace('-', '_')}"
    print(f"Attempting to delete ChromaDB collection: '{collection_name}' for tutor_id: {tutor_id}")
    print(f"ChromaDB persistence directory is: {PERSIST_DIR_BASE}")

    try:
        chroma_client = chromadb.PersistentClient(path=PERSIST_DIR_BASE)
        
        collection_uuid_str: Optional[str] = None
        physical_collection_path: Optional[str] = None
        collection_existed_before_api_delete = False

        try:
            target_collection_obj = chroma_client.get_collection(name=collection_name)
            collection_uuid_str = str(target_collection_obj.id) 
            # Construct the path to the physical directory using the UUID
            physical_collection_path = os.path.join(PERSIST_DIR_BASE, collection_uuid_str)
            print(f"Found collection '{collection_name}' with UUID: {collection_uuid_str}. Expected physical path: {physical_collection_path}")
            
            if os.path.exists(physical_collection_path) and os.path.isdir(physical_collection_path):
                collection_existed_before_api_delete = True
                print(f"Physical directory '{physical_collection_path}' exists before API deletion attempt.")
            else:
                print(f"Physical directory '{physical_collection_path}' does NOT exist before API deletion attempt.")
        
        except Exception as e_get_coll:
            print(f"Info: Could not get collection '{collection_name}' from ChromaDB (it might not exist, or an error occurred trying to get its UUID): {e_get_coll}")
            # Try deleting by name if getting the object failed
            try:
                chroma_client.delete_collection(name=collection_name)
                print(f"API call to delete_collection('{collection_name}') by name attempted as UUID was not retrieved.")
                # If this succeeds, the physical folder (if named after UUID) might still be there or removed by API.
                # We don't have physical_collection_path in this case, so direct physical deletion is harder.
            except Exception as e_del_by_name_fallback:
                print(f"API call to delete_collection('{collection_name}') by name also failed: {e_del_by_name_fallback}")
            return # Exit if we couldn't get the collection object initially.

        api_delete_call_made = False
        try:
            chroma_client.delete_collection(name=collection_name) # API call
            print(f"API call to delete_collection('{collection_name}') was successful.")
            api_delete_call_made = True
        except Exception as e_api_delete:
            print(f"Error during API call to delete_collection('{collection_name}'): {e_api_delete}. Will still attempt physical cleanup if path is known.")

        # Attempt physical deletion of the UUID-named folder
        if physical_collection_path:
            if os.path.exists(physical_collection_path) and os.path.isdir(physical_collection_path):
                print(f"Physical directory '{physical_collection_path}' (UUID-based) still exists. Attempting shutil.rmtree...")
                try:
                    shutil.rmtree(physical_collection_path)
                    print(f"Successfully deleted physical directory: {physical_collection_path}")
                except Exception as e_rmtree_uuid:
                    print(f"Error deleting physical directory '{physical_collection_path}' with shutil.rmtree: {e_rmtree_uuid}. Manual cleanup might be needed.")
            else:
                if collection_existed_before_api_delete and api_delete_call_made:
                    print(f"Physical directory '{physical_collection_path}' no longer exists. Likely removed by the API delete_collection call.")
                elif collection_existed_before_api_delete and not api_delete_call_made:
                     print(f"Physical directory '{physical_collection_path}' no longer exists, but API delete call failed or was not made successfully (problematic state).")
                else: # Did not exist before, and still does not exist.
                    print(f"Physical directory '{physical_collection_path}' was not found initially and is still not found.")
        else:
            # This case should ideally not be reached if get_collection succeeded.
            print(f"Physical collection path for '{collection_name}' was not determined (UUID lookup failed). Skipping UUID-based physical deletion.")

    except Exception as e:
        print(f"General error during ChromaDB collection deletion process for '{collection_name}' (tutor_id {tutor_id}): {e}. Manual cleanup might be needed.")


def add_chunk_to_chromadb(collection: ChromaCollection, text_chunk: str, embedding: List[float], metadata: Dict[str, Any], status_dict: Optional[dict] = None):
    """Adds a single text chunk and its embedding to the specified ChromaDB collection."""
    chunk_id = str(uuid.uuid4())
    try:
        collection.add(
            documents=[text_chunk],
            embeddings=[embedding],
            ids=[chunk_id],
            metadatas=[metadata]
        )
    except Exception as e:
        error_msg_add_chunk = f"Error adding chunk (Source: {metadata.get('source')}, File: {metadata.get('file_name')}) to ChromaDB: {e}"
        _update_status_safely(status_dict, error=error_msg_add_chunk)


def _process_text_document_for_embedding(
    doc_text: str,
    source_name: str, # e.g. "file:///path/to/file.py", "repository_overview", "additional_info_0_auth"
    collection: ChromaCollection,
    text_splitter: CharacterTextSplitter,
    status_dict: dict,
    doc_type_override: Optional[str] = None # For repo_overview, additional_info
):
    """Splits a text document, gets embeddings for chunks, and adds them to ChromaDB."""
    _update_status_safely(status_dict, progress_detail=f"Processing document: {source_name} for embedding...")
    if not doc_text.strip():
        _update_status_safely(status_dict, progress_detail=f"Skipping empty document: {source_name}.")
        return

    try:
        raw_chunks = text_splitter.split_text(doc_text)
    except Exception as e:
        _update_status_safely(status_dict, error=f"Error splitting document {source_name}: {e}", progress_detail=f"Failed to split {source_name}")
        return

    num_chunks = len(raw_chunks)
    _update_status_safely(status_dict, progress_detail=f"Split '{source_name}' into {num_chunks} chunk(s).")

    for i, chunk_text in enumerate(raw_chunks):
        if not chunk_text.strip():
            _update_status_safely(status_dict, progress_detail=f"Skipping empty chunk {i+1}/{num_chunks} from '{source_name}'.")
            continue
        
        progress_update = f"Embedding chunk {i+1}/{num_chunks} from '{source_name}'..."
        _update_status_safely(status_dict, progress_detail=progress_update) 


        embedding = get_embedding_for_text(chunk_text, status_dict)
        if embedding:
            metadata: Dict[str, Any] = {"source": source_name, "chunk_index": i}
            if doc_type_override:
                metadata["doc_type"] = doc_type_override
                metadata["file_name"] = source_name # For overview/additional, filename is the source itself
            elif source_name.startswith("file://"):
                 metadata["doc_type"] = "file_content"
                 actual_file_path = source_name.replace("file://", "")
                 metadata["file_name"] = os.path.basename(actual_file_path)
            else: # Should not happen if doc_type_override is used correctly
                 metadata["doc_type"] = "generic_text"
                 metadata["file_name"] = source_name


            add_chunk_to_chromadb(collection, chunk_text, embedding, metadata, status_dict)
        elif not status_dict.get("error"): 
            _update_status_safely(status_dict, message=f"Failed to get embedding for chunk {i+1}/{num_chunks} from '{source_name}'. Skipping chunk.")
        
        if status_dict.get("error"): 
            print(f"Stopping embedding for document '{source_name}' due to error: {status_dict.get('error')}")
            return


def _process_single_file_for_embedding(
    file_path: str,
    collection: ChromaCollection,
    text_splitter: CharacterTextSplitter,
    status_dict: dict
):
    """Reads a single file, then processes its content for embedding."""
    base_file_name = os.path.basename(file_path)
    _update_status_safely(status_dict, progress_detail=f"Embedding file: {base_file_name}...")
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        if not content.strip():
            _update_status_safely(status_dict, progress_detail=f"Skipping empty file: {file_path}.")
            return
        # Pass file path with "file://" prefix as source_name
        _process_text_document_for_embedding(content, f"file://{file_path}", collection, text_splitter, status_dict)
    except Exception as e:
        _update_status_safely(status_dict, error=f"Error reading or processing file {file_path}: {e}", progress_detail=f"Failed for file: {base_file_name}")


def embed_documents_for_tutor(
    tutor_id: str,
    file_paths: List[str],
    repo_overview: str,
    additional_info_list: List[Dict[str, str]],
    status_dict: dict
):
    """
    Main function to handle embedding for a tutor.
    Embeds discovered files, repository overview, and additional info.
    """
    _update_status_safely(status_dict, message="Initializing embedding process...")

    collection = initialize_chroma_collection(tutor_id, status_dict)
    if not collection:
        if not status_dict.get("error"): # Error already set by initialize_chroma_collection
            _update_status_safely(status_dict, error="Fatal: Could not initialize ChromaDB. Aborting embedding.")
        return

    text_splitter = CharacterTextSplitter(chunk_size=1700, chunk_overlap=200, separator="\n")

    # Process repo_overview first
    if repo_overview and repo_overview.strip():
        _process_text_document_for_embedding(
            repo_overview, 
            "repository_overview", 
            collection, 
            text_splitter, 
            status_dict,
            doc_type_override="repo_overview"
        )
        if status_dict.get("error"): 
            print(f"Stopping embedding for tutor {tutor_id} due to error during repo overview embedding: {status_dict.get('error')}")
            return 
    else:
        _update_status_safely(status_dict, progress_detail="No repository overview provided, skipping its embedding.")

    # Process additional_info_list
    if additional_info_list:
        for i, info_item in enumerate(additional_info_list):
            title = info_item.get('title', '')
            description = info_item.get('description', '')
            if title or description:
                full_text = f"Title: {title}\nDescription: {description}"
                source_name_info = f"additional_info_{i}_{title.replace(' ', '_').lower()[:20]}"
                _process_text_document_for_embedding(
                    full_text, 
                    source_name_info, 
                    collection, 
                    text_splitter, 
                    status_dict,
                    doc_type_override="additional_info"
                )
                if status_dict.get("error"):
                    print(f"Stopping embedding for tutor {tutor_id} due to error during additional info item '{title}' embedding: {status_dict.get('error')}")
                    return
            else:
                 _update_status_safely(status_dict, progress_detail=f"Skipping empty additional info item at index {i}.")
    else:
        _update_status_safely(status_dict, progress_detail="No additional info items provided, skipping their embedding.")

    # Process files
    if file_paths:
        _update_status_safely(status_dict, message=f"Preparing to embed content from {len(file_paths)} discovered files...")
        # Using a ThreadPoolExecutor for concurrent file processing (reading and chunking) 
        # and embedding API calls.
        # Adjust max_workers based on your API rate limits and server capabilities.
        max_workers = min(5, os.cpu_count() * 2 if os.cpu_count() else 4) 

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for file_path in file_paths:
                if status_dict.get("error"): 
                    print(f"Stopping file embedding submission for tutor {tutor_id} due to pre-existing error: {status_dict.get('error')}")
                    break 
                futures.append(executor.submit(
                    _process_single_file_for_embedding,
                    file_path,
                    collection,
                    text_splitter,
                    status_dict
                ))
            
            processed_files_count = 0
            total_files_to_process = len(futures) 
            for i, future in enumerate(futures):
                try:
                    future.result() # Wait for thread to complete or raise exception from within the thread
                    if not status_dict.get("error"): # Only count as processed if no specific error occurred for THIS file or globally
                        processed_files_count +=1
                    
                    # Progress detail update based on files *attempted*
                    _update_status_safely(status_dict, progress_detail=f"Attempted processing for file {i+1}/{total_files_to_process}. Successfully processed so far: {processed_files_count}.")

                    if status_dict.get("error"): # Check error from within the thread's execution or a previous one
                        current_error = status_dict.get('error')
                        print(f"Error encountered during embedding file {os.path.basename(file_paths[i]) if i < len(file_paths) else 'unknown file'}: {current_error}. Halting further file processing for tutor {tutor_id}.")
                        # Attempt to cancel remaining futures
                        for f_cancel in futures[i+1:]:
                            if not f_cancel.done(): f_cancel.cancel()
                        # executor.shutdown(wait=False, cancel_futures=True) # Python 3.9+ for cancel_futures
                        # For older Python or simpler shutdown:
                        # Let already submitted tasks run to completion or error out,
                        # but don't submit new ones (already handled by outer loop check)
                        # The return here will stop processing for this tutor.
                        return 
                except Exception as e_future: 
                    # This catches errors from the future.result() if the thread itself had an unhandled exception
                    file_being_processed = os.path.basename(file_paths[i]) if i < len(file_paths) else 'unknown file'
                    print(f"A critical error occurred processing one of the files ({file_being_processed}): {e_future}")
                    _update_status_safely(status_dict, error=f"Critical error processing file: {file_being_processed} - {str(e_future)}")
                    return # Stop processing for this tutor
        
        if not status_dict.get("error"): 
            _update_status_safely(status_dict, message=f"Finished embedding content from {processed_files_count}/{total_files_to_process} files successfully.")
    else:
        _update_status_safely(status_dict, progress_detail="No files discovered or provided for embedding.")

    if not status_dict.get("error"): 
        _update_status_safely(status_dict, message="Processing completed. Repository embedded.", status="COMPLETED") # Final success status
    else: 
        # Error message and status should already be set by _update_status_safely
        # This just ensures we don't overwrite a FAILED status with something less specific.
        if status_dict.get("status") != "FAILED":
             _update_status_safely(status_dict, message=f"Document embedding process encountered errors for tutor {tutor_id}. Error: {status_dict.get('error')}", status="FAILED")


def query_chroma_for_tutor(tutor_id: str, query_text: str, n_results: int = 5, status_dict: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Queries ChromaDB for a given tutor_id and query_text using Azure OpenAI for query embedding."""
    log_prefix = f"QueryChroma (TutorID: {tutor_id}): "
    # For query, status_dict is usually None as it's a direct call, not part of background processing.
    # If status_dict is provided, it's for logging within a larger flow.
    current_status_dict_for_query = status_dict if status_dict else {}

    _update_status_safely(current_status_dict_for_query, message=f"Querying ChromaDB with: '{query_text[:50]}...'")
    if not status_dict: print(f"{log_prefix}Querying with: '{query_text[:50]}...'")


    collection = initialize_chroma_collection(tutor_id, current_status_dict_for_query)
    if not collection:
        error_msg = "Failed to initialize ChromaDB collection for querying."
        _update_status_safely(current_status_dict_for_query, error=error_msg)
        if not status_dict: print(f"{log_prefix}{error_msg}")
        return None # Return None for error

    query_embedding = get_embedding_for_text(query_text, current_status_dict_for_query)
    if not query_embedding:
        error_msg_emb = f"Failed to generate embedding for query: '{query_text[:50]}...'"
        if not current_status_dict_for_query.get("error"): # Don't overwrite specific error from get_embedding_for_text
            _update_status_safely(current_status_dict_for_query, error=error_msg_emb)
        if not status_dict: print(f"{log_prefix}{error_msg_emb}")
        return None # Return None for error

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas"] # Include metadatas
        )

        documents = results.get("documents")
        metadatas_list = results.get("metadatas")

        if documents and isinstance(documents, list) and len(documents) > 0:
            # The result structure for documents and metadatas is List[List[...]]
            # We need to flatten it if it's nested (it usually is one level deep for single query_embedding)
            flat_documents = [doc for sublist in documents for doc in sublist if doc is not None]
            flat_metadatas = [meta for sublist in metadatas_list for meta in sublist if meta is not None] if metadatas_list else []


            combined_context_parts = []
            for i, doc_content in enumerate(flat_documents):
                doc_meta = flat_metadatas[i] if i < len(flat_metadatas) else {}
                source_info = doc_meta.get("source", "Unknown source")
                file_name_info = doc_meta.get("file_name", "")
                chunk_idx_info = doc_meta.get("chunk_index", "")
                
                context_header = f"Context from: {source_info}"
                if file_name_info and file_name_info != source_info : # Avoid "Context from: file.txt (file.txt)"
                    context_header += f" (File: {file_name_info})"
                if chunk_idx_info != "":
                    context_header += f" [Chunk: {chunk_idx_info}]"

                combined_context_parts.append(f"{context_header}\n---\n{doc_content}\n---")
            
            return "\n\n".join(combined_context_parts)
        else:
            no_results_msg = "No relevant documents found in ChromaDB for the query."
            _update_status_safely(current_status_dict_for_query, message=no_results_msg)
            if not status_dict: print(f"{log_prefix}{no_results_msg}")
            return "" # Return empty string for no results, not None
    except Exception as e:
        error_msg_query = f"Error querying ChromaDB: {e}"
        _update_status_safely(current_status_dict_for_query, error=error_msg_query)
        if not status_dict: print(f"{log_prefix}{error_msg_query}")
        return None # Return None for error


    