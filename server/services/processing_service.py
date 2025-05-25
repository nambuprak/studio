
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
    # Add common .git directory pattern to ensure it's always ignored if not explicitly un-ignored
    # This is important because pathspec matches against relative paths from the .gitignore location
    if ".git/" not in patterns and ".git" not in patterns :
        patterns.append(".git/") # Ensure .git folder itself is ignored
    return pathspec.PathSpec.from_lines('gitwildmatch', patterns)

def _update_status(status_dict: Optional[Dict[str, Any]], message: str, processed_files_count: Optional[int] = None, total_files_estimate: Optional[int] = None, error: Optional[str] = None):
    if status_dict:
        tutor_id_log = status_dict.get('tutor_id', 'N/A')
        if message:
            status_dict["message"] = message
            # Prepend tutor ID to print statements for clarity if multiple tasks run
            print(f"Status Update (TutorID: {tutor_id_log}): {message}")
        if processed_files_count is not None:
            status_dict["discovered_files_count"] = processed_files_count
        if total_files_estimate is not None:
            status_dict["total_files_estimate"] = total_files_estimate
        if error:
            status_dict["error"] = error
            print(f"Error Update (TutorID: {tutor_id_log}): {error}")


def _process_files_in_directory(
    directory_path: str,
    file_types_str: str,
    exclude_folders_str: str,
    tutor_id: str, # For logging/status context
    status_dict: Optional[Dict[str, Any]],
    is_local_folder_walk: bool = False # True if walking a user-provided local folder
) -> List[str]: # Returns list of absolute file paths
    """
    Walks through a directory, collects absolute paths of files matching criteria.
    If is_local_folder_walk is True, it will also try to respect .gitignore rules.
    Updates status_dict with progress. Returns list of absolute file paths.
    """
    discovered_file_paths: List[str] = []

    # Prepare file types: trim spaces, ensure they start with '.'
    file_types_to_include = [ft.strip() for ft in file_types_str.split(',') if ft.strip()]
    file_types_to_include = [ft if ft.startswith('.') else '.' + ft for ft in file_types_to_include if ft]

    # Prepare excluded folders: trim spaces
    folders_to_exclude_set = {fd.strip() for fd in exclude_folders_str.split(',') if fd.strip()}

    _update_status(status_dict, f"Starting file scan in: {directory_path}. Including: {file_types_to_include or 'all'}. Excluding folders: {folders_to_exclude_set or 'none'}.")

    gitignore_spec: Optional[pathspec.PathSpec] = None
    if is_local_folder_walk: # Only apply .gitignore for direct local folder walks
        gitignore_spec = _read_gitignore(directory_path)
        if gitignore_spec and gitignore_spec.patterns:
             _update_status(status_dict, f"Applying .gitignore rules from {os.path.join(directory_path, '.gitignore')}")

    current_file_count = 0
    for root, dirs, files in os.walk(directory_path, topdown=True):
        # For .gitignore compatibility, we need paths relative to the directory_path (where .gitignore is)
        # Modify dirs in-place to exclude based on user list and .gitignore
        original_dirs_copy = list(dirs) # Iterate over a copy
        dirs[:] = [] # Clear original dirs list to rebuild it

        for d_name in original_dirs_copy:
            dir_path_full = os.path.join(root, d_name)
            # Path relative to the directory_path (walk root) for .gitignore matching
            dir_path_relative_to_walk_root = os.path.relpath(dir_path_full, directory_path)

            if d_name in folders_to_exclude_set:
                _update_status(status_dict, f"Excluding folder by user rule: {dir_path_full}")
                continue
            
            if d_name.startswith('.'): # Typically exclude hidden directories like .idea, .vscode unless specified
                if d_name != ".git": # .git is handled by gitignore spec if present
                    _update_status(status_dict, f"Skipping hidden directory: {dir_path_full}")
                    continue
            
            # Check against .gitignore if applicable and spec is loaded
            # pathspec expects paths with a trailing slash for directories
            if gitignore_spec and gitignore_spec.match_file(dir_path_relative_to_walk_root + '/'):
                _update_status(status_dict, f"Excluding folder by .gitignore: {dir_path_full}")
                continue
            
            dirs.append(d_name) # Add directory back if not excluded

        for file_name in files:
            file_path_full = os.path.join(root, file_name)
            file_path_relative_to_walk_root = os.path.relpath(file_path_full, directory_path)

            if gitignore_spec and gitignore_spec.match_file(file_path_relative_to_walk_root):
                _update_status(status_dict, f"Excluding file by .gitignore: {file_path_full}")
                continue

            # Skip hidden files unless their extension is explicitly included
            if file_name.startswith('.') and not any(file_name.endswith(ft) for ft in file_types_to_include):
                 _update_status(status_dict, f"Skipping hidden file: {file_path_full}")
                 continue

            if not file_types_to_include: # If no specific types, include all non-excluded
                discovered_file_paths.append(file_path_full)
                current_file_count += 1
                _update_status(status_dict, f"Discovered file ({current_file_count}): {os.path.basename(file_path_full)}")
            else:
                _, ext = os.path.splitext(file_name)
                if ext.lower().strip() in file_types_to_include:
                    discovered_file_paths.append(file_path_full)
                    current_file_count += 1
                    _update_status(status_dict, f"Discovered file ({current_file_count}): {os.path.basename(file_path_full)}")
                # else:
                #     _update_status(status_dict, f"Skipping file by type: {file_path_full} (ext: {ext.lower().strip()})")


    _update_status(status_dict, message=f"Discovered {len(discovered_file_paths)} files in '{directory_path}' after filtering.", processed_files_count=len(discovered_file_paths))
    return discovered_file_paths

