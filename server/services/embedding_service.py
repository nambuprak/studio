
import os
import uuid
import time
import requests
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional

import chromadb
from chromadb.api.models.Collection import Collection as ChromaCollection
# from langchain_community.document_loaders import TextLoader # Not used directly here, handled by caller
from langchain.text_splitter import CharacterTextSplitter # Correct import if using langchain for splitting

# Environment variables or constants from your script (adapt as needed)
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "text-embedding-ada-002")
# Store ChromaDB in a subdirectory of the server directory
PERSIST_DIR_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chroma_db_store")
MAX_RETRIES_EMBEDDING = 1  # As per user's script (was 3 commented out)
RETRY_BACKOFF_FACTOR_EMBEDDING = 2 # seconds

# Ensure the ChromaDB persistence directory exists
os.makedirs(PERSIST_DIR_BASE, exist_ok=True)
print(f"ChromaDB persistence directory set to: {PERSIST_DIR_BASE}")


def _update_status_safely(status_dict: Optional[Dict[str, Any]], message: Optional[str] = None, error: Optional[str] = None, progress_detail: Optional[str] = None):
    if status_dict is None:
        print(f"Warning: status_dict is None. Message: {message}, Error: {error}")
        return
    
    current_tutor_id = status_dict.get('tutor_id', 'N/A')
    log_prefix = f"Status Update (TutorID: {current_tutor_id}): "

    if message:
        status_dict["message"] = message
        print(f"{log_prefix}{message}")
    if error:
        status_dict["error"] = error
        # If there's an error, it often becomes the main message or part of it
        error_message_to_set = f"Error: {error}"
        if message and "error" not in message.lower() and "failed" not in message.lower():
            status_dict["message"] = f"{message} - {error_message_to_set}"
        else:
            status_dict["message"] = error_message_to_set
        print(f"{log_prefix}Error recorded: {error}")

    if progress_detail: # For more granular updates if needed
        status_dict["progress_detail"] = progress_detail
        # Often, a progress detail also becomes the main status message if no other message is more prominent
        if not message and "message" not in status_dict: # if no specific message set yet
             status_dict["message"] = progress_detail
        print(f"{log_prefix}Progress: {progress_detail}")


def get_embedding_for_text(text: str, status_dict: dict) -> Optional[List[float]]:
    """
    Gets embedding for a single text string using the custom API.
    Adapted from user's getembeddings function.
    """
    # This URL and token should ideally come from environment variables or a secure config
    url = "https://aienablement-api.mycompany.com/embeddings"
    headers = {
        "accept": "application/json",
        "azure-deployment-version": "2024-02-01", # This might be specific to your API
        "Authorization": "Bearer token12345678", # HARDCODED TOKEN - VERY INSECURE FOR PRODUCTION
        "Content-Type": "application/json"
    }
    payload = {"model": EMBEDDING_MODEL_NAME, "input": text}
    
    retry_count = 0
    while retry_count < MAX_RETRIES_EMBEDDING:
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30) # Added timeout
            response.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)
            embedding_data = response.json()
            
            if "data" in embedding_data and len(embedding_data["data"]) > 0 and "embedding" in embedding_data["data"][0]:
                return embedding_data["data"][0]["embedding"]
            else:
                _update_status_safely(status_dict, message=f"Invalid embedding response format for text (first 50 chars): '{text[:50]}...'", error="Invalid embedding response")
                return None
        except requests.exceptions.RequestException as e:
            _update_status_safely(status_dict, message=f"Embedding API request failed: {e}. Attempt {retry_count + 1}/{MAX_RETRIES_EMBEDDING}.", error=str(e))
            retry_count += 1
            if retry_count < MAX_RETRIES_EMBEDDING:
                time.sleep(RETRY_BACKOFF_FACTOR_EMBEDDING ** retry_count) # Exponential backoff
            else:
                _update_status_safely(status_dict, message=f"Failed to generate embedding after {MAX_RETRIES_EMBEDDING} attempts for text: '{text[:50]}...'", error="Max retries reached for embedding API")
                return None
        except ValueError as ve: # For JSON decoding errors
             _update_status_safely(status_dict, message=f"Error parsing embedding response: {ve} for text: '{text[:50]}...'", error=str(ve))
             return None # typically not retryable
    return None


def initialize_chroma_collection(tutor_id: str, status_dict: dict) -> Optional[ChromaCollection]:
    collection_name = f"tutor_{tutor_id.replace('-', '_')}" # Ensure valid collection name
    try:
        _update_status_safely(status_dict, message=f"Initializing ChromaDB client at {PERSIST_DIR_BASE}...")
        chroma_client = chromadb.PersistentClient(path=PERSIST_DIR_BASE)
        
        _update_status_safely(status_dict, message=f"Getting or creating ChromaDB collection: {collection_name}...")
        collection = chroma_client.get_or_create_collection(name=collection_name)
        _update_status_safely(status_dict, message=f"ChromaDB collection '{collection_name}' ready.")
        return collection
    except Exception as e:
        _update_status_safely(status_dict, message=f"Error initializing ChromaDB for tutor {tutor_id}: {e}", error=str(e))
        return None


def add_chunk_to_chromadb(collection: ChromaCollection, text_chunk: str, embedding: List[float], metadata: Dict[str, Any], status_dict: dict):
    chunk_id = str(uuid.uuid4())
    try:
        collection.add(
            documents=[text_chunk],
            embeddings=[embedding],
            ids=[chunk_id],
            metadatas=[metadata]
        )
        # _update_status_safely(status_dict, progress_detail=f"Added chunk (ID: {chunk_id}, Source: {metadata.get('source')}) to ChromaDB.")
        # This level of detail might be too verbose for the main status_dict message, keeping it commented.
    except Exception as e:
        _update_status_safely(status_dict, message=f"Error adding chunk (Source: {metadata.get('source')}) to ChromaDB: {e}", error=str(e))


