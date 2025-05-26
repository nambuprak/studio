
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
CUSTOM_EMBEDDING_API_URL = os.getenv(CUSTOM_EMBEDDING_API_URL_ENV_VAR, "https://aienablement-api.mycompany.com/embeddings")
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
MAX_RETRIES_EMBEDDING = 1
RETRY_BACKOFF_FACTOR_EMBEDDING = 2 # Seconds

# Ensure the ChromaDB persistence directory exists
os.makedirs(PERSIST_DIR_BASE, exist_ok=True)
print(f"ChromaDB persistence directory set to: {PERSIST_DIR_BASE}")


def _update_status_safely(status_dict: Optional[Dict[str, Any]], message: Optional[str] = None, error: Optional[str] = None, progress_detail: Optional[str] = None):
    if status_dict is None:
        # print(f"Warning: status_dict is None. Message: {message}, Error: {error}, Progress: {progress_detail}")
        return

    current_tutor_id = status_dict.get('tutor_id', 'N/A')
    # log_prefix = f"Status Update (TutorID: {current_tutor_id}): " # Can be too verbose here

    if message:
        status_dict["message"] = message
    if error:
        status_dict["error"] = error
        error_message_to_set = f"Error: {error}"
        if "message" in status_dict and status_dict["message"] and "error" not in status_dict["message"].lower() and "failed" not in status_dict["message"].lower():
            status_dict["message"] = f"{status_dict['message']} - {error_message_to_set}"
        else:
            status_dict["message"] = error_message_to_set

    if progress_detail:
        status_dict["progress_detail"] = progress_detail
        # Update main message only if it's currently a generic processing/embedding message or empty
        current_msg_lower = status_dict.get("message", "").lower()
        if not current_msg_lower or \
           current_msg_lower.startswith(("processing", "embedding","starting","cloning", "initializing", "discovered", "split", "embedding chunk")):
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
                if status_dict: _update_status_safely(status_dict, error=err_msg, progress_detail=err_msg)
                else: print(err_msg)
                return None
        except requests.exceptions.RequestException as e:
            error_msg = f"Custom Embedding API request failed: {e}. Attempt {retry_count + 1}/{MAX_RETRIES_EMBEDDING}."
            if status_dict: _update_status_safely(status_dict, error=error_msg, progress_detail=error_msg)
            else: print(error_msg)
            retry_count += 1
            if retry_count < MAX_RETRIES_EMBEDDING:
                time.sleep(RETRY_BACKOFF_FACTOR_EMBEDDING ** retry_count)
            else:
                final_error_msg = f"Failed custom embedding API after {MAX_RETRIES_EMBEDDING} attempts for text: '{text[:50]}...'"
                if status_dict: _update_status_safely(status_dict, error=final_error_msg, progress_detail=final_error_msg)
                else: print(final_error_msg)
                return None
        except ValueError as ve: # JSONDecodeError is a subclass of ValueError
             error_msg_ve = f"Error parsing custom embedding API response: {ve} for text: '{text[:50]}...'"
             if status_dict: _update_status_safely(status_dict, error=error_msg_ve, progress_detail=error_msg_ve)
             else: print(error_msg_ve)
             return None
    return None