def process_repository_content(
    input_type: str,
    source_location: str,
    file_types_str: str,
    exclude_folders_str: str,
    tutor_id: str,
    embed_repo_flag: bool,
    repo_overview: str, # Text of repository overview
    additional_info_list: List[Dict[str, str]], # List of {'title': '...', 'description': '...'}
    status_dict: Optional[Dict[str, Any]]
) -> Tuple[int, str]: # Returns (discovered_files_count, message)
    """
    Processes repository content either from a local folder or by cloning a Git URL.
    If embed_repo_flag is True, also triggers embedding.
    Updates status_dict with progress.
    """
    discovered_files_count = 0
    final_processing_message = ""
    discovered_file_paths: List[str] = []

    if input_type == 'folder':
        if not os.path.isdir(source_location):
            err_msg = f"Error: Folder path does not exist: {source_location}"
            _update_status(status_dict, err_msg, error="Folder path invalid")
            raise ValueError(err_msg)

        _update_status(status_dict, f"Processing local folder: {source_location}")
        discovered_file_paths = _process_files_in_directory(source_location, file_types_str, exclude_folders_str, tutor_id, status_dict, is_local_folder_walk=True)
        discovered_files_count = len(discovered_file_paths)
        final_processing_message = "Local folder file discovery complete."

    elif input_type == 'url':
        # Create a unique temporary directory for cloning this specific tutor's repo
        temp_clone_dir = f"temp_repo_clone_{tutor_id.replace('-', '_')}"

        if os.path.exists(temp_clone_dir):
            _update_status(status_dict, f"Cleaning up pre-existing temporary directory: {temp_clone_dir}")
            try:
                shutil.rmtree(temp_clone_dir)
            except Exception as e_rm_old:
                 _update_status(status_dict, f"Warning: Could not remove old temp dir {temp_clone_dir}: {e_rm_old}")

        try:
            os.makedirs(temp_clone_dir, exist_ok=True)
            _update_status(status_dict, f"Cloning repository: {source_location} into {temp_clone_dir}...")
            repo = git.Repo.clone_from(source_location, temp_clone_dir, depth=1) # Shallow clone
            _update_status(status_dict, "Repository cloned successfully. Checking out HEAD...")

            try:
                repo.git.checkout('HEAD') # Ensure files are in the working directory
                _update_status(status_dict, f"Checked out HEAD. Processing cloned files in {temp_clone_dir}...")
            except git.exc.GitCommandError as e_checkout:
                _update_status(status_dict, f"Warning: Could not explicitly checkout HEAD: {e_checkout}. Proceeding with current state.", error=str(e_checkout))
            except Exception as e_general_checkout: # Catch other potential checkout errors
                _update_status(status_dict, f"Warning: An unexpected error during checkout: {e_general_checkout}. Proceeding...", error=str(e_general_checkout))

            # Process files within the cloned directory. .gitignore is inherently handled by git clone.
            discovered_file_paths = _process_files_in_directory(temp_clone_dir, file_types_str, exclude_folders_str, tutor_id, status_dict, is_local_folder_walk=False)
            discovered_files_count = len(discovered_file_paths)
            final_processing_message = "Repository cloned and file discovery complete."

        except git.exc.GitCommandError as e_clone:
            error_details = e_clone.stderr if hasattr(e_clone, 'stderr') and e_clone.stderr else str(e_clone)
            _update_status(status_dict, f"Git cloning error: {error_details}", error=f"Git clone failed: {error_details}")
            raise Exception(f"Failed to clone repository: {error_details}")
        except Exception as e_process: # Catch other errors during setup
            _update_status(status_dict, f"Error processing cloned repository: {str(e_process)}", error=str(e_process))
            raise Exception(f"An unexpected error occurred during repository processing setup: {str(e_process)}")
        finally:
            if os.path.exists(temp_clone_dir):
                _update_status(status_dict, f"Cleaning up temporary directory: {temp_clone_dir}...")
                try:
                    # Attempt to fix PermissionError on Windows for .git folder
                    if os.name == 'nt':
                        git_dir_path = os.path.join(temp_clone_dir, '.git')
                        if os.path.exists(git_dir_path):
                            for root_git, dirs_git, files_git in os.walk(git_dir_path):
                                for name_git in dirs_git + files_git:
                                    try:
                                        os.chmod(os.path.join(root_git, name_git), 0o777) # Set to read/write/execute for all
                                    except Exception:
                                        pass # Ignore errors during chmod, rmtree will try anyway
                    shutil.rmtree(temp_clone_dir)
                    _update_status(status_dict, f"Successfully removed {temp_clone_dir}")
                except PermissionError as e_perm: # Specific handling for PermissionError
                    _update_status(status_dict, f"PermissionError removing {temp_clone_dir}: {e_perm}. Manual cleanup might be needed.", error=str(e_perm))
                except Exception as e_rm:
                    _update_status(status_dict, f"Error removing {temp_clone_dir}: {e_rm}", error=str(e_rm))
    else:
        err_msg_input_type = f"Invalid input_type for processing: {input_type}"
        _update_status(status_dict, err_msg_input_type, error="Invalid input type")
        raise ValueError(err_msg_input_type)

    # Proceed with embedding if the flag is set and files were discovered
    if embed_repo_flag: # No need to check discovered_file_paths here, embed_documents_for_tutor handles empty list
        _update_status(status_dict, message=f"Starting embedding process for {discovered_files_count} files, repo overview, and additional info...")
        try:
            embed_documents_for_tutor(
                tutor_id=tutor_id,
                file_paths=discovered_file_paths,
                repo_overview=repo_overview,
                additional_info_list=additional_info_list,
                status_dict=status_dict # Pass the status_dict for updates
            )
            # The final message "Document embedding process fully completed for this tutor." is set within embed_documents_for_tutor.
            # So, we don't override final_processing_message here unless embedding fails.
            final_processing_message = status_dict.get("message", "Embedding process completed.") if status_dict else "Embedding process completed."
        except Exception as e_embed:
            err_msg_embed = f"Error during embedding process: {e_embed}"
            _update_status(status_dict, message=err_msg_embed, error=str(e_embed))
            final_processing_message = err_msg_embed # Update message to reflect embedding failure
    # If embedding was not flagged, the initial final_processing_message from file discovery stands.
    # Or if embed_repo_flag was true but no files were found, embed_documents_for_tutor handles this.

    return discovered_files_count, final_processing_message

    