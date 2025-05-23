
from flask import Flask, jsonify, request
from flask_cors import CORS
import git # For Git operations
import os # For file system operations like walking directories
import shutil # For removing directories

app = Flask(__name__)
CORS(app)  # This will enable CORS for all routes

# Mock data for repositories - replace with your actual data fetching logic
mock_repositories = [
    {"id": "repo-alpha-from-api", "name": "Repo Alpha (API)"},
    {"id": "repo-beta-from-api", "name": "Repo Beta (API)"},
    {"id": "repo-gamma-from-api", "name": "Repo Gamma (API)"},
    {"id": "repo-delta-from-api", "name": "Repo Delta (API)"},
    {"id": "repo-epsilon-from-api", "name": "Repo Epsilon (API)"},
]

@app.route('/api/repos', methods=['GET'])
def get_repos():
    return jsonify(mock_repositories)

@app.route('/api/analyze-repo', methods=['POST'])
def analyze_repo():
    data = request.json
    repo_url = data.get('repo_url')
    repo_overview = data.get('repo_overview')
    tap_bap = data.get('tap_bap')
    file_types_str = data.get('file_types', '') # e.g., ".ts,.tsx,.md"
    exclude_folders_str = data.get('exclude_folders', '') # e.g., "node_modules,.git"
    additional_info_list = data.get('additional_info_list', [])

    if not repo_url:
        return jsonify({"error": "Repository URL is required"}), 400

    # Define a temporary directory path relative to where app.py is run
    # You might want to make this path more robust or use system temp directories
    temp_clone_dir = "temp_repo_clone" 
    
    try:
        # 0. Clean up pre-existing temp directory if it exists (e.g., from a previous failed run)
        if os.path.exists(temp_clone_dir):
            print(f"Cleaning up pre-existing temporary directory: {temp_clone_dir}")
            shutil.rmtree(temp_clone_dir)
        os.makedirs(temp_clone_dir, exist_ok=True) # Create the temp directory

        # 1. Clone the repository using GitPython
        print(f"Cloning repository: {repo_url} into {temp_clone_dir}")
        git.Repo.clone_from(repo_url, temp_clone_dir)
        print("Repository cloned successfully.")

        # 2. Recursively list files, applying filters
        processed_files = []
        file_types_to_include = [ft.strip() for ft in file_types_str.split(',') if ft.strip()]
        folders_to_exclude = {fd.strip() for fd in exclude_folders_str.split(',') if fd.strip()}
        
        print(f"Including file types: {file_types_to_include}")
        print(f"Excluding folders: {folders_to_exclude}")

        for root, dirs, files in os.walk(temp_clone_dir, topdown=True):
            # Filter directories to exclude
            # Modify 'dirs' in-place to prevent os.walk from traversing into them
            dirs[:] = [d for d in dirs if d not in folders_to_exclude]
            
            for file_name in files:
                file_path = os.path.join(root, file_name)
                if not file_types_to_include: # If no types specified, include all
                    processed_files.append(file_path)
                    # print(f"Including file (no type filter): {file_path}")
                else:
                    _, ext = os.path.splitext(file_name)
                    if ext in file_types_to_include:
                        processed_files.append(file_path)
                        # print(f"Including file (type match): {file_path}")
        
        print(f"Discovered {len(processed_files)} files after filtering.")
        # For now, just returning mock data and some info from the process
        analysis_result = {
            "message": "Repository cloned and files listed (simulated analysis).",
            "repo_url": repo_url,
            "cloned_to": os.path.abspath(temp_clone_dir),
            "overview": repo_overview,
            "tap_bap": tap_bap,
            "file_types_filter": file_types_str,
            "exclude_folders_filter": exclude_folders_str,
            "additional_specific_details": additional_info_list,
            "discovered_files_count": len(processed_files),
            # "first_10_files": [os.path.relpath(f, temp_clone_dir) for f in processed_files[:10]] # Example
        }
        
        print(f"Analysis data: {analysis_result}")
        return jsonify(analysis_result), 200

    except git.exc.GitCommandError as e:
        print(f"Git cloning error: {e}")
        return jsonify({"error": f"Failed to clone repository: {e.stderr}"}), 500
    except Exception as e:
        print(f"Error processing repository: {e}")
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500
    finally:
        # 3. Clean up the temporary cloned directory
        if os.path.exists(temp_clone_dir):
            print(f"Cleaning up temporary directory: {temp_clone_dir}")
            try:
                shutil.rmtree(temp_clone_dir)
                print(f"Successfully removed {temp_clone_dir}")
            except Exception as e_rm:
                print(f"Error removing temporary directory {temp_clone_dir}: {e_rm}")
        else:
            print(f"Temporary directory {temp_clone_dir} not found for cleanup (might have failed before creation or already cleaned).")


if __name__ == '__main__':
    # You can specify the port for your Flask app, e.g., 5001
    # Make sure this port is different from your Next.js app's port (e.g., 9002)
    app.run(host='127.0.0.1', port=5001, debug=True)

