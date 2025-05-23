
from flask import Flask, jsonify, request
from flask_cors import CORS
# import git # Would be imported if GitPython is used
# import os
# import shutil # For cleaning up temp directories

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
    # In a real application, you would fetch this data from a database
    # or another source based on your OpenAI integration.
    return jsonify(mock_repositories)

@app.route('/api/analyze-repo', methods=['POST'])
def analyze_repo():
    data = request.json
    repo_url = data.get('repo_url')
    repo_overview = data.get('repo_overview')
    tap_bap = data.get('tap_bap')
    file_types_str = data.get('file_types') # e.g., ".ts,.tsx,.md"
    exclude_folders_str = data.get('exclude_folders') # e.g., "node_modules,.git"
    additional_info_list = data.get('additional_info_list')

    if not repo_url:
        return jsonify({"error": "Repository URL is required"}), 400

    # Placeholder for Git cloning and file processing logic
    # temp_clone_dir = "temp_repo_clone" # Define a temporary directory path
    
    try:
        # 1. Clone the repository using GitPython
        # print(f"Cloning repository: {repo_url} to {temp_clone_dir}")
        # git.Repo.clone_from(repo_url, temp_clone_dir)
        # print("Repository cloned successfully.")

        # 2. Recursively list files, applying filters
        #    (using os.walk or pathlib)
        #    - Filter by file_types
        #    - Exclude exclude_folders
        processed_files = [] # This would be a list of file paths or content
        # Example:
        # for root, dirs, files in os.walk(temp_clone_dir):
        #     # Filter dirs based on exclude_folders_str
        #     # Filter files based on file_types_str
        #     for file_name in files:
        #         processed_files.append(os.path.join(root, file_name))
        
        # For now, returning mock data
        mock_analysis_result = {
            "message": "Repository analysis initiated (mock response).",
            "repo_url": repo_url,
            "overview": repo_overview,
            "tap_bap": tap_bap,
            "file_types_to_include": file_types_str,
            "folders_to_exclude": exclude_folders_str,
            "additional_specific_details": additional_info_list,
            "discovered_files_count": 0 # Replace with actual count
        }
        
        print(f"Analysis data: {mock_analysis_result}")
        return jsonify(mock_analysis_result), 200

    except Exception as e:
        # print(f"Error processing repository: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        # 3. Clean up the temporary cloned directory
        # if os.path.exists(temp_clone_dir):
        #     print(f"Cleaning up temporary directory: {temp_clone_dir}")
        #     shutil.rmtree(temp_clone_dir)
        pass

if __name__ == '__main__':
    # You can specify the port for your Flask app, e.g., 5001
    # Make sure this port is different from your Next.js app's port (e.g., 9002)
    app.run(host='127.0.0.1', port=5001, debug=True)

