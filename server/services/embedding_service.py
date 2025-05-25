
import os
import uuid
import time
import requests
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional

import chromadb
from chromadb.api.models.Collection import Collection as ChromaCollection
from langchain.text_splitter import CharacterTextSplitter

EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "text-embedding-ada-002")
PERSIST_DIR_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chroma_db_store")
MAX_RETRIES_EMBEDDING = 1
RETRY_BACKOFF_FACTOR_EMBEDDING = 2 # seconds

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
        error_message_to_set = f"Error: {error}"
        if message and "error" not in message.lower() and "failed" not in message.lower():
            status_dict["message"] = f"{message} - {error_message_to_set}"
        else:
            status_dict["message"] = error_message_to_set
        print(f"{log_prefix}Error recorded: {error}")

    if progress_detail:
        status_dict["progress_detail"] = progress_detail
        if not message or "message" not in status_dict : # if no specific message set yet or current message is generic
             status_dict["message"] = progress_detail
        print(f"{log_prefix}Progress: {progress_detail}")


def get_embedding_for_text(text: str, status_dict: Optional[dict] = None) -> Optional[List[float]]:
    """
    Gets embedding for a single text string using the custom API.
    """
    url = "https://aienablement-api.mycompany.com/embeddings" # Replace with your actual API
    headers = {
        "accept": "application/json",
        "azure-deployment-version": "2024-02-01",
        "Authorization": "Bearer token12345678", # HARDCODED TOKEN - INSECURE
        "Content-Type": "application/json"
    }
    payload = {"model": EMBEDDING_MODEL_NAME, "input": text}
    
    retry_count = 0
    while retry_count < MAX_RETRIES_EMBEDDING:
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            embedding_data = response.json()
            
            if "data" in embedding_data and len(embedding_data["data"]) > 0 and "embedding" in embedding_data["data"][0]:
                return embedding_data["data"][0]["embedding"]
            else:
                if status_dict: _update_status_safely(status_dict, error=f"Invalid embedding response format for text: '{text[:50]}...'")
                else: print(f"Invalid embedding response format for text: '{text[:50]}...'")
                return None
        except requests.exceptions.RequestException as e:
            error_msg = f"Embedding API request failed: {e}. Attempt {retry_count + 1}/{MAX_RETRIES_EMBEDDING}."
            if status_dict: _update_status_safely(status_dict, error=error_msg)
            else: print(error_msg)
            retry_count += 1
            if retry_count < MAX_RETRIES_EMBEDDING:
                time.sleep(RETRY_BACKOFF_FACTOR_EMBEDDING ** retry_count)
            else:
                final_error_msg = f"Failed to generate embedding after {MAX_RETRIES_EMBEDDING} attempts for text: '{text[:50]}...'"
                if status_dict: _update_status_safely(status_dict, error=final_error_msg)
                else: print(final_error_msg)
                return None
        except ValueError as ve:
             error_msg_ve = f"Error parsing embedding response: {ve} for text: '{text[:50]}...'"
             if status_dict: _update_status_safely(status_dict, error=error_msg_ve)
             else: print(error_msg_ve)
             return None
    return None


def initialize_chroma_collection(tutor_id: str, status_dict: Optional[dict] = None) -> Optional[ChromaCollection]:
    collection_name = f"tutor_{tutor_id.replace('-', '_')}"
    try:
        if status_dict: _update_status_safely(status_dict, message=f"Initializing ChromaDB client at {PERSIST_DIR_BASE}...")
        chroma_client = chromadb.PersistentClient(path=PERSIST_DIR_BASE)
        
        if status_dict: _update_status_safely(status_dict, message=f"Getting or creating ChromaDB collection: {collection_name}...")
        collection = chroma_client.get_or_create_collection(name=collection_name)
        if status_dict: _update_status_safely(status_dict, message=f"ChromaDB collection '{collection_name}' ready.")
        return collection
    except Exception as e:
        error_msg_chroma = f"Error initializing ChromaDB for tutor {tutor_id}: {e}"
        if status_dict: _update_status_safely(status_dict, error=error_msg_chroma)
        else: print(error_msg_chroma)
        return None


def add_chunk_to_chromadb(collection: ChromaCollection, text_chunk: str, embedding: List[float], metadata: Dict[str, Any], status_dict: Optional[dict] = None):
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
    if status_dict: _update_status_safely(status_dict, progress_detail=f"Processing document: {source_name} for embedding...")
    if not doc_text.strip():
        if status_dict: _update_status_safely(status_dict, progress_detail=f"Skipping empty document: {source_name}.")
        return

    try:
        raw_chunks = text_splitter.split_text(doc_text)
    except Exception as e:
        if status_dict: _update_status_safely(status_dict, error=f"Error splitting document {source_name}: {e}")
        return
        
    num_chunks = len(raw_chunks)
    if status_dict: _update_status_safely(status_dict, progress_detail=f"Split '{source_name}' into {num_chunks} chunk(s).")

    for i, chunk_text in enumerate(raw_chunks):
        if not chunk_text.strip():
            continue
        if status_dict: _update_status_safely(status_dict, progress_detail=f"Embedding chunk {i+1}/{num_chunks} from '{source_name}'...")
        
        embedding = get_embedding_for_text(chunk_text, status_dict)
        if embedding:
            metadata = {"source": source_name, "chunk_index": i, "doc_type": "file_content" if "file://" in source_name else "metadata_text"}
            if "repository_overview" in source_name:
                 metadata["doc_type"] = "repo_overview"
            elif "additional_info" in source_name:
                 metadata["doc_type"] = "additional_info"
            add_chunk_to_chromadb(collection, chunk_text, embedding, metadata, status_dict)
        else:
            if status_dict: _update_status_safely(status_dict, message=f"Failed to get embedding for chunk {i+1}/{num_chunks} from '{source_name}'. Skipping chunk.")


