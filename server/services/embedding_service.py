
import os
import uuid
import time
import requests # For get_embedding_for_text_custom_api
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional

import chromadb
from chromadb.api.models.Collection import Collection as ChromaCollection
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
CUSTOM_EMBEDDING_API_TOKEN = os.getenv(CUSTOM_EMBEDDING_API_TOKEN_ENV_VAR)
CUSTOM_EMBEDDING_API_MODEL_NAME = os.getenv(CUSTOM_EMBEDDING_API_MODEL_NAME_ENV_VAR, "text-embedding-ada-002")


if CUSTOM_EMBEDDING_API_TOKEN is None:
    print(f"Warning: {CUSTOM_EMBEDDING_API_TOKEN_ENV_VAR} environment variable is not set. Using placeholder token for get_embedding_for_text_custom_api.")
    CUSTOM_EMBEDDING_API_TOKEN = "Bearer placeholder_token_custom_api"

# Base directory for ChromaDB persistence.
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
    log_prefix = f"Status Update (TutorID: {current_tutor_id}): "

    if message:
        status_dict["message"] = message
        # print(f"{log_prefix}{message}") # Can be too verbose, app.py handles primary status printing
    if error:
        status_dict["error"] = error
        error_message_to_set = f"Error: {error}"
        if "message" in status_dict and status_dict["message"] and "error" not in status_dict["message"].lower() and "failed" not in status_dict["message"].lower():
            status_dict["message"] = f"{status_dict['message']} - {error_message_to_set}"
        else:
            status_dict["message"] = error_message_to_set
        # print(f"{log_prefix}Error recorded: {error}")

    if progress_detail:
        status_dict["progress_detail"] = progress_detail
        if not status_dict.get("message") or status_dict.get("message", "").lower().startswith(("processing", "embedding","starting","cloning", "initializing")):
             status_dict["message"] = progress_detail
        # print(f"{log_prefix}Progress: {progress_detail}")


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
        except ValueError as ve:
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
            response = azure_client.embeddings.create(
                model=embedding_deployment_name,
                input=text
            )
            if response.data and len(response.data) > 0:
                return response.data[0].embedding
            else:
                err_msg_format = f"Invalid Azure OpenAI embedding response format for text: '{text[:50]}...'"
                if status_dict: _update_status_safely(status_dict, error=err_msg_format, progress_detail=err_msg_format)
                else: print(err_msg_format)
                return None
        except Exception as e: # Catch broader exceptions from the OpenAI client
            error_msg = f"Azure OpenAI Embedding API call failed: {e}. Attempt {retry_count + 1}/{MAX_RETRIES_EMBEDDING}."
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
    """Deletes the ChromaDB collection associated with a given tutor_id."""
    collection_name = f"tutor_{tutor_id.replace('-', '_')}"
    try:
        print(f"Attempting to delete ChromaDB collection: {collection_name} from {PERSIST_DIR_BASE}")
        chroma_client = chromadb.PersistentClient(path=PERSIST_DIR_BASE)
        collections = chroma_client.list_collections()
        if any(coll.name == collection_name for coll in collections):
            chroma_client.delete_collection(name=collection_name)
            print(f"Successfully deleted ChromaDB collection: {collection_name}")
        else:
            print(f"ChromaDB collection '{collection_name}' not found, no deletion needed.")
    except Exception as e:
        print(f"Error deleting ChromaDB collection '{collection_name}': {e}. Manual cleanup might be needed.")


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
            continue
        _update_status_safely(status_dict, progress_detail=f"Embedding chunk {i+1}/{num_chunks} from '{source_name}'...")

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

    text_splitter = CharacterTextSplitter(chunk_size=1700, chunk_overlap=200, separator="\n")

    if repo_overview and repo_overview.strip():
        _process_text_document_for_embedding(repo_overview, "repository_overview", collection, text_splitter, status_dict)
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
            else:
                 _update_status_safely(status_dict, progress_detail=f"Skipping empty additional info item at index {i}.")
    else:
        _update_status_safely(status_dict, progress_detail="No additional info items provided, skipping their embedding.")

    if file_paths:
        _update_status_safely(status_dict, message=f"Preparing to embed content from {len(file_paths)} discovered files...")
        max_workers = min(5, os.cpu_count() * 2 if os.cpu_count() else 4) # Reduced max_workers slightly to avoid hitting API limits too fast

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
                    future.result()
                    processed_files_count +=1
                except Exception as e:
                    _update_status_safely(status_dict, message=f"An error occurred processing one of the files ({os.path.basename(file_paths[i])}): {e}")
        _update_status_safely(status_dict, message=f"Finished embedding content from {processed_files_count}/{total_files} files.")
    else:
        _update_status_safely(status_dict, progress_detail="No files discovered or provided for embedding.")

    _update_status_safely(status_dict, message="Document embedding process fully completed for this tutor.")


def query_chroma_for_tutor(tutor_id: str, query_text: str, n_results: int = 5, status_dict: Optional[Dict[str, Any]] = None) -> str:
    """Queries ChromaDB for a given tutor_id and query_text using Azure OpenAI for query embedding."""
    if status_dict: _update_status_safely(status_dict, message=f"Querying ChromaDB for tutor {tutor_id} with query: '{query_text[:50]}...'")
    # else: print(f"Querying ChromaDB for tutor {tutor_id} with query: '{query_text[:50]}...'") # Can be verbose

    collection = initialize_chroma_collection(tutor_id, status_dict)
    if not collection:
        error_msg = "Failed to initialize ChromaDB collection for querying."
        if status_dict: _update_status_safely(status_dict, error=error_msg)
        else: print(error_msg)
        return ""

    # Use the new Azure OpenAI based embedding function for the query
    query_embedding = get_embedding_for_text(query_text, status_dict)
    if not query_embedding:
        error_msg_emb = f"Failed to generate embedding for query: '{query_text[:50]}...'"
        if not status_dict: print(error_msg_emb) # Error already logged to status_dict if provided
        return ""

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents"]
        )

        documents = results.get("documents")
        if documents and isinstance(documents, list) and len(documents) > 0:
            valid_documents = [str(doc) for doc in documents[0] if doc is not None]
            combined_content = "\n---\n".join(valid_documents)
            # success_msg = f"Retrieved {len(valid_documents)} context chunks from ChromaDB."
            # if status_dict: _update_status_safely(status_dict, message=success_msg) # Can be too verbose
            # else: print(success_msg)
            return combined_content
        else:
            no_results_msg = "No relevant documents found in ChromaDB for the query."
            if status_dict: _update_status_safely(status_dict, message=no_results_msg)
            else: print(no_results_msg)
            return ""
    except Exception as e:
        error_msg_query = f"Error querying ChromaDB: {e}"
        if status_dict: _update_status_safely(status_dict, error=error_msg_query)
        else: print(error_msg_query)
        return ""

    

    