def get_embedding_for_text(text: str, status_dict: Optional[dict] = None) -> Optional[List[float]]:
    """
    Gets embedding for a single text string using Azure OpenAI.
    Updates status_dict with errors if any.
    """
    azure_endpoint = os.getenv(AZURE_OPENAI_ENDPOINT_ENV_VAR)
    api_key = os.getenv(AZURE_OPENAI_API_KEY_ENV_VAR)
    api_version = os.getenv(AZURE_OPENAI_API_VERSION_ENV_VAR, "2024-02-01") # Default or from env
    embedding_deployment_name = os.getenv(AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME_ENV_VAR)

    if not all([azure_endpoint, api_key, embedding_deployment_name]):
        missing_vars = [
            var_name for var_name, var_val in {
                AZURE_OPENAI_ENDPOINT_ENV_VAR: azure_endpoint,
                AZURE_OPENAI_API_KEY_ENV_VAR: api_key,
                AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME_ENV_VAR: embedding_deployment_name
            }.items() if not var_val
        ]
        err_msg_env = f"Azure OpenAI embedding environment variables missing: {', '.join(missing_vars)}"
        if status_dict: _update_status_safely(status_dict, error=err_msg_env, progress_detail=err_msg_env)
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
        if status_dict: _update_status_safely(status_dict, error=err_msg_client, progress_detail=err_msg_client)
        else: print(err_msg_client)
        return None

    retry_count = 0
    while retry_count < MAX_RETRIES_EMBEDDING:
        try:
            # Replace spaces and newlines in text input to prevent issues with some models
            processed_text = text.replace("\\n", " ").replace("\\r", " ").strip()
            if not processed_text: # handle empty string after processing
                # print(f"Skipping embedding for empty text input.")
                return None

            response = azure_client.embeddings.create(
                model=embedding_deployment_name,
                input=processed_text
            )
            if response.data and len(response.data) > 0:
                return response.data[0].embedding
            else:
                err_msg_format = f"Invalid Azure OpenAI embedding response format for text: '{processed_text[:50]}...'"
                if status_dict: _update_status_safely(status_dict, error=err_msg_format, progress_detail=err_msg_format)
                else: print(err_msg_format)
                return None
        except Exception as e: # Catch broader exceptions from the OpenAI client
            error_msg = f"Azure OpenAI Embedding API call failed: {e}. Attempt {retry_count + 1}/{MAX_RETRIES_EMBEDDING} for text: '{text[:50]}...'."
            if status_dict: _update_status_safely(status_dict, error=error_msg, progress_detail=error_msg)
            else: print(error_msg)
            retry_count += 1
            if retry_count < MAX_RETRIES_EMBEDDING:
                time.sleep(RETRY_BACKOFF_FACTOR_EMBEDDING ** retry_count)
            else:
                final_error_msg = f"Failed Azure OpenAI embedding after {MAX_RETRIES_EMBEDDING} attempts for text: '{text[:50]}...'"
                if status_dict: _update_status_safely(status_dict, error=final_error_msg, progress_detail=final_error_msg)
                else: print(final_error_msg)
                return None
    return None


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
    collection_uuid_str: Optional[str] = None
    chroma_client = None
    
    try:
        print(f"Attempting to delete ChromaDB collection: {collection_name} from {PERSIST_DIR_BASE}")
        chroma_client = chromadb.PersistentClient(path=PERSIST_DIR_BASE)
        
        # Get collection to find its UUID for physical deletion
        try:
            target_collection_obj = chroma_client.get_collection(name=collection_name)
            collection_uuid_str = str(target_collection_obj.id) # This is the UUID
            print(f"Found collection '{collection_name}' with UUID: {collection_uuid_str}")
        except Exception as e_get_coll: 
            # This exception block handles cases where the collection might not exist by name.
            # If we can't get it by name, it means it likely doesn't exist or an error occurred.
            # We shouldn't try to delete its physical folder if we don't know its UUID.
            print(f"Could not get collection '{collection_name}' to find its UUID (it might not exist or an error occurred): {e_get_coll}")
            # Check if a folder with the *collection_name* exists (less likely, but possible if something went wrong)
            collection_folder_by_name_path = os.path.join(PERSIST_DIR_BASE, collection_name)
            if os.path.exists(collection_folder_by_name_path) and os.path.isdir(collection_folder_by_name_path):
                try:
                    print(f"Attempting to delete folder by name: {collection_folder_by_name_path} as UUID was not retrievable.")
                    shutil.rmtree(collection_folder_by_name_path)
                    print(f"Successfully deleted physical directory by name for collection: {collection_folder_by_name_path}")
                except Exception as e_rmtree_by_name:
                    print(f"Error deleting physical directory by name '{collection_folder_by_name_path}': {e_rmtree_by_name}. Manual cleanup might be needed.")
            return # Exit if collection not found by name and no folder by name exists

        # Attempt API deletion (if collection was found by name)
        if target_collection_obj: # Ensure target_collection_obj is not None
            try:
                chroma_client.delete_collection(name=collection_name)
                print(f"Successfully requested API deletion of ChromaDB collection: {collection_name}")
            except Exception as e_api_delete:
                print(f"Error during API deletion of ChromaDB collection '{collection_name}': {e_api_delete}. Proceeding to attempt physical cleanup if UUID was found.")

        # Attempt physical directory deletion using UUID if it was found
        if collection_uuid_str:
            collection_data_path_by_uuid = os.path.join(PERSIST_DIR_BASE, collection_uuid_str)
            if os.path.exists(collection_data_path_by_uuid) and os.path.isdir(collection_data_path_by_uuid):
                try:
                    shutil.rmtree(collection_data_path_by_uuid)
                    print(f"Successfully deleted physical directory for collection UUID '{collection_uuid_str}' ('{collection_name}'): {collection_data_path_by_uuid}")
                except Exception as e_rmtree_uuid:
                    print(f"Error deleting physical directory by UUID '{collection_data_path_by_uuid}': {e_rmtree_uuid}. Manual cleanup might be needed.")
            else:
                print(f"Physical directory for collection UUID '{collection_uuid_str}' ('{collection_name}') not found at '{collection_data_path_by_uuid}', no physical deletion needed or already removed.")
        else:
             print(f"No collection UUID found for '{collection_name}', skipping targeted physical directory deletion by UUID.")

    except Exception as e:
        print(f"General error during ChromaDB collection deletion for '{collection_name}': {e}. Manual cleanup might be needed.")


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
        if status_dict: _update_status_safely(status_dict, error=error_msg_add_chunk, progress_detail=error_msg_add_chunk)
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
        # Only set as main message if it's a generic one
        current_message_lower = status_dict.get("message", "").lower()
        if not current_message_lower or any(kw in current_message_lower for kw in ["processing", "embedding", "starting", "cloning", "discovered", "split"]):
            _update_status_safely(status_dict, message=progress_update, progress_detail=progress_update)
        else:
            _update_status_safely(status_dict, progress_detail=progress_update)


        # Uses the new Azure OpenAI based embedding function
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
        else:
            # Error messages for failed embedding are handled by get_embedding_for_text
            _update_status_safely(status_dict, message=f"Failed to get embedding for chunk {i+1}/{num_chunks} from '{source_name}'. Skipping chunk.")


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
        _update_status_safely(status_dict, message=f"Fatal: Could not initialize ChromaDB for tutor {tutor_id}. Aborting embedding.", error="ChromaDB init failed")
        return

    # Langchain's CharacterTextSplitter is good for general text.
    # Consider other splitters (e.g., RecursiveCharacterTextSplitter, CodeSplitter) for code if needed.
    text_splitter = CharacterTextSplitter(chunk_size=1700, chunk_overlap=200, separator="\\n")

    if repo_overview and repo_overview.strip():
        _process_text_document_for_embedding(repo_overview, "repository_overview", collection, text_splitter, status_dict)
    else:
        _update_status_safely(status_dict, progress_detail="No repository overview provided, skipping its embedding.")

    if additional_info_list:
        for i, info_item in enumerate(additional_info_list):
            title = info_item.get('title', '')
            description = info_item.get('description', '')
            if title or description:
                # Combine title and description for a richer context chunk
                full_text = f"Title: {title}\\nDescription: {description}"
                source_name_info = f"additional_info_{i}_{title.replace(' ', '_').lower()[:20]}"
                _process_text_document_for_embedding(full_text, source_name_info, collection, text_splitter, status_dict)
            else:
                 _update_status_safely(status_dict, progress_detail=f"Skipping empty additional info item at index {i}.")
    else:
        _update_status_safely(status_dict, progress_detail="No additional info items provided, skipping their embedding.")

    if file_paths:
        _update_status_safely(status_dict, message=f"Preparing to embed content from {len(file_paths)} discovered files...")
        # Adjust max_workers based on API rate limits and server capacity
        # Using a modest number for now to avoid overwhelming a single API key if rate limited
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

            processed_files_count = 0
            total_files = len(file_paths)
            for i, future in enumerate(futures):
                try:
                    future.result() # Wait for each file's processing to complete
                    processed_files_count +=1
                    _update_status_safely(status_dict, progress_detail=f"Completed embedding for {processed_files_count}/{total_files} files.")
                except Exception as e: # Catch errors from individual file processing futures
                    # Error from future.result() should ideally already update status_dict via _update_status_safely within the task
                    # This is a fallback log.
                    print(f"An error occurred processing one of the files ({os.path.basename(file_paths[i])}): {e}")
                    _update_status_safely(status_dict, message=f"An error occurred processing file: {os.path.basename(file_paths[i])}")
        _update_status_safely(status_dict, message=f"Finished embedding content from {processed_files_count}/{total_files} files.")
    else:
        _update_status_safely(status_dict, progress_detail="No files discovered or provided for embedding.")

    _update_status_safely(status_dict, message="Document embedding process fully completed for this tutor.")


