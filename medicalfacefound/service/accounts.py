"""Local accounts with scrypt passwords and revocable, hashed session credentials."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from uuid import uuid4

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, Field

from medicalfacefound.service import database as db

COOKIE = 'mff_session'
SESSION_SECONDS = 7 * 24 * 3600


def initialize_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS participants (
        id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS participant_sessions (
        token_hash TEXT PRIMARY KEY, participant_id TEXT NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
        expires_at REAL NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS auth_attempts (
        bucket TEXT PRIMARY KEY, started_at REAL NOT NULL, attempts INTEGER NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS clinical_information (
        capture_id TEXT PRIMARY KEY REFERENCES captures(id) ON DELETE CASCADE,
        information_json TEXT NOT NULL, updated_at TEXT NOT NULL)''')
    cols = {r[1] for r in conn.execute('PRAGMA table_info(captures)')}
    for name, kind in {
        'subject_id': "TEXT NOT NULL DEFAULT 'unknown'",
        'participant_id': 'TEXT REFERENCES participants(id)',
        'research_consent': 'INTEGER NOT NULL DEFAULT 0',
        'training_consent': 'INTEGER NOT NULL DEFAULT 0',
        'research_consent_version': 'TEXT',
        'research_consented_at': 'TEXT',
    }.items():
        if name not in cols:
            conn.execute(f'ALTER TABLE captures ADD COLUMN {name} {kind}')
    conn.execute('''CREATE TABLE IF NOT EXISTS subjects (
        id TEXT PRIMARY KEY, participant_id TEXT NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
        label TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(participant_id,label))''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_capture_participant ON captures(participant_id,created_at)')
    conn.execute('''CREATE TABLE IF NOT EXISTS consent_events (
        id TEXT PRIMARY KEY, capture_id TEXT NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
        research INTEGER NOT NULL, training INTEGER NOT NULL, version TEXT NOT NULL, created_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS observations (
        capture_id TEXT NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
        model TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL, measured_on TEXT NOT NULL,
        source TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(capture_id, model))''')


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, maxmem=64*1024*1024)
    return salt + ':' + digest.hex()


def check_write(request):
    # Cross-origin forms cannot provide this header; no CORS origins are allowed.
    if request.headers.get('X-MFF-Request') != '1':
        raise HTTPException(403, '请通过本站页面提交请求')


def current_user(path, request: Request, required=False):
    token = request.cookies.get(COOKIE)
    user = None
    if token:
        with db.connect(path) as conn:
            row = conn.execute('''SELECT p.id,p.username FROM participants p JOIN participant_sessions s
                ON s.participant_id=p.id WHERE s.token_hash=? AND s.expires_at>?''',
                (db.token_hash(token), time.time())).fetchone()
            user = dict(row) if row else None
    if required and not user:
        raise HTTPException(401, '请先登录个人账号')
    if user and request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        check_write(request)
    return user


def validate_subject(path, subject_id, user, allow_unknown=True):
    if subject_id == 'self' or (allow_unknown and user and subject_id == 'unknown'):
        return
    if not user:
        raise HTTPException(403, '请登录后选择其他对象')
    with db.connect(path) as conn:
        if not conn.execute('SELECT 1 FROM subjects WHERE id=? AND participant_id=?', (subject_id,user['id'])).fetchone():
            raise HTTPException(404, '对象不存在')


class SubjectCreate(BaseModel):
    label: str = Field(min_length=1,max_length=40)


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r'^[A-Za-z0-9_\-]+$')
    password: str = Field(min_length=10, max_length=128)


def add_account_routes(app, settings):
    path = settings.database_path

    def rate_limit(request):
        # Do not trust client-supplied X-Forwarded-For. Uvicorn controls proxy trust.
        bucket = db.token_hash(request.client.host if request.client else 'local')
        now = time.time()
        with db.connect(path) as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('DELETE FROM auth_attempts WHERE started_at<?', (now-900,))
            row = conn.execute('SELECT attempts FROM auth_attempts WHERE bucket=?', (bucket,)).fetchone()
            if row and row[0] >= 20:
                raise HTTPException(429, '尝试次数过多，请在 15 分钟后重试')
            conn.execute('''INSERT INTO auth_attempts VALUES (?,?,1)
                ON CONFLICT(bucket) DO UPDATE SET attempts=attempts+1''', (bucket, now))

    def session(response, request, user):
        token = secrets.token_urlsafe(32)
        with db.connect(path) as conn:
            conn.execute('DELETE FROM participant_sessions WHERE expires_at<?', (time.time(),))
            old = request.cookies.get(COOKIE)
            if old:
                conn.execute('DELETE FROM participant_sessions WHERE token_hash=?', (db.token_hash(old),))
            conn.execute('INSERT INTO participant_sessions VALUES (?,?,?)',
                         (db.token_hash(token), user['id'], time.time()+SESSION_SECONDS))
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                            secure=request.url.scheme == 'https', samesite='strict', path='/')
        return {'user': user}

    @app.post('/v1/account/register', status_code=201)
    def register(body: Credentials, request: Request, response: Response):
        check_write(request)
        rate_limit(request)
        identity, username = str(uuid4()), body.username.lower()
        hashed = password_hash(body.password)
        try:
            with db.connect(path) as conn:
                conn.execute('INSERT INTO participants VALUES (?,?,?,?)', (identity, username, hashed, db.now()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, '该账号名不可用，请更换') from None
        return session(response, request, {'id': identity, 'username': username})

    @app.post('/v1/account/login')
    def login(body: Credentials, request: Request, response: Response):
        check_write(request)
        rate_limit(request)
        with db.connect(path) as conn:
            row = conn.execute('SELECT * FROM participants WHERE username=?', (body.username.lower(),)).fetchone()
        salt = row['password_hash'].split(':')[0] if row else '0'*32
        candidate = password_hash(body.password, salt)
        if not row or not secrets.compare_digest(candidate, row['password_hash']):
            raise HTTPException(401, '账号或密码不正确')
        return session(response, request, {'id': row['id'], 'username': row['username']})

    @app.post('/v1/account/logout')
    def logout(request: Request, response: Response):
        check_write(request)
        with db.connect(path) as conn:
            conn.execute('DELETE FROM participant_sessions WHERE token_hash=?',
                         (db.token_hash(request.cookies.get(COOKIE, '')),))
        response.delete_cookie(COOKIE, path='/')
        return {'status': 'logged_out'}

    @app.get('/v1/account/me')
    def me(request: Request):
        return {'user': current_user(path, request)}

    @app.get('/v1/me/subjects')
    def subjects(request: Request):
        user=current_user(path,request,required=True)
        with db.connect(path) as conn:
            items=[dict(r) for r in conn.execute('SELECT id,label FROM subjects WHERE participant_id=? ORDER BY created_at,id',(user['id'],))]
            counts=dict(conn.execute('SELECT subject_id,COUNT(*) FROM captures WHERE participant_id=? GROUP BY subject_id',(user['id'],)).fetchall())
        return {'items':[{**item,'record_count':counts.get(item['id'],0)} for item in [{'id':'self','label':'本人'},{'id':'unknown','label':'待确认'},*items]]}

    @app.post('/v1/me/subjects',status_code=201)
    def create_subject(body: SubjectCreate, request: Request):
        user=current_user(path,request,required=True)
        label=body.label.strip()
        if not label or label in {'本人','待确认'}: raise HTTPException(422,'请填写成员称呼，不能使用“本人”或“待确认”')
        identity=str(uuid4())
        try:
            with db.connect(path) as conn:
                conn.execute('INSERT INTO subjects VALUES (?,?,?,?)',(identity,user['id'],label,db.now()))
        except sqlite3.IntegrityError:
            raise HTTPException(409,'该成员称呼已存在') from None
        return {'id':identity,'label':label}

    @app.get('/v1/me/captures')
    def history(request: Request, offset: int = 0, limit: int = 20, subject_id: str | None = None):
        user = current_user(path, request, required=True)
        if subject_id is not None: validate_subject(path,subject_id,user)
        if offset < 0 or not 1 <= limit <= 100:
            raise HTTPException(422, '无效分页参数')
        with db.connect(path) as conn:
            total = conn.execute('SELECT COUNT(*) FROM captures WHERE participant_id=? AND (? IS NULL OR subject_id=?)', (user['id'],subject_id,subject_id)).fetchone()[0]
            ids = [r[0] for r in conn.execute('''SELECT id FROM captures WHERE participant_id=? AND (? IS NULL OR subject_id=?)
                ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?''', (user['id'],subject_id,subject_id, limit, offset))]
        return {'total': total, 'items': [r for identity in ids if (r := db.report(path, identity))]}
