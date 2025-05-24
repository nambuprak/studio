
import os
import shutil
import git # For Git operations
import pathspec # For .gitignore processing
from typing import Dict, Any

def _read_gitignore(directory_path: str) -> pathspec.PathSpec:
    """Reads .gitignore from the given directory and returns a PathSpec object."""
    gitignore_path = os.path.join(directory_path, ".gitignore")
    patterns = []
    if os.path.exists(gitignore_path):
        try:
            with open(gitignore_path, "r") as f:
                patterns = f.read().splitlines()
            print(f"Read {len(patterns)} patterns from .gitignore at {gitignore_path}")
        except Exception as e:
            print(f"Warning: Could not read .gitignore at {gitignore_path}: {e}")
    # Add common .git directory pattern to ensure it's always ignored if not explicitly un-ignored
    if ".git/" not in patterns and ".git" not in patterns :
        patterns.append(".git/")
    return pathspec.PathSpec.from_lines('gitwildmatch', patterns)

def _update_status(status_dict: Dict[str, Any], message: str, processed_files: int = None, total_files: int = None):
    if status_dict:
        status_dict["message"] = message
        if processed_files is not None:
            status_dict["processed_files_count"] = processed_files
        if total_files is not None:
            status_dict["total_files_count"] = total_files
        print(f"Status Update: {message}")


def _process_files_in_directory(
    directory_path: str, 
    file_types_str: str, 
    exclude_folders_str: str, 
    tutor_id: str, # For logging/status updates
    status_dict: Dict[str, Any], # For live status updates
    is_local_folder_walk: bool = False
) -> int:
    """
    Walks through a directory, counts files matching criteria.
    If is_local_folder_walk is True, it will also try to respect .gitignore rules.
    Updates status_dict with progress.
    """
    processed_files_count = 0
    # Ensure file types start with a dot and are not empty, and trim spaces
    file_types_to_include = [ft.strip() for ft in file_types_str.split(',') if ft.strip() and ft.strip().startswith('.')]
    # Ensure excluded folders are stripped of whitespace
    folders_to_exclude_set = {fd.strip() for fd in exclude_folders_str.split(',') if fd.strip()}

    _update_status(status_dict, f"Starting file scan in: {directory_path}. Including: {file_types_to_include or 'all'}. Excluding: {folders_to_exclude_set or 'none'}.")
    
    gitignore_spec = None
    if is_local_folder_walk: 
        gitignore_spec = _read_gitignore(directory_path)
        if gitignore_spec:
             _update_status(status_dict, f"Applying .gitignore rules from {directory_path}/.gitignore")

    # First pass: Count total potential files (optional, can be slow for large dirs)
    # For simplicity, we'll update count as we go.

    for root, dirs, files in os.walk(directory_path, topdown=True):
        # --- Directory Exclusion Logic ---
        dirs_to_remove = set()
        for d_name in list(dirs): 
            dir_path_full = os.path.join(root, d_name)
            dir_path_relative_to_walk_root = os.path.relpath(dir_path_full, directory_path)
            
            if d_name in folders_to_exclude_set:
                dirs_to_remove.add(d_name)
                continue
            
            if d_name.startswith('.'): 
                dirs_to_remove.add(d_name)
                continue
            
            if gitignore_spec and gitignore_spec.match_file(dir_path_relative_to_walk_root + '/'): 
                dirs_to_remove.add(d_name)
                continue
        
        dirs[:] = [d for d in dirs if d not in dirs_to_remove]
        
        for file_name in files:
            file_path_full = os.path.join(root, file_name)
            file_path_relative_to_walk_root = os.path.relpath(file_path_full, directory_path)

            if gitignore_spec and gitignore_spec.match_file(file_path_relative_to_walk_root):
                continue
            
            if file_name.startswith('.') and not any(file_name.endswith(ft) for ft in file_types_to_include):
                continue

            if not file_types_to_include: 
                processed_files_count += 1
                _update_status(status_dict, f"Processing file ({processed_files_count}): {file_path_relative_to_walk_root}", processed_files=processed_files_count)
            else:
                _, ext = os.path.splitext(file_name)
                if ext.strip() in file_types_to_include: 
                    processed_files_count += 1
                    _update_status(status_dict, f"Processing file ({processed_files_count}): {file_path_relative_to_walk_root}", processed_files=processed_files_count)
    
    _update_status(status_dict, f"Discovered {processed_files_count} files in {directory_path} after filtering.", processed_files=processed_files_count)
    return processed_files_count

