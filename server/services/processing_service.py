
import os
import shutil
import git # For Git operations
import pathspec # For .gitignore processing
from typing import Dict, Any, List, Tuple, Optional

# Relative import for embedding_service
from .embedding_service import embed_documents_for_tutor


def _read_gitignore(directory_path: str) -> pathspec.PathSpec:
    """Reads .gitignore from the given directory and returns a PathSpec object."""
    gitignore_path = os.path.join(directory_path, ".gitignore")
    patterns: List[str] = []
    if os.path.exists(gitignore_path):
        try:
            with open(gitignore_path, "r", encoding='utf-8', errors='ignore') as f:
                patterns = f.read().splitlines()
            print(f"Read {len(patterns)} patterns from .gitignore at {gitignore_path}")
        except Exception as e:
            print(f"Warning: Could not read .gitignore at {gitignore_path}: {e}")
    
    # Ensure .git directory itself is always part of the spec to be ignored if present.
    # This is important because pathspec matches against relative paths from the .gitignore location.
    # Adding it here makes it behave more like git itself, which won't traverse .git.
    if ".git/" not in patterns and ".git" not in patterns:
        patterns.append(".git/")
    return pathspec.PathSpec.from_lines('gitwildmatch', patterns)

def _update_status(status_dict: Optional[Dict[str, Any]], message: Optional[str] = None, status: Optional[str] = None, processed_files_count: Optional[int] = None, total_files_estimate: Optional[int] = None, error: Optional[str] = None):
    if status_dict:
        tutor_id_log = status_dict.get('tutor_id', 'N/A')
        
        if error:
            status_dict["error"] = error
            status_dict["message"] = f"Error: {error}" # Error message takes precedence
            status_dict["status"] = "FAILED" # Always set status to FAILED if an error is reported
            print(f"Error Update (TutorID: {tutor_id_log}): {error}")
            return # Stop further processing for this update call

        if message:
            status_dict["message"] = message
            print(f"Status Update (TutorID: {tutor_id_log}): {message}")
        
        if status: # Allows setting specific status like "PROCESSING_FILES" or "COMPLETED"
            status_dict["status"] = status

        if processed_files_count is not None:
            status_dict["discovered_files_count"] = processed_files_count
        if total_files_estimate is not None:
            status_dict["total_files_estimate"] = total_files_estimate


def _process_files_in_directory(
    directory_path: str,
    file_types_str: str,
    exclude_folders_str: str,
    tutor_id: str, 
    status_dict: Optional[Dict[str, Any]],
    is_local_folder_walk: bool = False 
) -> List[str]: 
    """
    Walks through a directory, collects absolute paths of files matching criteria.
    If is_local_folder_walk is True, it will also try to respect .gitignore rules.
    Updates status_dict with progress. Returns list of absolute file paths.
    """
    discovered_file_paths: List[str] = []

    file_types_to_include = [ft.strip() for ft in file_types_str.split(',') if ft.strip()]
    file_types_to_include = [ft if ft.startswith('.') else '.' + ft for ft in file_types_to_include if ft]

    folders_to_exclude_set = {fd.strip() for fd in exclude_folders_str.split(',') if fd.strip()}

    _update_status(status_dict, message=f"Starting file scan in: {directory_path}. Including: {file_types_to_include or 'all'}. Excluding folders: {folders_to_exclude_set or 'none'}.")

    gitignore_spec: Optional[pathspec.PathSpec] = None
    if is_local_folder_walk: 
        gitignore_spec = _read_gitignore(directory_path)
        if gitignore_spec and gitignore_spec.patterns:
             _update_status(status_dict, message=f"Applying .gitignore rules from {os.path.join(directory_path, '.gitignore')}")

    current_file_count = 0
    for root, dirs, files in os.walk(directory_path, topdown=True):
        # For .gitignore compatibility, we need paths relative to the directory_path (where .gitignore is)
        original_dirs_copy = list(dirs) 
        dirs[:] = [] 

        for d_name in original_dirs_copy:
            dir_path_full = os.path.join(root, d_name)
            dir_path_relative_to_walk_root = os.path.relpath(dir_path_full, directory_path)

            if d_name in folders_to_exclude_set:
                _update_status(status_dict, message=f"Excluding folder by user rule: {dir_path_full}")
                continue
            
            # Always exclude .git if processing a local folder, even if not in .gitignore or exclude_folders_str
            # For cloned repos, .git is usually not an issue as we care about checked-out files.
            if is_local_folder_walk and d_name == ".git":
                _update_status(status_dict, message=f"Skipping .git directory: {dir_path_full}")
                continue

            if d_name.startswith('.'): 
                 if d_name not in [".git"]: # .git has specific handling above or by gitignore_spec
                    _update_status(status_dict, message=f"Skipping hidden directory: {dir_path_full}")
                    continue
            
            if gitignore_spec and gitignore_spec.match_file(dir_path_relative_to_walk_root + '/'):
                _update_status(status_dict, message=f"Excluding folder by .gitignore: {dir_path_full}")
                continue
            
            dirs.append(d_name)

        for file_name in files:
            file_path_full = os.path.join(root, file_name)
            file_path_relative_to_walk_root = os.path.relpath(file_path_full, directory_path)

            if gitignore_spec and gitignore_spec.match_file(file_path_relative_to_walk_root):
                _update_status(status_dict, message=f"Excluding file by .gitignore: {file_path_full}")
                continue

            if file_name.startswith('.') and not any(file_name.endswith(ft) for ft in file_types_to_include):
                 _update_status(status_dict, message=f"Skipping hidden file: {file_path_full}")
                 continue

            if not file_types_to_include: 
                discovered_file_paths.append(file_path_full)
                current_file_count += 1
                _update_status(status_dict, message=f"Discovered file ({current_file_count}): {os.path.basename(file_path_full)}")
            else:
                _, ext = os.path.splitext(file_name)
                if ext.lower().strip() in file_types_to_include:
                    discovered_file_paths.append(file_path_full)
                    current_file_count += 1
                    _update_status(status_dict, message=f"Discovered file ({current_file_count}): {os.path.basename(file_path_full)}")

    _update_status(status_dict, message=f"Discovered {len(discovered_file_paths)} files in '{directory_path}' after filtering.", processed_files_count=len(discovered_file_paths))
    return discovered_file_paths

