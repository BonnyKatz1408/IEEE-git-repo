import os
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv

# Load variables from .env file into os.environ
load_dotenv()

app = Flask(__name__)

# --- Environment Variables ---
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'default-dev-fallback-key')

DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'port': int(os.environ.get('DB_PORT', 3306)),
    'user': os.environ.get('DB_USER', 'root'),
    'password': os.environ.get('DB_PASSWORD', ''),
    'database': os.environ.get('DB_NAME', 'waypoint_db')
}

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

# --- Authentication Guard Decorator ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Page Routes ---
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/register')
def registerpage():
    if 'user_id' in session:
        return redirect(url_for('analyze'))
    return render_template('registration.html')

@app.route('/login')
def login():
    if 'user_id' in session:
        return redirect(url_for('analyze'))
    return render_template('login.html')

@app.route('/analyze')
@login_required
def analyze():
    return render_template('dashboard.html', user_name=session.get('user_name'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- Auth API Endpoints ---
@app.route('/auth/register', methods=['POST'])
def register_auth():
    data = request.get_json() or {}
    fullname = data.get('fullname', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    confirm_password = data.get('confirm_password', '')

    if not fullname or not email or not password:
        return jsonify({'success': False, 'message': 'All fields are required.'}), 400

    if password != confirm_password:
        return jsonify({'success': False, 'message': 'Passwords do not match.'}), 400

    if len(password) < 8:
        return jsonify({'success': False, 'message': 'Password must be at least 8 characters.'}), 400

    password_hash = generate_password_hash(password)

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id FROM users WHERE work_email = %s", (email,))
        if cursor.fetchone():
            return jsonify({'success': False, 'message': 'Work email is already registered.'}), 409

        sql = """
            INSERT INTO users (full_name, work_email, password_hash)
            VALUES (%s, %s, %s)
        """
        cursor.execute(sql, (fullname, email, password_hash))
        conn.commit()

        return jsonify({'success': True, 'message': 'Account created successfully.'}), 201

    except Error as e:
        return jsonify({'success': False, 'message': 'Database error occurred.'}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

@app.route('/auth/login', methods=['POST'])
def login_auth():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    remember = data.get('remember', False)

    if not email or not password:
        return jsonify({'success': False, 'message': 'Email and password are required.'}), 400

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id, full_name, password_hash FROM users WHERE work_email = %s", (email,))
        user = cursor.fetchone()

        if not user or not check_password_hash(user['password_hash'], password):
            return jsonify({'success': False, 'message': 'Invalid credentials.'}), 401

        session['user_id'] = user['id']
        session['user_name'] = user['full_name']
        session.permanent = remember

        return jsonify({'success': True, 'redirect': url_for('analyze')}), 200

    except Error as e:
        return jsonify({'success': False, 'message': 'Database error occurred.'}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() in ('true', '1', 't')
    port = int(os.environ.get('FLASK_PORT', 5000))
    app.run(debug=debug_mode, host='0.0.0.0', port=port)