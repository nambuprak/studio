
import os
import shutil
import git # For Git operations
import pathspec # For .gitignore processing

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
    return pathspec.PathSpec.from_lines('gitwildmatch', patterns)

def _process_files_in_directory(directory_path: str, file_types_str: str, exclude_folders_str: str, is_local_folder_walk: bool = False) -> int:
    """
    Walks through a directory, counts files matching criteria.
    If is_local_folder_walk is True, it will also try to respect .gitignore rules.
    """
    processed_files_count = 0
    # Ensure file types start with a dot and are not empty, and trim spaces
    file_types_to_include = [ft.strip() for ft in file_types_str.split(',') if ft.strip() and ft.strip().startswith('.')]
    # Ensure excluded folders are stripped of whitespace
    folders_to_exclude_set = {fd.strip() for fd in exclude_folders_str.split(',') if fd.strip()}

    print(f"Processing directory: {directory_path}")
    print(f"Including file types: {file_types_to_include}")
    print(f"Excluding folders (from input): {folders_to_exclude_set}")

    gitignore_spec = None
    if is_local_folder_walk: # Only apply .gitignore for local folder walks, not for cloned repos
        gitignore_spec = _read_gitignore(directory_path)
        if gitignore_spec:
             print(f"Applying .gitignore rules from {directory_path}/.gitignore")


    for root, dirs, files in os.walk(directory_path, topdown=True):
        # --- Directory Exclusion Logic ---
        original_dirs_count = len(dirs)
        
        # Filter dirs in place (iterate over a copy for safe modification)
        dirs_to_remove = set()
        for d_name in list(dirs): # Iterate over a copy
            dir_path_full = os.path.join(root, d_name)
            dir_path_relative_to_walk_root = os.path.relpath(dir_path_full, directory_path)
            
            # 1. Exclude based on user's `exclude_folders_str` (applies to directory names only)
            if d_name in folders_to_exclude_set:
                dirs_to_remove.add(d_name)
                # print(f"Excluding dir (user list): {dir_path_relative_to_walk_root}")
                continue
            
            # 2. Exclude hidden directories (like .git, .vscode)
            if d_name.startswith('.'): 
                dirs_to_remove.add(d_name)
                # print(f"Excluding dir (hidden): {dir_path_relative_to_walk_root}")
                continue
            
            # 3. If local folder walk, exclude based on .gitignore patterns (applies to relative paths from root of walk)
            if gitignore_spec and gitignore_spec.match_file(dir_path_relative_to_walk_root + '/'): # Add trailing slash for directories
                dirs_to_remove.add(d_name)
                # print(f"Excluding dir (.gitignore): {dir_path_relative_to_walk_root}")
                continue
        
        dirs[:] = [d for d in dirs if d not in dirs_to_remove]
        
        # if original_dirs_count != len(dirs):
        # print(f"Dirs before filtering in '{root}': {original_dirs_count}, after: {len(dirs)}. Kept: {dirs}")


        # --- File Processing & Exclusion ---
        for file_name in files:
            file_path_full = os.path.join(root, file_name)
            file_path_relative_to_walk_root = os.path.relpath(file_path_full, directory_path)

            # 1. Exclude based on .gitignore (if applicable for local walks)
            if gitignore_spec and gitignore_spec.match_file(file_path_relative_to_walk_root):
                # print(f"Skipping file (.gitignore): {file_path_relative_to_walk_root}")
                continue
            
            # 2. Exclude hidden files (unless explicitly included by file_types_str, which is unlikely for hidden files)
            if file_name.startswith('.') and not any(file_name.endswith(ft) for ft in file_types_to_include):
                # print(f"Skipping file (hidden and not in include list): {file_path_relative_to_walk_root}")
                continue

            # 3. Include based on file_types_to_include
            if not file_types_to_include: # If no types specified, include all (after .gitignore filtering)
                processed_files_count += 1
                # print(f"Processing file (all types): {file_path_full}")
            else:
                _, ext = os.path.splitext(file_name)
                if ext in file_types_to_include:
                    processed_files_count += 1
                    # print(f"Processing file (filtered type): {file_path_full}")
    
    print(f"Discovered {processed_files_count} files in {directory_path} after filtering.")
    return processed_files_count

def process_repository_content(input_type: str, source_location: str, 
                               file_types_str: str, exclude_folders_str: str, 
                               tutor_id: str) -> tuple[int, str]:
    """
    Processes repository content either from a local folder or by cloning a Git URL.
    Returns (discovered_files_count, message).
    Raises exceptions on failure.
    """
    discovered_files_count = 0
    processing_message = ""

    if input_type == 'folder':
        if not os.path.isdir(source_location):
            raise ValueError(f"Provided folder path does not exist or is not a directory: {source_location}")
        
        print(f"Processing local folder: {source_location}")
        discovered_files_count = _process_files_in_directory(source_location, file_types_str, exclude_folders_str, is_local_folder_walk=True)
        processing_message = "Self Tutor configuration saved and local folder processed."

    elif input_type == 'url':
        # Use a unique temporary directory for cloning, relative to the script's location or a defined temp area
        # For simplicity, creating it in the current working directory of the Flask app (server folder)
        temp_clone_dir = f"temp_repo_clone_{tutor_id}" 
        
        # Ensure the temp_clone_dir is an absolute path or a well-defined relative path
        # If server/app.py is run from the project root, this will be project_root/temp_repo_clone_id
        # If server/app.py is run from server/, this will be server/temp_repo_clone_id
        # For more robustness, one might use tempfile.mkdtemp()
        
        if os.path.exists(temp_clone_dir):
            print(f"Cleaning up pre-existing temporary directory: {temp_clone_dir}")
            shutil.rmtree(temp_clone_dir)
        os.makedirs(temp_clone_dir, exist_ok=True)
        
        try:
            print(f"Cloning repository: {source_location} into {temp_clone_dir}")
            git.Repo.clone_from(source_location, temp_clone_dir) 
            print("Repository cloned successfully.")
            
            # Process the cloned directory. .gitignore rules are implicitly handled by `git clone`.
            # `is_local_folder_walk` is False because we are not reading a .gitignore from the cloned repo's root again.
            # The `exclude_folders_str` and `file_types_str` from user input will apply to the cloned content.
            discovered_files_count = _process_files_in_directory(temp_clone_dir, file_types_str, exclude_folders_str, is_local_folder_walk=False)
            processing_message = "Self Tutor configuration saved and repository processed."

        except git.exc.GitCommandError as e:
            print(f"Git cloning error: {e}")
            error_details = e.stderr if hasattr(e, 'stderr') and e.stderr else str(e)
            raise Exception(f"Failed to clone repository: {error_details}")
        except Exception as e:
            print(f"Error processing cloned repository: {e}")
            raise Exception(f"An unexpected error occurred during repository processing: {str(e)}")
        finally:
            if os.path.exists(temp_clone_dir):
                print(f"Cleaning up temporary directory: {temp_clone_dir}")
                try:
                    shutil.rmtree(temp_clone_dir)
                    print(f"Successfully removed {temp_clone_dir}")
                except Exception as e_rm:
                    print(f"Error removing temporary directory {temp_clone_dir}: {e_rm}")
            else:
                print(f"Temporary directory {temp_clone_dir} not found for cleanup (might have failed before creation).")
    else:
        raise ValueError(f"Invalid input_type for processing: {input_type}")
        
    return discovered_files_count, processing_message
