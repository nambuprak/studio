
import os
import uuid
import time
import requests # For get_embedding_for_text
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional

import chromadb
from chromadb.api.models.Collection import Collection as ChromaCollection
# from langchain_community.document_loaders import TextLoader # Not directly used here, file content read manually
from langchain.text_splitter import CharacterTextSplitter

# Environment variables for embedding API
# Use your actual model name if different from "text-embedding-ada-002"
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "text-embedding-ada-002")
# Get custom embedding API URL and Token from environment variables
CUSTOM_EMBEDDING_API_URL = os.getenv("CUSTOM_EMBEDDING_API_URL", "https://aienablement-api.mycompany.com/embeddings")
CUSTOM_EMBEDDING_API_TOKEN = os.getenv("CUSTOM_EMBEDDING_API_TOKEN")

if CUSTOM_EMBEDDING_API_TOKEN is None:
    print("Warning: CUSTOM_EMBEDDING_API_TOKEN environment variable is not set. Using placeholder token.")
    CUSTOM_EMBEDDING_API_TOKEN = "Bearer token12345678" # Fallback, but ideally script should fail or warn prominently

# Base directory for ChromaDB persistence.
PERSIST_DIR_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chroma_db_store")

# Embedding API call settings
MAX_RETRIES_EMBEDDING = 1 # Max retries for the embedding API call
RETRY_BACKOFF_FACTOR_EMBEDDING = 2 # Seconds

# Ensure the ChromaDB persistence directory exists
os.makedirs(PERSIST_DIR_BASE, exist_ok=True)
print(f"ChromaDB persistence directory set to: {PERSIST_DIR_BASE}")


def _update_status_safely(status_dict: Optional[Dict[str, Any]], message: Optional[str] = None, error: Optional[str] = None, progress_detail: Optional[str] = None):
    if status_dict is None:
        print(f"Warning: status_dict is None. Message: {message}, Error: {error}, Progress: {progress_detail}")
        return

    current_tutor_id = status_dict.get('tutor_id', 'N/A')
    log_prefix = f"Status Update (TutorID: {current_tutor_id}): "

    if message:
        status_dict["message"] = message
        print(f"{log_prefix}{message}")
    if error:
        status_dict["error"] = error
        error_message_to_set = f"Error: {error}"
        if "message" in status_dict and status_dict["message"] and "error" not in status_dict["message"].lower() and "failed" not in status_dict["message"].lower():
            status_dict["message"] = f"{status_dict['message']} - {error_message_to_set}"
        else:
            status_dict["message"] = error_message_to_set
        print(f"{log_prefix}Error recorded: {error}")

    if progress_detail:
        status_dict["progress_detail"] = progress_detail
        # If no specific message is set, or if the current message is generic, update with progress_detail
        if not status_dict.get("message") or status_dict.get("message", "").lower().startswith(("processing", "embedding","starting","cloning")):
             status_dict["message"] = progress_detail # Make progress detail the main message if appropriate
        print(f"{log_prefix}Progress: {progress_detail}")


