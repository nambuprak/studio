
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


def _update_status_safely(status_dict: Optional[Dict[str, Any]], message: Optional[str] = None, error: Optional[str] = None, progress_detail: Optional[str] = None):
    if status_dict is None:
        return

    if error:  # Prioritize error message
        status_dict["error"] = error
        # Ensure the main message reflects this error directly
        status_dict["message"] = f"Error: {error}" 
        # Optionally, still set progress_detail if provided, but it won't overwrite the main error message
        if progress_detail:
            status_dict["progress_detail"] = progress_detail
        return  # Stop further message processing if an error occurred

    if message:
        status_dict["message"] = message
    
    if progress_detail: 
        status_dict["progress_detail"] = progress_detail
        current_msg_lower = status_dict.get("message", "").lower()
        # Check if message is already a final status or error
        is_final_status_msg = "completed" in current_msg_lower or \
                              "failed" in current_msg_lower or \
                              "error" in current_msg_lower
        
        if not is_final_status_msg:
            # Update message with progress_detail only if current message is generic
            if not current_msg_lower or \
               any(kw in current_msg_lower for kw in ["processing", "embedding","starting","cloning", "initializing", "discovered", "split", "embedding chunk"]):
                 status_dict["message"] = progress_detail


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

    # Using MAX_RETRIES_EMBEDDING for consistency, though original script had 1 for this.
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
                if retry_count + 1 >= MAX_RETRIES_EMBEDDING: # Last attempt
                     if status_dict: _update_status_safely(status_dict, error=err_msg)
                     else: print(err_msg)
                else: # Not last attempt, treat as progress_detail or just print
                    if status_dict: _update_status_safely(status_dict, progress_detail=err_msg)
                    else: print(err_msg)
                # No return here, loop will continue if retries left
        except requests.exceptions.RequestException as e:
            error_msg = f"Custom Embedding API request failed: {e}. Attempt {retry_count + 1}/{MAX_RETRIES_EMBEDDING}."
            if retry_count + 1 >= MAX_RETRIES_EMBEDDING: # Last attempt
                if status_dict: _update_status_safely(status_dict, error=error_msg)
                else: print(error_msg)
            else:
                if status_dict: _update_status_safely(status_dict, progress_detail=error_msg)
                else: print(error_msg)
        except ValueError as ve: # JSONDecodeError is a subclass of ValueError
             error_msg_ve = f"Error parsing custom embedding API response: {ve} for text: '{text[:50]}...'"
             # This is a non-retryable error for this request
             if status_dict: _update_status_safely(status_dict, error=error_msg_ve)
             else: print(error_msg_ve)
             return None # Exit on parse error

        retry_count += 1
        if retry_count < MAX_RETRIES_EMBEDDING:
            time.sleep(RETRY_BACKOFF_FACTOR_EMBEDDING ** retry_count)
        else: # All retries failed for request/format issues
            final_error_msg = f"Failed custom embedding API after {MAX_RETRIES_EMBEDDING} attempts for text: '{text[:50]}...'"
            # This path might not be reached if specific errors are handled above, but as a fallback.
            if status_dict and not status_dict.get("error"): # Only update if no specific error already set
                _update_status_safely(status_dict, error=final_error_msg)
            elif not status_dict:
                 print(final_error_msg)
            return None
    return None # Should be unreachable if loop logic is correct


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
        if status_dict: _update_status_safely(status_dict, error=err_msg_env)
        else: print(err_msg_env)
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
        if status_dict: _update_status_safely(status_dict, error=err_msg_client)
        else: print(err_msg_client)
        return None

    retry_count = 0
    processed_text = text.replace("\n", " ").replace("\r", " ").strip() # OpenAI recommends replacing newlines
    if not processed_text: # Skip empty or whitespace-only strings
        if status_dict: _update_status_safely(status_dict, progress_detail=f"Skipped embedding for empty text.")
        return None


    while retry_count < MAX_RETRIES_EMBEDDING:
        try:
            response = azure_client.embeddings.create(
                model=embedding_deployment_name,
                input=processed_text
            )
            if response.data and len(response.data) > 0:
                return response.data[0].embedding
            else: # Should not happen if API call itself was successful and returned data
                err_msg_format = f"Invalid Azure OpenAI embedding response format for text: '{processed_text[:50]}...'"
                if retry_count + 1 >= MAX_RETRIES_EMBEDDING:
                     if status_dict: _update_status_safely(status_dict, error=err_msg_format)
                     else: print(err_msg_format)
                else:
                     if status_dict: _update_status_safely(status_dict, progress_detail=err_msg_format)
                     else: print(err_msg_format)
        except Exception as e: 
            error_detail = str(e)
            # Check for common API errors if possible (e.g. from openai.APIError)
            # For now, a generic message:
            error_msg_api_call = f"Azure OpenAI Embedding API call failed: {error_detail}. Attempt {retry_count + 1}/{MAX_RETRIES_EMBEDDING} for text: '{processed_text[:50]}...'."
            if retry_count + 1 >= MAX_RETRIES_EMBEDDING:
                if status_dict: _update_status_safely(status_dict, error=error_msg_api_call)
                else: print(error_msg_api_call)
            else:
                if status_dict: _update_status_safely(status_dict, progress_detail=error_msg_api_call)
                else: print(error_msg_api_call)
        
        retry_count += 1
        if retry_count < MAX_RETRIES_EMBEDDING:
            time.sleep(RETRY_BACKOFF_FACTOR_EMBEDDING ** retry_count)
        else: # All retries failed
            # The error message should have been set in the last attempt's except block.
            # This is a fallback if no specific error was caught and status_dict.error isn't set.
            final_error_msg = f"Failed Azure OpenAI embedding after {MAX_RETRIES_EMBEDDING} attempts for text: '{processed_text[:50]}...'"
            if status_dict and not status_dict.get("error"):
                 _update_status_safely(status_dict, error=final_error_msg)
            elif not status_dict:
                 print(final_error_msg)
            return None
            
    return None # Should be unreachable


