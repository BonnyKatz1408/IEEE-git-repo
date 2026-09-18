import os
import sys
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash
import pymysql
from pymysql.cursors import DictCursor


PROJECT_ROOT = Path(__file__).resolve().parent
ANALYZER_ROOT = PROJECT_ROOT / 'repo-autopsy'
load_dotenv(PROJECT_ROOT / '.env')
load_dotenv(PROJECT_ROOT / 'Hackem' / '.env')
sys.path.insert(0, str(ANALYZER_ROOT))

from analyze import analyze as analyze_repository
from analyzer.cache import cache_dir, load_ai_answer, save_ai_answer
from analyzer.rag import classify_question, generate_answer


def _json_safe(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'change-this-secret-key')
if os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY'):
    app.logger.info('Gemini configured; model=%s', os.getenv('GEMINI_MODEL', 'gemini-3.6-flash'))
else:
    app.logger.warning('Gemini unavailable: GEMINI_API_KEY/GOOGLE_API_KEY not configured; using deterministic RAG fallback.')


def database_connection():
    return pymysql.connect(
        host=os.getenv('DB_HOST', '127.0.0.1'),
        port=int(os.getenv('DB_PORT', '3306')),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', ''),
        database=os.getenv('DB_NAME', 'waypoint'),
        cursorclass=DictCursor,
        autocommit=True,
    )


def ensure_users_table():
    connection = database_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    full_name VARCHAR(120) NOT NULL,
                    email VARCHAR(255) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            ''')
            for column, definition in {
                'bio': 'TEXT NULL',
                'location': 'VARCHAR(160) NULL',
                'github_username': 'VARCHAR(100) NULL',
            }.items():
                cursor.execute(
                    "SELECT COUNT(*) AS count FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = %s",
                    (column,),
                )
                if cursor.fetchone()['count'] == 0:
                    cursor.execute(f'ALTER TABLE users ADD COLUMN {column} {definition}')
    finally:
        connection.close()


def current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    ensure_users_table()
    connection = database_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT id, full_name, email, bio, location, github_username, created_at FROM users WHERE id = %s', (user_id,))
            return cursor.fetchone()
    finally:
        connection.close()


@app.context_processor
def inject_current_user():
    return {'current_user': current_user()}

@app.route('/')
def home():
    return render_template('index.html')
@app.route('/register')
def registerpage():
    if session.get('user_id'):
        return redirect(url_for('profile_page'))
    return render_template('registration.html')


@app.route('/login')
def loginpage():
    if session.get('user_id'):
        return redirect(url_for('profile_page'))
    return render_template('Login.html')


@app.route('/profile', methods=['GET', 'POST'])
def profile_page():
    if not session.get('user_id'):
        return redirect(url_for('loginpage'))
    ensure_users_table()
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        bio = request.form.get('bio', '').strip()
        location = request.form.get('location', '').strip()
        github_username = request.form.get('github_username', '').strip()
        if len(full_name) < 2 or '@' not in email:
            return render_template('profile.html', profile_error='Enter a name and valid email address.', profile_form=request.form), 400
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute('''
                    UPDATE users SET full_name = %s, email = %s, bio = %s, location = %s, github_username = %s
                    WHERE id = %s
                ''', (full_name, email, bio, location, github_username, session['user_id']))
        except pymysql.err.IntegrityError:
            return render_template('profile.html', profile_error='That email address is already in use.', profile_form=request.form), 409
        finally:
            connection.close()
        session['user_name'] = full_name
        return redirect(url_for('profile_page', saved=1))
    return render_template('profile.html', profile_saved=request.args.get('saved') == '1')


@app.post('/api/signup')
def signup_route():
    payload = request.get_json(silent=True) or {}
    full_name = str(payload.get('full_name', '')).strip()
    email = str(payload.get('email', '')).strip().lower()
    password = str(payload.get('password', ''))
    if len(full_name) < 2 or '@' not in email or len(password) < 8:
        return jsonify({'error': 'Enter a name, valid email, and password of at least 8 characters.'}), 400

    try:
        ensure_users_table()
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    'INSERT INTO users (full_name, email, password_hash) VALUES (%s, %s, %s)',
                    (full_name, email, generate_password_hash(password)),
                )
                user_id = cursor.lastrowid
        finally:
            connection.close()
        session['user_id'] = user_id
        session['user_name'] = full_name
        return jsonify({'message': 'Account created. You can now sign in.'}), 201
    except pymysql.err.IntegrityError:
        return jsonify({'error': 'An account with that email already exists.'}), 409
    except Exception as error:
        app.logger.exception('Signup failed')
        return jsonify({'error': str(error)}), 500


@app.post('/api/login')
def login_route():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get('email', '')).strip().lower()
    password = str(payload.get('password', ''))
    if not email or not password:
        return jsonify({'error': 'Enter your email and password.'}), 400

    try:
        ensure_users_table()
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT id, full_name, email, password_hash FROM users WHERE email = %s', (email,))
                user = cursor.fetchone()
        finally:
            connection.close()
        if not user or not check_password_hash(user['password_hash'], password):
            return jsonify({'error': 'Invalid email or password.'}), 401
        session['user_id'] = user['id']
        session['user_name'] = user['full_name']
        return jsonify({'message': 'Signed in.', 'user': {'full_name': user['full_name'], 'email': user['email']}})
    except Exception as error:
        app.logger.exception('Login failed')
        return jsonify({'error': str(error)}), 500


@app.post('/logout')
def logout_route():
    session.clear()
    return jsonify({'message': 'Signed out.'})


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


@app.post('/api/ask')
def ask_route():
    payload = request.get_json(silent=True) or {}
    repository_url = str(payload.get('url', '')).strip()
    question = str(payload.get('question', '')).strip()
    context = payload.get('context') or {}
    if not repository_url:
        return jsonify({'error': 'Enter a GitHub repository URL.'}), 400
    if not question:
        return jsonify({'error': 'Enter a question about the repository.'}), 400
    if 'github.com' not in repository_url.lower():
        return jsonify({'error': 'Only public GitHub repository URLs are supported.'}), 400

    try:
        report = analyze_repository(repository_url)
        rag = report.get('rag') or {'chunks': []}
        intent = classify_question(question, context)
        cache_key = report.get('version') or {}
        ai_cache = cache_dir(PROJECT_ROOT, cache_key.get('owner', ''), cache_key.get('repo', ''), cache_key.get('sha', ''))
        answer = load_ai_answer(ai_cache, intent) if intent in {'repository-overview', 'main-flow'} else None
        if answer is None:
            answer = generate_answer(question, report, rag.get('chunks', []), context)
            if intent in {'repository-overview', 'main-flow'} and answer.get('mode') == 'gemini-rag':
                save_ai_answer(ai_cache, intent, answer)
        return jsonify(_json_safe(answer))
    except Exception as error:
        app.logger.exception('Repository Q&A failed')
        return jsonify({'error': str(error)}), 500

if __name__=='__main__':
    app.run(debug=True, host="0.0.0.0",port =8080)