def get_embedding_for_text(text: str, status_dict: Optional[dict] = None) -> Optional[List[float]]:
    """
    Gets embedding for a single text string using the custom API.
    Updates status_dict with errors if any.
    """
    url = CUSTOM_EMBEDDING_API_URL
    headers = {
        "accept": "application/json",
        "azure-deployment-version": os.getenv("EMBEDDING_API_VERSION", "2024-02-01"), # Example, make configurable
        "Authorization": CUSTOM_EMBEDDING_API_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {"model": EMBEDDING_MODEL_NAME, "input": text}

    retry_count = 0
    while retry_count < MAX_RETRIES_EMBEDDING:
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30) # 30-second timeout
            response.raise_for_status() # Raises HTTPError for bad responses (4XX or 5XX)
            embedding_data = response.json()

            if "data" in embedding_data and len(embedding_data["data"]) > 0 and "embedding" in embedding_data["data"][0]:
                return embedding_data["data"][0]["embedding"]
            else:
                err_msg = f"Invalid embedding response format for text: '{text[:50]}...'"
                if status_dict: _update_status_safely(status_dict, error=err_msg, progress_detail=err_msg)
                else: print(err_msg)
                return None # Or raise an error
        except requests.exceptions.RequestException as e:
            error_msg = f"Embedding API request failed: {e}. Attempt {retry_count + 1}/{MAX_RETRIES_EMBEDDING}."
            if status_dict: _update_status_safely(status_dict, error=error_msg, progress_detail=error_msg)
            else: print(error_msg)
            retry_count += 1
            if retry_count < MAX_RETRIES_EMBEDDING:
                time.sleep(RETRY_BACKOFF_FACTOR_EMBEDDING ** retry_count) # Exponential backoff
            else:
                final_error_msg = f"Failed to generate embedding after {MAX_RETRIES_EMBEDDING} attempts for text: '{text[:50]}...'"
                if status_dict: _update_status_safely(status_dict, error=final_error_msg, progress_detail=final_error_msg)
                else: print(final_error_msg)
                return None # Or raise an error
        except ValueError as ve: # Handles JSON decoding errors
             error_msg_ve = f"Error parsing embedding response: {ve} for text: '{text[:50]}...'"
             if status_dict: _update_status_safely(status_dict, error=error_msg_ve, progress_detail=error_msg_ve)
             else: print(error_msg_ve)
             return None # Or raise an error
    return None


def initialize_chroma_collection(tutor_id: str, status_dict: Optional[dict] = None) -> Optional[ChromaCollection]:
    """Initializes or gets a ChromaDB collection for a given tutor_id."""
    collection_name = f"tutor_{tutor_id.replace('-', '_')}" # Sanitize tutor_id for collection name
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
        # Check if collection exists before attempting to delete to avoid error if it's already gone
        collections = chroma_client.list_collections()
        if any(coll.name == collection_name for coll in collections):
            chroma_client.delete_collection(name=collection_name)
            print(f"Successfully deleted ChromaDB collection: {collection_name}")
        else:
            print(f"ChromaDB collection '{collection_name}' not found, no deletion needed.")
    except Exception as e:
        # Log the error but don't let it block the rest of the tutor deletion process typically
        print(f"Error deleting ChromaDB collection '{collection_name}': {e}. Manual cleanup might be needed.")
        # Depending on policy, you might want to raise this error to make it more critical.


def add_chunk_to_chromadb(collection: ChromaCollection, text_chunk: str, embedding: List[float], metadata: Dict[str, Any], status_dict: Optional[dict] = None):
    """Adds a single text chunk and its embedding to the specified ChromaDB collection."""
    chunk_id = str(uuid.uuid4()) # Generate a unique ID for the chunk
    try:
        collection.add(
            documents=[text_chunk],
            embeddings=[embedding],
            ids=[chunk_id],
            metadatas=[metadata] # Store metadata like source file, chunk index
        )
        # Optional: Log success, but can be verbose
        # if status_dict: _update_status_safely(status_dict, progress_detail=f"Added chunk from {metadata.get('source')} to ChromaDB.")
    except Exception as e:
        error_msg_add_chunk = f"Error adding chunk (Source: {metadata.get('source')}) to ChromaDB: {e}"
        if status_dict: _update_status_safely(status_dict, error=error_msg_add_chunk, progress_detail=error_msg_add_chunk)
        else: print(error_msg_add_chunk)


