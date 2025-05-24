
from flask import Flask, jsonify, request
from flask_cors import CORS
from pydantic import BaseModel, ValidationError, validator
from typing import List, Dict
import uuid
import json

# Refactored service imports
from services.database_service import init_db, save_tutor_config, get_all_tutors
from services.processing_service import process_repository_content
from services.utils import extract_project_name_from_url, extract_project_name_from_path

app = Flask(__name__)
CORS(app)

# Initialize database on startup
init_db()

# --- Pydantic Models ---
class AdditionalInfoItemInput(BaseModel):
    title: str
    description: str

class CreateTutorInput(BaseModel):
    input_type: str  # 'folder' or 'url'
    source_location: str
    repo_overview: str = ""
    tap_bap: str = ""
    file_types: str = ""
    exclude_folders: str = ""
    additional_info_list: List[AdditionalInfoItemInput] = []
    embed_repo: bool = False

    @validator('source_location')
    def source_location_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Source location (folder path or URL) cannot be empty')
        return v

    @validator('input_type')
    def input_type_must_be_valid(cls, v):
        if v not in ['folder', 'url']:
            raise ValueError("Input type must be 'folder' or 'url'")
        return v

# --- API Endpoints ---
@app.route('/api/repos', methods=['GET'])
def get_repos_from_db_route():
    try:
        repos = get_all_tutors()
        return jsonify(repos)
    except Exception as e:
        print(f"Error fetching repos: {e}")
        return jsonify({"error": "Failed to fetch repositories"}), 500

@app.route('/api/analyze-repo', methods=['POST'])
def analyze_repo_route():
    try:
        data = CreateTutorInput(**request.json)
    except ValidationError as e:
        return jsonify({"error": "Invalid input", "details": e.errors()}), 400
    except Exception as e:
        print(f"Error parsing request: {e}")
        return jsonify({"error": f"Error parsing request JSON: {str(e)}"}), 400

    tutor_id = str(uuid.uuid4())
    project_name = ""
    if data.input_type == 'url':
        project_name = extract_project_name_from_url(data.source_location)
    elif data.input_type == 'folder':
        project_name = extract_project_name_from_path(data.source_location)
    else: # Should be caught by Pydantic validator, but as a fallback
        return jsonify({"error": "Invalid input_type provided."}), 400

    try:
        save_tutor_config(
            tutor_id=tutor_id,
            project_name=project_name,
            input_type=data.input_type,
            source_location=data.source_location,
            repo_overview=data.repo_overview,
            tap_bap=data.tap_bap,
            file_types_str=data.file_types,
            exclude_folders_str=data.exclude_folders,
            additional_info_list_json=json.dumps([item.model_dump() for item in data.additional_info_list]),
            embed_repo_flag=data.embed_repo
        )
    except Exception as e:
        print(f"Database error during save_tutor_config: {e}")
        return jsonify({"error": f"Database error: {str(e)}"}), 500

    analysis_result = {
        "message": "Self Tutor configuration saved.",
        "tutor_id": tutor_id,
        "project_name": project_name,
        "source_location": data.source_location,
        "input_type": data.input_type,
    }

    if data.embed_repo:
        try:
            discovered_files_count, processing_message = process_repository_content(
                input_type=data.input_type,
                source_location=data.source_location,
                file_types_str=data.file_types,
                exclude_folders_str=data.exclude_folders,
                tutor_id=tutor_id # for unique temp folder if cloning
            )
            analysis_result["message"] = processing_message
            analysis_result["discovered_files_count"] = discovered_files_count
        except Exception as e:
            print(f"Error processing repository content: {e}")
            analysis_result["embedding_error"] = str(e)
            # Configuration is saved, but embedding failed.
            analysis_result["message"] = "Self Tutor configuration saved, but repository/folder processing failed."
            analysis_result["discovered_files_count"] = 0
    else:
        print("Repository/folder embedding skipped by user.")
        analysis_result["discovered_files_count"] = "N/A (Embedding skipped)"

    return jsonify(analysis_result), 200


if __name__ == '__main__':
    # init_db is called at the top level when the module is imported
    app.run(host='127.0.0.1', port=5001, debug=True)

    