def _process_single_file_for_embedding(
    file_path: str, 
    collection: ChromaCollection, 
    text_splitter: CharacterTextSplitter, 
    status_dict: dict 
):
    if status_dict: _update_status_safely(status_dict, progress_detail=f"Embedding file: {os.path.basename(file_path)}...")
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        if not content.strip():
            if status_dict: _update_status_safely(status_dict, progress_detail=f"Skipping empty file: {file_path}.")
            return
        _process_text_document_for_embedding(content, f"file://{file_path}", collection, text_splitter, status_dict)
    except Exception as e:
        if status_dict: _update_status_safely(status_dict, error=f"Error reading or processing file {file_path}: {e}")


def embed_documents_for_tutor(
    tutor_id: str,
    file_paths: List[str],
    repo_overview: str,
    additional_info_list: List[Dict[str, str]],
    status_dict: dict 
):
    if status_dict: _update_status_safely(status_dict, message="Starting document embedding process...")
    
    collection = initialize_chroma_collection(tutor_id, status_dict)
    if not collection:
        if status_dict: _update_status_safely(status_dict, message=f"Fatal: Could not initialize ChromaDB for tutor {tutor_id}. Aborting embedding.", error="ChromaDB init failed")
        return

    text_splitter = CharacterTextSplitter(chunk_size=1700, chunk_overlap=200, separator="\n")

    if repo_overview and repo_overview.strip():
        _process_text_document_for_embedding(repo_overview, "repository_overview", collection, text_splitter, status_dict)
    else:
        if status_dict: _update_status_safely(status_dict, progress_detail="No repository overview provided, skipping its embedding.")

    if additional_info_list:
        for i, info_item in enumerate(additional_info_list):
            title = info_item.get('title', '')
            description = info_item.get('description', '')
            if title or description:
                full_text = f"Title: {title}\nDescription: {description}"
                source_name_info = f"additional_info_{i}_{title.replace(' ', '_')[:20]}"
                _process_text_document_for_embedding(full_text, source_name_info, collection, text_splitter, status_dict)
            else:
                 if status_dict: _update_status_safely(status_dict, progress_detail=f"Skipping empty additional info item at index {i}.")
    else:
        if status_dict: _update_status_safely(status_dict, progress_detail="No additional info items provided, skipping their embedding.")

    if file_paths:
        if status_dict: _update_status_safely(status_dict, message=f"Preparing to embed content from {len(file_paths)} discovered files...")
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
                    future.result()
                    processed_files_count +=1
                    if status_dict: _update_status_safely(status_dict, progress_detail=f"Completed embedding for file {i+1}/{total_files}: {os.path.basename(file_paths[i])}.")
                except Exception as e:
                    if status_dict: _update_status_safely(status_dict, message=f"An error occurred processing one of the files ({os.path.basename(file_paths[i])}): {e}")
        if status_dict: _update_status_safely(status_dict, message=f"Finished embedding content from {processed_files_count}/{total_files} files.")
    else:
        if status_dict: _update_status_safely(status_dict, progress_detail="No files discovered or provided for embedding.")

    if status_dict: _update_status_safely(status_dict, message="Document embedding process fully completed for this tutor.")

def query_chroma_for_tutor(tutor_id: str, query_text: str, n_results: int = 5, status_dict: Optional[Dict[str, Any]] = None) -> str:
    """Queries ChromaDB for a given tutor_id and query_text."""
    if status_dict: _update_status_safely(status_dict, message=f"Querying ChromaDB for tutor {tutor_id} with query: '{query_text[:50]}...'")
    else: print(f"Querying ChromaDB for tutor {tutor_id} with query: '{query_text[:50]}...'")

    collection = initialize_chroma_collection(tutor_id, status_dict)
    if not collection:
        error_msg = "Failed to initialize ChromaDB collection for querying."
        if status_dict: _update_status_safely(status_dict, error=error_msg)
        else: print(error_msg)
        return ""

    query_embedding = get_embedding_for_text(query_text, status_dict)
    if not query_embedding:
        error_msg_emb = f"Failed to generate embedding for query: '{query_text[:50]}...'"
        if status_dict: _update_status_safely(status_dict, error=error_msg_emb)
        else: print(error_msg_emb)
        return ""

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents"] # Only fetch documents
        )

        documents = results.get("documents")
        if documents and isinstance(documents, list) and len(documents) > 0:
            # ChromaDB query returns a list of lists for documents, even for a single query embedding
            combined_content = "\n---\n".join(documents[0]) # Join documents from the first (and only) result set
            if status_dict: _update_status_safely(status_dict, message=f"Retrieved {len(documents[0])} context chunks from ChromaDB.")
            else: print(f"Retrieved {len(documents[0])} context chunks from ChromaDB.")
            return combined_content
        else:
            if status_dict: _update_status_safely(status_dict, message="No relevant documents found in ChromaDB for the query.")
            else: print("No relevant documents found in ChromaDB for the query.")
            return ""
    except Exception as e:
        error_msg_query = f"Error querying ChromaDB: {e}"
        if status_dict: _update_status_safely(status_dict, error=error_msg_query)
        else: print(error_msg_query)
        return ""