def initialize_chroma_collection(tutor_id: str, status_dict: Optional[dict] = None) -> Optional[ChromaCollection]:
    """Initializes or gets a ChromaDB collection for a given tutor_id."""
    collection_name = f"tutor_{tutor_id.replace('-', '_')}"
    try:
        if status_dict: _update_status_safely(status_dict, progress_detail=f"Initializing ChromaDB client at {PERSIST_DIR_BASE}...")
        chroma_client = chromadb.PersistentClient(path=PERSIST_DIR_BASE)

        if status_dict: _update_status_safely(status_dict, progress_detail=f"Getting or creating ChromaDB collection: {collection_name}...")
        collection = chroma_client.get_or_create_collection(name=collection_name)
        if status_dict: _update_status_safely(status_dict, progress_detail=f"ChromaDB collection '{collection_name}' ready.")
        return collection
    except Exception as e:
        error_msg_chroma = f"Error initializing ChromaDB for tutor {tutor_id}: {e}"
        if status_dict: _update_status_safely(status_dict, error=error_msg_chroma, message="ChromaDB initialization failed.")
        else: print(error_msg_chroma)
        return None

def delete_chroma_collection_for_tutor(tutor_id: str):
    """Deletes the ChromaDB collection associated with a given tutor_id, including its physical directory."""
    collection_name = f"tutor_{tutor_id.replace('-', '_')}"
    print(f"Attempting to delete ChromaDB collection: '{collection_name}' for tutor_id: {tutor_id}")
    print(f"ChromaDB persistence directory is: {PERSIST_DIR_BASE}")

    try:
        chroma_client = chromadb.PersistentClient(path=PERSIST_DIR_BASE)
        
        collection_uuid_str = None
        physical_collection_path = None
        collection_existed_before_api_delete = False

        try:
            target_collection_obj = chroma_client.get_collection(name=collection_name)
            collection_uuid_str = str(target_collection_obj.id) 
            physical_collection_path = os.path.join(PERSIST_DIR_BASE, collection_uuid_str)
            print(f"Found collection '{collection_name}' with UUID: {collection_uuid_str}. Expected physical path: {physical_collection_path}")
            
            if os.path.exists(physical_collection_path) and os.path.isdir(physical_collection_path):
                collection_existed_before_api_delete = True
                print(f"Physical directory '{physical_collection_path}' exists before API deletion attempt.")
            else:
                print(f"Physical directory '{physical_collection_path}' does NOT exist before API deletion attempt.")
        
        except Exception as e_get_coll:
            print(f"Could not get collection '{collection_name}' from ChromaDB (it might not exist or an error occurred): {e_get_coll}")
            # If we can't get the collection, try to delete by name and then look for a folder matching the name (less ideal)
            try:
                chroma_client.delete_collection(name=collection_name)
                print(f"API call to delete_collection('{collection_name}') attempted (collection object not found initially).")
            except Exception as e_del_by_name:
                print(f"API call to delete_collection('{collection_name}') also failed: {e_del_by_name}")
            
            # Fallback: Try to delete folder if it's named directly after collection_name (not UUID based)
            # This is less likely for default ChromaDB setup but provides an extra cleanup attempt.
            named_collection_path = os.path.join(PERSIST_DIR_BASE, collection_name)
            if os.path.exists(named_collection_path) and os.path.isdir(named_collection_path):
                print(f"Attempting to delete potential named folder '{named_collection_path}' as UUID path was not determined.")
                try:
                    shutil.rmtree(named_collection_path)
                    print(f"Successfully deleted named folder: {named_collection_path}")
                except Exception as e_rm_named:
                    print(f"Error deleting named folder '{named_collection_path}': {e_rm_named}")
            else:
                print(f"Named folder '{named_collection_path}' not found.")
            return # Exit if we can't get the collection, as we can't reliably know its UUID-based folder.

        api_delete_call_made = False
        try:
            chroma_client.delete_collection(name=collection_name)
            print(f"API call to delete_collection('{collection_name}') was successful.")
            api_delete_call_made = True
        except Exception as e_api_delete:
            print(f"Error during API call to delete_collection('{collection_name}'): {e_api_delete}. Will still attempt physical cleanup if path is known.")

        if physical_collection_path:
            if os.path.exists(physical_collection_path) and os.path.isdir(physical_collection_path):
                print(f"Physical directory '{physical_collection_path}' still exists after API delete attempt. Attempting shutil.rmtree...")
                try:
                    shutil.rmtree(physical_collection_path)
                    print(f"Successfully deleted physical directory: {physical_collection_path}")
                except Exception as e_rmtree_uuid:
                    print(f"Error deleting physical directory '{physical_collection_path}' with shutil.rmtree: {e_rmtree_uuid}. Manual cleanup might be needed.")
            else:
                if collection_existed_before_api_delete and api_delete_call_made:
                    print(f"Physical directory '{physical_collection_path}' no longer exists. Likely removed by the API delete_collection call.")
                elif collection_existed_before_api_delete and not api_delete_call_made:
                     print(f"Physical directory '{physical_collection_path}' no longer exists, but API delete call failed or was not made successfully.")
                else: 
                    print(f"Physical directory '{physical_collection_path}' was not found initially and is still not found.")
        else:
            print(f"Physical collection path for '{collection_name}' was not determined. Skipping physical deletion of UUID-based folder.")

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
        error_msg_add_chunk = f"Error adding chunk (Source: {metadata.get('source')}) to ChromaDB: {e}"
        if status_dict: _update_status_safely(status_dict, error=error_msg_add_chunk)
        else: print(error_msg_add_chunk)


