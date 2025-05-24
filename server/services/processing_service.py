
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
    # Add common virtual environment folders and IDE folders by default,
    # as .gitignore might not always list them if it's in a parent directory
    # or if it's a global gitignore.
    # However, explicit exclude_folders_str from user input takes precedence.
    # For this POC, we'll rely on user input for these common ones.
    return pathspec.PathSpec.from_lines('gitwildmatch', patterns)

def _process_files_in_directory(directory_path: str, file_types_str: str, exclude_folders_str: str, is_local_folder_walk: bool = False) -> int:
    """
    Walks through a directory, counts files matching criteria.
    If is_local_folder_walk is True, it will also try to respect .gitignore rules.
    """
    processed_files_count = 0
    # Ensure file types start with a dot and are not empty
    file_types_to_include = [ft.strip() for ft in file_types_str.split(',') if ft.strip() and ft.startswith('.')]
    # Ensure excluded folders are stripped of whitespace
    folders_to_exclude_set = {fd.strip() for fd in exclude_folders_str.split(',') if fd.strip()}

    print(f"Processing directory: {directory_path}")
    print(f"Including file types: {file_types_to_include}")
    print(f"Excluding folders (from input): {folders_to_exclude_set}")

    gitignore_spec = None
    if is_local_folder_walk:
        gitignore_spec = _read_gitignore(directory_path)
        if gitignore_spec:
             print(f"Applying .gitignore rules from {directory_path}/.gitignore")


    for root, dirs, files in os.walk(directory_path, topdown=True):
        # --- Directory Exclusion ---
        # 1. Exclude based on user's `exclude_folders_str` (applies to directory names only)
        # 2. Exclude hidden directories (like .git, .vscode)
        # 3. If local folder walk, exclude based on .gitignore patterns (applies to relative paths from root of walk)

        original_dirs_count = len(dirs)
        
        # Filter dirs in place
        dirs_to_remove = set()
        for d in dirs:
            dir_path_relative_to_walk_root = os.path.relpath(os.path.join(root, d), directory_path)
            
            if d in folders_to_exclude_set: # From user input
                dirs_to_remove.add(d)
                # print(f"Excluding dir (user list): {dir_path_relative_to_walk_root}")
                continue
            if d.startswith('.'): # Hidden folder
                dirs_to_remove.add(d)
                # print(f"Excluding dir (hidden): {dir_path_relative_to_walk_root}")
                continue
            if gitignore_spec and gitignore_spec.match_file(dir_path_relative_to_walk_root):
                dirs_to_remove.add(d)
                # print(f"Excluding dir (.gitignore): {dir_path_relative_to_walk_root}")
                continue
        
        dirs[:] = [d for d in dirs if d not in dirs_to_remove]
        
        # if original_dirs_count != len(dirs):
        # print(f"Dirs before filtering in '{root}': {original_dirs_count}, after: {len(dirs)}. Kept: {dirs}")


        # --- File Processing & Exclusion ---
        for file_name in files:
            file_path_full = os.path.join(root, file_name)
            file_path_relative_to_walk_root = os.path.relpath(file_path_full, directory_path)

            # 1. Exclude based on .gitignore (if applicable)
            if gitignore_spec and gitignore_spec.match_file(file_path_relative_to_walk_root):
                # print(f"Skipping file (.gitignore): {file_path_relative_to_walk_root}")
                continue
            
            # 2. Exclude hidden files (unless explicitly included by file_types_str, which is unlikely for hidden files)
            # This is a basic check; .gitignore is more robust for hidden files that are part of the project.
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
        # For local folder, pass is_local_folder_walk=True to enable .gitignore processing
        discovered_files_count = _process_files_in_directory(source_location, file_types_str, exclude_folders_str, is_local_folder_walk=True)
        processing_message = "Self Tutor configuration saved and local folder processed."

    elif input_type == 'url':
        # Use a unique temporary directory for cloning
        temp_clone_dir = f"temp_repo_clone_{tutor_id}" 
        
        if os.path.exists(temp_clone_dir):
            print(f"Cleaning up pre-existing temporary directory: {temp_clone_dir}")
            shutil.rmtree(temp_clone_dir)
        os.makedirs(temp_clone_dir, exist_ok=True)
        
        try:
            print(f"Cloning repository: {source_location} into {temp_clone_dir}")
            # Add depth=1 for faster clone if full history isn't needed for processing
            # For POC, full clone is fine. For production, consider shallow clone if applicable.
            git.Repo.clone_from(source_location, temp_clone_dir) 
            print("Repository cloned successfully.")
            
            # For cloned repo, .gitignore rules are inherently handled by git itself (files not tracked won't be cloned)
            # So, is_local_folder_walk can be False or we can rely on the cloned structure.
            # The exclude_folders_str still applies to the *cloned* content.
            discovered_files_count = _process_files_in_directory(temp_clone_dir, file_types_str, exclude_folders_str, is_local_folder_walk=False)
            processing_message = "Self Tutor configuration saved and repository processed."

        except git.exc.GitCommandError as e:
            print(f"Git cloning error: {e}")
            # It's helpful to include e.stderr if available, as it often contains the specific git error message
            error_details = e.stderr if hasattr(e, 'stderr') and e.stderr else str(e)
            raise Exception(f"Failed to clone repository: {error_details}")
        except Exception as e:
            print(f"Error processing cloned repository: {e}")
            raise Exception(f"An unexpected error occurred during repository processing: {str(e)}")
        finally:
            if os.path.exists(temp_clone_dir):
                print(f"Cleaning up temporary directory: {temp_clone_dir}")
                try:
                    # On Windows, rmtree can sometimes fail if files are locked.
                    # Adding a robust retry or specific error handling for Windows might be needed in production.
                    shutil.rmtree(temp_clone_dir)
                    print(f"Successfully removed {temp_clone_dir}")
                except Exception as e_rm:
                    print(f"Error removing temporary directory {temp_clone_dir}: {e_rm}")
                    # Optionally, re-raise or log this more severely as it can lead to disk space issues.
            else:
                print(f"Temporary directory {temp_clone_dir} not found for cleanup (might have failed before creation).")
    else:
        raise ValueError(f"Invalid input_type for processing: {input_type}")
        
    return discovered_files_count, processing_message
