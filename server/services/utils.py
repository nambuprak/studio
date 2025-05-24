
import os
from urllib.parse import urlparse

def extract_project_name_from_url(repo_url: str) -> str:
    """Extracts project name from a Git repository URL."""
    try:
        path = urlparse(repo_url).path
        # Remove .git suffix if present, then get basename
        name_with_ext = os.path.basename(path.removesuffix('.git'))
        project_name = name_with_ext 
        return project_name if project_name else "untitled_project_from_url"
    except Exception:
        return "untitled_project_from_url"

def extract_project_name_from_path(folder_path: str) -> str:
    """Extracts project name from a local folder path (basename)."""
    try:
        project_name = os.path.basename(os.path.normpath(folder_path)) # Normalize to handle trailing slashes
        return project_name if project_name else "untitled_project_from_folder"
    except Exception:
        return "untitled_project_from_folder"

    