def process_repository_content(
    input_type: str, 
    source_location: str, 
    file_types_str: str, 
    exclude_folders_str: str, 
    tutor_id: str,
    status_dict: Dict[str, Any] # For live status updates
) -> tuple[int, str]:
    """
    Processes repository content either from a local folder or by cloning a Git URL.
    Returns (discovered_files_count, message).
    Raises exceptions on failure.
    Updates status_dict with progress.
    """
    discovered_files_count = 0
    processing_message = ""

    if input_type == 'folder':
        if not os.path.isdir(source_location):
            _update_status(status_dict, f"Error: Folder path does not exist: {source_location}")
            raise ValueError(f"Provided folder path does not exist or is not a directory: {source_location}")
        
        _update_status(status_dict, f"Processing local folder: {source_location}")
        discovered_files_count = _process_files_in_directory(source_location, file_types_str, exclude_folders_str, tutor_id, status_dict, is_local_folder_walk=True)
        processing_message = "Local folder processed."

    elif input_type == 'url':
        temp_clone_dir = f"temp_repo_clone_{tutor_id}" 
        
        if os.path.exists(temp_clone_dir):
            _update_status(status_dict, f"Cleaning up pre-existing temporary directory: {temp_clone_dir}")
            shutil.rmtree(temp_clone_dir)
        os.makedirs(temp_clone_dir, exist_ok=True)
        
        repo = None
        try:
            _update_status(status_dict, f"Cloning repository: {source_location} into {temp_clone_dir}...")
            repo = git.Repo.clone_from(source_location, temp_clone_dir) 
            _update_status(status_dict, "Repository cloned successfully. Checking out HEAD...")

            try:
                repo.git.checkout('HEAD') 
                _update_status(status_dict, f"Checked out HEAD. Processing cloned files in {temp_clone_dir}...")
            except git.exc.GitCommandError as e_checkout:
                _update_status(status_dict, f"Warning: Could not explicitly checkout HEAD: {e_checkout}. Proceeding...")
            except Exception as e_general_checkout: 
                _update_status(status_dict, f"Warning: An unexpected error during checkout: {e_general_checkout}. Proceeding...")

            discovered_files_count = _process_files_in_directory(temp_clone_dir, file_types_str, exclude_folders_str, tutor_id, status_dict, is_local_folder_walk=False)
            processing_message = "Repository cloned and processed."

        except git.exc.GitCommandError as e_clone:
            error_details = e_clone.stderr if hasattr(e_clone, 'stderr') and e_clone.stderr else str(e_clone)
            _update_status(status_dict, f"Git cloning error: {error_details}")
            raise Exception(f"Failed to clone repository: {error_details}")
        except Exception as e_process:
            _update_status(status_dict, f"Error processing cloned repository: {str(e_process)}")
            raise Exception(f"An unexpected error occurred during repository processing: {str(e_process)}")
        finally:
            if os.path.exists(temp_clone_dir):
                _update_status(status_dict, f"Cleaning up temporary directory: {temp_clone_dir}...")
                try:
                    if os.name == 'nt':
                        for root_git, dirs_git, files_git in os.walk(temp_clone_dir):
                            for d_name_git in dirs_git:
                                if d_name_git == '.git':
                                    git_dir_path = os.path.join(root_git, d_name_git)
                                    for dirpath_perm, _, filenames_perm in os.walk(git_dir_path):
                                        for filename_perm in filenames_perm:
                                            filepath_perm = os.path.join(dirpath_perm, filename_perm)
                                            try:
                                                os.chmod(filepath_perm, 0o777) 
                                            except Exception as e_chmod:
                                                print(f"Could not change permissions for {filepath_perm}: {e_chmod}") # Log quietly
                    shutil.rmtree(temp_clone_dir)
                    _update_status(status_dict, f"Successfully removed {temp_clone_dir}")
                except PermissionError as e_perm: 
                    print(f"PermissionError removing {temp_clone_dir}: {e_perm}.") # Log more visibly
                    _update_status(status_dict, f"PermissionError removing {temp_clone_dir}: {e_perm}. Manual cleanup might be needed.")
                except Exception as e_rm:
                    print(f"Error removing {temp_clone_dir}: {e_rm}")
                    _update_status(status_dict, f"Error removing {temp_clone_dir}: {e_rm}")
            else:
                _update_status(status_dict, f"Temporary directory {temp_clone_dir} not found for cleanup.")
    else:
        _update_status(status_dict, f"Invalid input_type for processing: {input_type}")
        raise ValueError(f"Invalid input_type for processing: {input_type}")
        
    return discovered_files_count, processing_message