def query_chroma_for_tutor(tutor_id: str, query_text: str, n_results: int = 5, status_dict: Optional[Dict[str, Any]] = None) -> str:
    """Queries ChromaDB for a given tutor_id and query_text using Azure OpenAI for query embedding."""
    log_prefix = f"QueryChroma (TutorID: {tutor_id}): "
    if status_dict: _update_status_safely(status_dict, message=f"Querying ChromaDB with: '{query_text[:50]}...'")
    else: print(f"{log_prefix}Querying with: '{query_text[:50]}...'")

    collection = initialize_chroma_collection(tutor_id, status_dict)
    if not collection:
        error_msg = "Failed to initialize ChromaDB collection for querying."
        if status_dict: _update_status_safely(status_dict, error=error_msg, message=error_msg)
        else: print(f"{log_prefix}{error_msg}")
        return ""

    # Use the new Azure OpenAI based embedding function for the query
    query_embedding = get_embedding_for_text(query_text, status_dict)
    if not query_embedding:
        # Error is logged by get_embedding_for_text, just ensure main message reflects failure
        error_msg_emb = f"Failed to generate embedding for query: '{query_text[:50]}...'"
        if status_dict: _update_status_safely(status_dict, message=error_msg_emb)
        else: print(f"{log_prefix}{error_msg_emb}")
        return ""

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents"] # Only fetch documents, not embeddings or metadatas for context
        )

        documents = results.get("documents")
        if documents and isinstance(documents, list) and len(documents) > 0:
            # documents[0] will be a list of the actual document strings
            valid_documents = [str(doc) for doc in documents[0] if doc is not None]
            combined_content = "\\n---\\n".join(valid_documents)
            # success_msg = f"Retrieved {len(valid_documents)} context chunks."
            # if status_dict: _update_status_safely(status_dict, message=success_msg) # Can be too verbose
            # else: print(f"{log_prefix}{success_msg}")
            return combined_content
        else:
            no_results_msg = "No relevant documents found in ChromaDB for the query."
            if status_dict: _update_status_safely(status_dict, message=no_results_msg)
            else: print(f"{log_prefix}{no_results_msg}")
            return ""
    except Exception as e:
        error_msg_query = f"Error querying ChromaDB: {e}"
        if status_dict: _update_status_safely(status_dict, error=error_msg_query, message=error_msg_query)
        else: print(f"{log_prefix}{error_msg_query}")
        return ""


    