def _process_text_document_for_embedding(
    doc_text: str, 
    source_name: str, # e.g., file_path, "repository_overview", "additional_info_X"
    collection: ChromaCollection, 
    text_splitter: CharacterTextSplitter, 
    status_dict: dict
):
    _update_status_safely(status_dict, message=f"Processing document: {source_name} for embedding...")
    if not doc_text.strip():
        _update_status_safely(status_dict, message=f"Skipping empty document: {source_name}.")
        return

    # Langchain's CharacterTextSplitter expects a list of Document objects or list of strings.
    # For a single text, we can split it directly.
    try:
        raw_chunks = text_splitter.split_text(doc_text)
    except Exception as e:
        _update_status_safely(status_dict, message=f"Error splitting document {source_name}: {e}", error=str(e))
        return
        
    num_chunks = len(raw_chunks)
    _update_status_safely(status_dict, progress_detail=f"Split '{source_name}' into {num_chunks} chunk(s). Setting this as current message.") # Adjusted to provide a message

    for i, chunk_text in enumerate(raw_chunks):
        if not chunk_text.strip(): # Skip empty chunks
            continue
        _update_status_safely(status_dict, progress_detail=f"Embedding chunk {i+1}/{num_chunks} from '{source_name}'...") # This will update status_dict["message"] if no other message is set
        
        embedding = get_embedding_for_text(chunk_text, status_dict)
        if embedding:
            metadata = {"source": source_name, "chunk_index": i, "doc_type": "file_content" if "file://" in source_name else "metadata_text"}
            if "repository_overview" in source_name:
                 metadata["doc_type"] = "repo_overview"
            elif "additional_info" in source_name:
                 metadata["doc_type"] = "additional_info"

            add_chunk_to_chromadb(collection, chunk_text, embedding, metadata, status_dict)
        else:
            _update_status_safely(status_dict, message=f"Failed to get embedding for chunk {i+1}/{num_chunks} from '{source_name}'. Skipping this chunk.")


def _process_single_file_for_embedding(
    file_path: str, 
    collection: ChromaCollection, 
    text_splitter: CharacterTextSplitter, 
    status_dict: dict
):
    _update_status_safely(status_dict, message=f"Reading and embedding file: {os.path.basename(file_path)}...")
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        if not content.strip():
            _update_status_safely(status_dict, message=f"Skipping empty file: {file_path}.")
            return
        _process_text_document_for_embedding(content, f"file://{file_path}", collection, text_splitter, status_dict)
    except Exception as e:
        _update_status_safely(status_dict, message=f"Error reading or processing file {file_path}: {e}", error=str(e))


def embed_documents_for_tutor(
    tutor_id: str,
    file_paths: List[str],
    repo_overview: str,
    additional_info_list: List[Dict[str, str]], # Each dict is {'title': str, 'description': str}
    status_dict: dict
):
    _update_status_safely(status_dict, message="Starting document embedding process...")
    
    collection = initialize_chroma_collection(tutor_id, status_dict)
    if not collection:
        _update_status_safely(status_dict, message=f"Fatal: Could not initialize ChromaDB for tutor {tutor_id}. Aborting embedding.", error="ChromaDB init failed")
        return

    # Standard text splitter configuration
    text_splitter = CharacterTextSplitter(chunk_size=1700, chunk_overlap=200, separator="\n")

    # 1. Embed repository_overview
    if repo_overview and repo_overview.strip():
        _process_text_document_for_embedding(repo_overview, "repository_overview", collection, text_splitter, status_dict)
    else:
        _update_status_safely(status_dict, message="No repository overview provided or it's empty, skipping its embedding.")

    # 2. Embed additional_info_list
    if additional_info_list:
        for i, info_item in enumerate(additional_info_list):
            title = info_item.get('title', '')
            description = info_item.get('description', '')
            if title or description: # Only process if there's some content
                full_text = f"Title: {title}\nDescription: {description}"
                source_name_info = f"additional_info_{i}_{title.replace(' ', '_')[:20]}" # Create a more file-like source name
                _process_text_document_for_embedding(full_text, source_name_info, collection, text_splitter, status_dict)
            else:
                 _update_status_safely(status_dict, message=f"Skipping empty additional info item at index {i}.")
    else:
        _update_status_safely(status_dict, message="No additional info items provided, skipping their embedding.")


    # 3. Embed files using ThreadPoolExecutor
    if file_paths:
        _update_status_safely(status_dict, message=f"Preparing to embed content from {len(file_paths)} discovered files...")
        # Adjust max_workers based on your embedding API's rate limits and server capacity
        max_workers = min(10, os.cpu_count() * 2 if os.cpu_count() else 4) 
        
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
                    # Provide a message for each completed file if desired, or a summary
                    _update_status_safely(status_dict, progress_detail=f"Completed embedding for file {i+1}/{total_files}: {os.path.basename(file_paths[i])}.")
                except Exception as e:
                    # Error already logged by _process_single_file_for_embedding or get_embedding_for_text
                    _update_status_safely(status_dict, message=f"An error occurred processing one of the files ({os.path.basename(file_paths[i])}): {e}")
        _update_status_safely(status_dict, message=f"Finished embedding content from {processed_files_count}/{total_files} files.")
    else:
        _update_status_safely(status_dict, message="No files discovered or provided for embedding.")

    _update_status_safely(status_dict, message="Document embedding process fully completed for this tutor.")