def _process_text_document_for_embedding(
    doc_text: str,
    source_name: str, # e.g., file path, "repository_overview", "additional_info_X"
    collection: ChromaCollection,
    text_splitter: CharacterTextSplitter,
    status_dict: dict # Assumed to be always provided here
):
    """Splits a text document, gets embeddings for chunks, and adds them to ChromaDB."""
    _update_status_safely(status_dict, progress_detail=f"Processing document: {source_name} for embedding...")
    if not doc_text.strip():
        _update_status_safely(status_dict, progress_detail=f"Skipping empty document: {source_name}.")
        return

    try:
        # Split the document into chunks
        raw_chunks = text_splitter.split_text(doc_text)
    except Exception as e: # Catch potential errors during text splitting
        _update_status_safely(status_dict, error=f"Error splitting document {source_name}: {e}", progress_detail=f"Failed to split {source_name}")
        return

    num_chunks = len(raw_chunks)
    _update_status_safely(status_dict, progress_detail=f"Split '{source_name}' into {num_chunks} chunk(s).")

    for i, chunk_text in enumerate(raw_chunks):
        if not chunk_text.strip(): # Skip empty chunks
            continue
        _update_status_safely(status_dict, progress_detail=f"Embedding chunk {i+1}/{num_chunks} from '{source_name}'...")

        embedding = get_embedding_for_text(chunk_text, status_dict)
        if embedding:
            metadata = {"source": source_name, "chunk_index": i}
            # Add more specific doc_type if needed
            if "file://" in source_name:
                 metadata["doc_type"] = "file_content"
            elif "repository_overview" == source_name: # Use exact match for special sources
                 metadata["doc_type"] = "repo_overview"
            elif source_name.startswith("additional_info_"):
                 metadata["doc_type"] = "additional_info"
            else:
                 metadata["doc_type"] = "generic_text"

            add_chunk_to_chromadb(collection, chunk_text, embedding, metadata, status_dict)
        else:
            # Error already logged by get_embedding_for_text
            _update_status_safely(status_dict, message=f"Failed to get embedding for chunk {i+1}/{num_chunks} from '{source_name}'. Skipping chunk.")


def _process_single_file_for_embedding(
    file_path: str,
    collection: ChromaCollection,
    text_splitter: CharacterTextSplitter,
    status_dict: dict # Assumed to be always provided
):
    """Reads a single file, then processes its content for embedding."""
    _update_status_safely(status_dict, progress_detail=f"Embedding file: {os.path.basename(file_path)}...")
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        if not content.strip():
            _update_status_safely(status_dict, progress_detail=f"Skipping empty file: {file_path}.")
            return
        # Use a source name that indicates it's a file
        _process_text_document_for_embedding(content, f"file://{file_path}", collection, text_splitter, status_dict)
    except Exception as e:
        _update_status_safely(status_dict, error=f"Error reading or processing file {file_path}: {e}", progress_detail=f"Failed for file: {os.path.basename(file_path)}")


