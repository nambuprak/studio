
import os
import shutil
import git # For Git operations

def _process_files_in_directory(directory_path: str, file_types_str: str, exclude_folders_str: str) -> int:
    """
    Walks through a directory, counts files matching criteria.
    This is a simplified version; actual content processing would happen here.
    """
    processed_files_count = 0
    file_types_to_include = [ft.strip() for ft in file_types_str.split(',') if ft.strip() and ft.startswith('.')]
    folders_to_exclude = {fd.strip() for fd in exclude_folders_str.split(',') if fd.strip()}

    print(f"Processing directory: {directory_path}")
    print(f"Including file types: {file_types_to_include}")
    print(f"Excluding folders: {folders_to_exclude}")
    
    for root, dirs, files in os.walk(directory_path, topdown=True):
        # Filter out excluded directories
        dirs[:] = [d for d in dirs if d not in folders_to_exclude and not d.startswith('.')] # also exclude hidden folders by default

        for file_name in files:
            if not file_types_to_include: # If no types specified, include all
                processed_files_count += 1
                # print(f"Processing file (all types): {os.path.join(root, file_name)}")
            else:
                _, ext = os.path.splitext(file_name)
                if ext in file_types_to_include:
                    processed_files_count += 1
                    # print(f"Processing file (filtered type): {os.path.join(root, file_name)}")
    
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
        discovered_files_count = _process_files_in_directory(source_location, file_types_str, exclude_folders_str)
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
            git.Repo.clone_from(source_location, temp_clone_dir)
            print("Repository cloned successfully.")
            
            discovered_files_count = _process_files_in_directory(temp_clone_dir, file_types_str, exclude_folders_str)
            processing_message = "Self Tutor configuration saved and repository processed."

        except git.exc.GitCommandError as e:
            print(f"Git cloning error: {e}")
            raise Exception(f"Failed to clone repository: {e.stderr}")
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
                print(f"Temporary directory {temp_clone_dir} not found for cleanup.")
    else:
        raise ValueError(f"Invalid input_type for processing: {input_type}")
        
    return discovered_files_count, processing_message

    