def process_repository_content(
    input_type: str,
    source_location: str,
    file_types_str: str,
    exclude_folders_str: str,
    tutor_id: str,
    embed_repo_flag: bool,
    repo_overview: str, 
    additional_info_list: List[Dict[str, str]], 
    status_dict: Optional[Dict[str, Any]]
) -> Tuple[int, str]: 
    """
    Processes repository content either from a local folder or by cloning a Git URL.
    If embed_repo_flag is True, also triggers embedding.
    Updates status_dict with progress.
    """
    discovered_files_count = 0
    final_processing_message = ""
    discovered_file_paths: List[str] = []

    if status_dict is None: # Should not happen if called from app.py's background thread
        status_dict = {} 

    if input_type == 'folder':
        if not os.path.isdir(source_location):
            err_msg = f"Error: Folder path does not exist: {source_location}"
            _update_status(status_dict, error=err_msg) # This sets status to FAILED
            # No need to raise here, the error in status_dict will halt further processing in app.py
            return 0, err_msg 

        _update_status(status_dict, message=f"Processing local folder: {source_location}", status="PROCESSING_FILES")
        discovered_file_paths = _process_files_in_directory(source_location, file_types_str, exclude_folders_str, tutor_id, status_dict, is_local_folder_walk=True)
        discovered_files_count = len(discovered_file_paths)
        final_processing_message = "Local folder file discovery complete."
        _update_status(status_dict, message=final_processing_message, processed_files_count=discovered_files_count)


    elif input_type == 'url':
        temp_clone_dir = f"temp_repo_clone_{tutor_id.replace('-', '_')}"

        if os.path.exists(temp_clone_dir):
            _update_status(status_dict, message=f"Cleaning up pre-existing temporary directory: {temp_clone_dir}")
            try:
                shutil.rmtree(temp_clone_dir)
            except Exception as e_rm_old:
                 _update_status(status_dict, message=f"Warning: Could not remove old temp dir {temp_clone_dir}: {e_rm_old}")

        try:
            os.makedirs(temp_clone_dir, exist_ok=True)
            _update_status(status_dict, message=f"Cloning repository: {source_location} into {temp_clone_dir}...", status="CLONING_REPO")
            repo = git.Repo.clone_from(source_location, temp_clone_dir, depth=1) 
            _update_status(status_dict, message="Repository cloned successfully. Checking out HEAD...")

            try:
                repo.git.checkout('HEAD') 
                _update_status(status_dict, message=f"Checked out HEAD. Processing cloned files in {temp_clone_dir}...", status="PROCESSING_FILES")
            except git.exc.GitCommandError as e_checkout:
                _update_status(status_dict, message=f"Warning: Could not explicitly checkout HEAD: {e_checkout}. Proceeding with current state.", error=str(e_checkout))
            except Exception as e_general_checkout: 
                _update_status(status_dict, message=f"Warning: An unexpected error during checkout: {e_general_checkout}. Proceeding...", error=str(e_general_checkout))
            
            if status_dict.get("error"): # If checkout failed critically
                return 0, status_dict.get("message", "Checkout failed")

            discovered_file_paths = _process_files_in_directory(temp_clone_dir, file_types_str, exclude_folders_str, tutor_id, status_dict, is_local_folder_walk=False)
            discovered_files_count = len(discovered_file_paths)
            final_processing_message = "Repository cloned and file discovery complete."
            _update_status(status_dict, message=final_processing_message, processed_files_count=discovered_files_count)


        except git.exc.GitCommandError as e_clone:
            error_details = e_clone.stderr if hasattr(e_clone, 'stderr') and e_clone.stderr else str(e_clone)
            _update_status(status_dict, error=f"Git clone failed: {error_details}")
            return 0, f"Git clone failed: {error_details}"
        except Exception as e_process: 
            _update_status(status_dict, error=f"Error processing cloned repository: {str(e_process)}")
            return 0, f"An unexpected error occurred during repository processing setup: {str(e_process)}"
        finally:
            if os.path.exists(temp_clone_dir):
                _update_status(status_dict, message=f"Cleaning up temporary directory: {temp_clone_dir}...")
                try:
                    if os.name == 'nt':
                        git_dir_path = os.path.join(temp_clone_dir, '.git')
                        if os.path.exists(git_dir_path):
                            for root_git, dirs_git, files_git in os.walk(git_dir_path):
                                for name_git in dirs_git + files_git:
                                    try:
                                        os.chmod(os.path.join(root_git, name_git), 0o777) 
                                    except Exception:
                                        pass 
                    shutil.rmtree(temp_clone_dir)
                    _update_status(status_dict, message=f"Successfully removed {temp_clone_dir}")
                except PermissionError as e_perm: 
                    _update_status(status_dict, message=f"PermissionError removing {temp_clone_dir}: {e_perm}. Manual cleanup might be needed.", error=str(e_perm))
                except Exception as e_rm:
                    _update_status(status_dict, message=f"Error removing {temp_clone_dir}: {e_rm}", error=str(e_rm))
    else:
        err_msg_input_type = f"Invalid input_type for processing: {input_type}"
        _update_status(status_dict, error=err_msg_input_type)
        return 0, err_msg_input_type

    if status_dict.get("error"): # If file discovery failed
        return discovered_files_count, status_dict.get("message", "File discovery failed.")

    if embed_repo_flag: 
        _update_status(status_dict, message=f"Starting embedding process for {discovered_files_count} files, repo overview, and additional info...", status="PROCESSING_EMBEDDING")
        try:
            embed_documents_for_tutor(
                tutor_id=tutor_id,
                file_paths=discovered_file_paths,
                repo_overview=repo_overview,
                additional_info_list=additional_info_list,
                status_dict=status_dict 
            )
            # embed_documents_for_tutor will set its own final message and status ("COMPLETED_EMBEDDING_STEP" or "FAILED")
            final_processing_message = status_dict.get("message", "Embedding process finished.") 
        except Exception as e_embed:
            err_msg_embed = f"Critical error during embedding process initiation: {e_embed}"
            _update_status(status_dict, error=err_msg_embed)
            final_processing_message = err_msg_embed
    
    if status_dict.get("error"): # Check if embedding itself failed
         return discovered_files_count, status_dict.get("message", "Embedding failed.")

    # If embed_repo_flag was false, or if embedding step completed without setting its own error.
    # This final message is for the overall "process_repository_content" step.
    # The actual "COMPLETED" status for the whole job is set in app.py's _perform_long_repository_processing
    if not status_dict.get("error"):
        if embed_repo_flag:
            # Message already set by embed_documents_for_tutor or error handling above
            pass
        else: # Embedding was skipped
            final_processing_message = "File discovery complete. Embedding skipped."
            _update_status(status_dict, message=final_processing_message, status="COMPLETED_NO_EMBEDDING")


    return discovered_files_count, final_processing_message
