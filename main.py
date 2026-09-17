import sys
from pathlib import Path

from flask import Flask, jsonify, render_template, request


PROJECT_ROOT = Path(__file__).resolve().parent
ANALYZER_ROOT = PROJECT_ROOT / 'repo-autopsy'
sys.path.insert(0, str(ANALYZER_ROOT))

from analyze import analyze as analyze_repository


def _json_safe(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


app = Flask(__name__)
@app.route('/')
def home():
    return render_template('index.html')
@app.route('/register')
def registerpage():
    return render_template('registration.html')


@app.post('/api/analyze')
def analyze_route():
    payload = request.get_json(silent=True) or {}
    repository_url = str(payload.get('url', '')).strip()
    if not repository_url:
        return jsonify({'error': 'Enter a GitHub repository URL.'}), 400
    if 'github.com' not in repository_url.lower():
        return jsonify({'error': 'Only public GitHub repository URLs are supported.'}), 400

    try:
        report = analyze_repository(repository_url)
        return jsonify(_json_safe(report))
    except Exception as error:
        app.logger.exception('Repository analysis failed')
        return jsonify({'error': str(error)}), 500
if __name__=='__main__':
    app.run(debug=True, host="0.0.0.0",port =8080)