
from flask import Flask, jsonify
from flask_cors import CORS

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

if __name__ == '__main__':
    # You can specify the port for your Flask app, e.g., 5001
    # Make sure this port is different from your Next.js app's port (e.g., 9002)
    app.run(host='127.0.0.1', port=5001, debug=True)
