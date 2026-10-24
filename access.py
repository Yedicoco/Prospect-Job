"""Comptes locaux PBKDF2 ; HTTP Basic doit être transporté via HTTPS en production."""
import base64
import hashlib
import hmac
import os
import secrets

connect = None
ROLES = ('admin', 'commercial', 'recrutement', 'lecture')


def configure(factory):
    global connect
    connect = factory
    with connect() as con:
        con.execute('CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, salt TEXT NOT NULL, digest TEXT NOT NULL, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)')


def add_user(username, password, role):
    if role not in ROLES or not username or len(username) > 80 or ':' in username or len(password) < 16:
        raise ValueError('Nom valide, rôle reconnu et mot de passe de 16 caractères minimum requis')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
    with connect() as con:
        con.execute('INSERT INTO users(username,salt,digest,role) VALUES (?,?,?,?) ON CONFLICT(username) DO UPDATE SET salt=excluded.salt,digest=excluded.digest,role=excluded.role,active=1', (username, salt, digest, role))


def authenticate(header):
    with connect() as con:
        count = con.execute('SELECT COUNT(*) FROM users WHERE active=1').fetchone()[0]
    fallback = os.getenv('YALLAH_ADMIN_PASSWORD', '')
    if not count and not fallback and os.getenv('YALLAH_ENV', 'development') != 'production':
        return {'username': 'local', 'role': 'admin'}
    try:
        scheme, token = header.split(' ', 1)
        if scheme != 'Basic':
            return None
        username, password = base64.b64decode(token, validate=True).decode().split(':', 1)
    except (ValueError, UnicodeDecodeError):
        return None
    if username == 'admin' and fallback and hmac.compare_digest(password.encode(), fallback.encode()):
        return {'username': 'admin', 'role': 'admin'}
    with connect() as con:
        row = con.execute('SELECT * FROM users WHERE username=? AND active=1', (username,)).fetchone()
    # Même coût pour un utilisateur inexistant.
    salt = bytes.fromhex(row['salt']) if row else bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600000).hex()
    if row and hmac.compare_digest(digest, row['digest']):
        return {'username': username, 'role': row['role']}
    return None


def production_check():
    if os.getenv('YALLAH_ENV', 'development') != 'production':
        return
    from urllib.parse import urlparse
    if os.getenv('YALLAH_ADMIN_PASSWORD') and len(os.environ['YALLAH_ADMIN_PASSWORD']) < 16:
        raise ValueError('Production : mot de passe administrateur de secours trop court')
    if urlparse(os.getenv('YALLAH_PUBLIC_URL', '')).scheme != 'https':
        raise ValueError('Production : YALLAH_PUBLIC_URL HTTPS requis ; configurez aussi la terminaison TLS du proxy')
    with connect() as con:
        has_admin = con.execute("SELECT 1 FROM users WHERE role='admin' AND active=1").fetchone()
    if not has_admin and len(os.getenv('YALLAH_ADMIN_PASSWORD', '')) < 16:
        raise ValueError('Production : compte administrateur fort requis')


def allow(role, action):
    if role == 'admin':
        return True
    commercial = {'opportunity', 'task', 'need_from_opportunity', 'qualify_need', 'conversation', 'email_ingest', 'proposal', 'intake_status', 'prospect_save', 'manual_action', 'intake_opportunity', 'time_log'}
    recruitment = {'candidate', 'application', 'assignment', 'assignment_update', 'task', 'need_save', 'email_ingest', 'intake_status', 'intake_classify', 'time_log'}
    return action in (commercial if role == 'commercial' else recruitment if role == 'recrutement' else set())