def embed_documents_for_tutor(
    tutor_id: str,
    file_paths: List[str],        # List of absolute paths to discovered files
    repo_overview: str,           # Text content of the repository overview
    additional_info_list: List[Dict[str, str]], # List of {'title': '...', 'description': '...'}
    status_dict: dict             # For updating processing status
):
    """
    Main function to handle embedding for a tutor.
    Embeds discovered files, repository overview, and additional info.
    """
    _update_status_safely(status_dict, message="Starting document embedding process...")

    collection = initialize_chroma_collection(tutor_id, status_dict)
    if not collection:
        # Error already logged by initialize_chroma_collection
        _update_status_safely(status_dict, message=f"Fatal: Could not initialize ChromaDB for tutor {tutor_id}. Aborting embedding.", error="ChromaDB init failed")
        return # Cannot proceed without a collection

    # Configure the text splitter (adjust chunk_size and chunk_overlap as needed)
    text_splitter = CharacterTextSplitter(chunk_size=1700, chunk_overlap=200, separator="\n")

    # Embed repository overview
    if repo_overview and repo_overview.strip():
        _process_text_document_for_embedding(repo_overview, "repository_overview", collection, text_splitter, status_dict)
    else:
        _update_status_safely(status_dict, progress_detail="No repository overview provided, skipping its embedding.")

    # Embed additional info items
    if additional_info_list:
        for i, info_item in enumerate(additional_info_list):
            title = info_item.get('title', '')
            description = info_item.get('description', '')
            if title or description: # Only process if there's some content
                full_text = f"Title: {title}\nDescription: {description}"
                # Create a unique source name for each additional info item
                source_name_info = f"additional_info_{i}_{title.replace(' ', '_').lower()[:20]}" # Sanitize title for source name
                _process_text_document_for_embedding(full_text, source_name_info, collection, text_splitter, status_dict)
            else:
                 _update_status_safely(status_dict, progress_detail=f"Skipping empty additional info item at index {i}.")
    else:
        _update_status_safely(status_dict, progress_detail="No additional info items provided, skipping their embedding.")

    # Embed discovered files (concurrently)
    if file_paths:
        _update_status_safely(status_dict, message=f"Preparing to embed content from {len(file_paths)} discovered files...")
        # Adjust max_workers based on your API rate limits and server capabilities
        max_workers = min(10, os.cpu_count() * 2 if os.cpu_count() else 4) # Example: up to 10 concurrent workers

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for file_path in file_paths:
                futures.append(executor.submit(
                    _process_single_file_for_embedding,
                    file_path,
                    collection,
                    text_splitter,
                    status_dict # Pass status_dict for updates within the thread
                ))

            processed_files_count = 0
            total_files = len(file_paths)
            for i, future in enumerate(futures): # Wait for futures to complete
                try:
                    future.result() # Can raise exceptions from the thread
                    processed_files_count +=1
                    # More granular progress update might be too verbose here, already done in _process_single_file_for_embedding
                    # _update_status_safely(status_dict, progress_detail=f"Completed embedding for file {i+1}/{total_files}: {os.path.basename(file_paths[i])}.")
                except Exception as e:
                    # Error is already logged within _process_single_file_for_embedding or get_embedding_for_text
                    _update_status_safely(status_dict, message=f"An error occurred processing one of the files ({os.path.basename(file_paths[i])}): {e}")
        _update_status_safely(status_dict, message=f"Finished embedding content from {processed_files_count}/{total_files} files.")
    else:
        _update_status_safely(status_dict, progress_detail="No files discovered or provided for embedding.")

    _update_status_safely(status_dict, message="Document embedding process fully completed for this tutor.")


def query_chroma_for_tutor(tutor_id: str, query_text: str, n_results: int = 5, status_dict: Optional[Dict[str, Any]] = None) -> str:
    """Queries ChromaDB for a given tutor_id and query_text."""
    if status_dict: _update_status_safely(status_dict, message=f"Querying ChromaDB for tutor {tutor_id} with query: '{query_text[:50]}...'")
    else: print(f"Querying ChromaDB for tutor {tutor_id} with query: '{query_text[:50]}...'")

    collection = initialize_chroma_collection(tutor_id, status_dict)
    if not collection:
        error_msg = "Failed to initialize ChromaDB collection for querying."
        if status_dict: _update_status_safely(status_dict, error=error_msg)
        else: print(error_msg)
        return "" # Return empty string on failure

    query_embedding = get_embedding_for_text(query_text, status_dict)
    if not query_embedding:
        error_msg_emb = f"Failed to generate embedding for query: '{query_text[:50]}...'"
        # get_embedding_for_text already logs to status_dict if provided
        if not status_dict: print(error_msg_emb)
        return ""

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents"] # Only fetch document content
        )

        documents = results.get("documents")
        if documents and isinstance(documents, list) and len(documents) > 0:
            # ChromaDB query returns a list of lists for documents, even for a single query embedding
            # Ensure all elements in documents[0] are strings before joining
            valid_documents = [str(doc) for doc in documents[0] if doc is not None]
            combined_content = "\n---\n".join(valid_documents)
            success_msg = f"Retrieved {len(valid_documents)} context chunks from ChromaDB."
            if status_dict: _update_status_safely(status_dict, message=success_msg)
            else: print(success_msg)
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

    