def _process_text_document_for_embedding(
    doc_text: str,
    source_name: str,
    collection: ChromaCollection,
    text_splitter: CharacterTextSplitter,
    status_dict: dict
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
            metadata = {"source": source_name, "chunk_index": i}
            if "file://" in source_name:
                 metadata["doc_type"] = "file_content"
            elif "repository_overview" == source_name:
                 metadata["doc_type"] = "repo_overview"
            elif source_name.startswith("additional_info_"):
                 metadata["doc_type"] = "additional_info"
            else:
                 metadata["doc_type"] = "generic_text"
            add_chunk_to_chromadb(collection, chunk_text, embedding, metadata, status_dict)
        # If embedding is None, check if an error was already set in status_dict by get_embedding_for_text
        elif not status_dict.get("error"): 
            # If no specific error from get_embedding_for_text, then log a generic chunk skip message.
            _update_status_safely(status_dict, message=f"Failed to get embedding for chunk {i+1}/{num_chunks} from '{source_name}'. Skipping chunk.")
        # If status_dict.get("error") is already set, we assume get_embedding_for_text has provided a more specific error message.


def _process_single_file_for_embedding(
    file_path: str,
    collection: ChromaCollection,
    text_splitter: CharacterTextSplitter,
    status_dict: dict
):
    """Reads a single file, then processes its content for embedding."""
    _update_status_safely(status_dict, progress_detail=f"Embedding file: {os.path.basename(file_path)}...")
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        if not content.strip():
            _update_status_safely(status_dict, progress_detail=f"Skipping empty file: {file_path}.")
            return
        _process_text_document_for_embedding(content, f"file://{file_path}", collection, text_splitter, status_dict)
    except Exception as e:
        _update_status_safely(status_dict, error=f"Error reading or processing file {file_path}: {e}", progress_detail=f"Failed for file: {os.path.basename(file_path)}")


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
        # initialize_chroma_collection already updates status_dict with an error.
        # Setting a more generic message here if it failed.
        if not status_dict.get("error"):
            _update_status_safely(status_dict, message=f"Fatal: Could not initialize ChromaDB for tutor {tutor_id}. Aborting embedding.", error="ChromaDB init failed")
        return

    text_splitter = CharacterTextSplitter(chunk_size=1700, chunk_overlap=200, separator="\n")

    if repo_overview and repo_overview.strip():
        _process_text_document_for_embedding(repo_overview, "repository_overview", collection, text_splitter, status_dict)
        if status_dict.get("error"): return # Stop if error during overview embedding
    else:
        _update_status_safely(status_dict, progress_detail="No repository overview provided, skipping its embedding.")

    if additional_info_list:
        for i, info_item in enumerate(additional_info_list):
            title = info_item.get('title', '')
            description = info_item.get('description', '')
            if title or description:
                full_text = f"Title: {title}\nDescription: {description}"
                source_name_info = f"additional_info_{i}_{title.replace(' ', '_').lower()[:20]}"
                _process_text_document_for_embedding(full_text, source_name_info, collection, text_splitter, status_dict)
                if status_dict.get("error"): return # Stop if error during additional info embedding
            else:
                 _update_status_safely(status_dict, progress_detail=f"Skipping empty additional info item at index {i}.")
    else:
        _update_status_safely(status_dict, progress_detail="No additional info items provided, skipping their embedding.")

    if file_paths:
        _update_status_safely(status_dict, message=f"Preparing to embed content from {len(file_paths)} discovered files...")
        max_workers = min(5, os.cpu_count() * 2 if os.cpu_count() else 4) 

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for file_path in file_paths:
                futures.append(executor.submit(
                    _process_single_file_for_embedding,
                    file_path,
                    collection,
                    text_splitter,
                    status_dict
                ))
                # Check for immediate errors from status_dict if a previous operation failed critically
                if status_dict.get("error"):
                    print(f"Stopping file embedding early due to error: {status_dict.get('error')}")
                    # Cancel remaining futures if possible (best effort)
                    for fut in futures:
                        if not fut.done():
                            fut.cancel()
                    executor.shutdown(wait=False, cancel_futures=True) # Python 3.9+
                    return 


            processed_files_count = 0
            total_files = len(futures) # Use len(futures) as some might be submitted before an error stop
            for i, future in enumerate(futures):
                if future.cancelled():
                    _update_status_safely(status_dict, progress_detail=f"Skipped embedding for file due to earlier cancellation.")
                    continue
                try:
                    future.result() # Wait for thread to complete or raise exception
                    if status_dict.get("error"): # Check error from within the thread's execution
                        print(f"Error during embedding file {os.path.basename(file_paths[i])}: {status_dict.get('error')}. Stopping further processing.")
                        return # Stop processing more files
                    processed_files_count +=1
                    _update_status_safely(status_dict, progress_detail=f"Completed embedding for {processed_files_count}/{total_files} files.")
                except Exception as e: 
                    # This catches exceptions raised by _process_single_file_for_embedding if not handled internally by it
                    print(f"An error occurred processing one of the files ({os.path.basename(file_paths[i])}): {e}")
                    _update_status_safely(status_dict, error=f"Error processing file: {os.path.basename(file_paths[i])} - {str(e)}")
                    return # Stop processing more files
        
        if not status_dict.get("error"): # If no errors occurred during file processing
            _update_status_safely(status_dict, message=f"Finished embedding content from {processed_files_count}/{total_files} files.")
    else:
        _update_status_safely(status_dict, progress_detail="No files discovered or provided for embedding.")

    if not status_dict.get("error"):
        _update_status_safely(status_dict, message="Document embedding process fully completed for this tutor.")


def query_chroma_for_tutor(tutor_id: str, query_text: str, n_results: int = 5, status_dict: Optional[Dict[str, Any]] = None) -> str:
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
        return ""

    query_embedding = get_embedding_for_text(query_text, current_status_dict_for_query)
    if not query_embedding:
        error_msg_emb = f"Failed to generate embedding for query: '{query_text[:50]}...'"
        # current_status_dict_for_query might already have an error from get_embedding_for_text
        if not current_status_dict_for_query.get("error"):
            _update_status_safely(current_status_dict_for_query, error=error_msg_emb)
        if not status_dict: print(f"{log_prefix}{error_msg_emb}")
        return ""

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents"] 
        )

        documents = results.get("documents")
        if documents and isinstance(documents, list) and len(documents) > 0:
            # Chroma can return List[List[str]] for documents, flatten if needed
            valid_documents = []
            for doc_list in documents:
                if isinstance(doc_list, list):
                    valid_documents.extend([str(doc) for doc in doc_list if doc is not None])
                elif doc_list is not None: # Should not happen based on include=["documents"] type hint
                    valid_documents.append(str(doc_list))

            combined_content = "\n---\n".join(valid_documents) # Use a clear separator
            return combined_content
        else:
            no_results_msg = "No relevant documents found in ChromaDB for the query."
            _update_status_safely(current_status_dict_for_query, message=no_results_msg)
            if not status_dict: print(f"{log_prefix}{no_results_msg}")
            return ""
    except Exception as e:
        error_msg_query = f"Error querying ChromaDB: {e}"
        _update_status_safely(current_status_dict_for_query, error=error_msg_query)
        if not status_dict: print(f"{log_prefix}{error_msg_query}")
        return ""

    