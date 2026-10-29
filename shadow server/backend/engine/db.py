"""PostgreSQL application storage. SQLite is an explicit isolated-test backend."""
import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from functools import lru_cache
from engine.config import ROOT

_initialized = set()
_init_lock = threading.Lock()
TABLES = {'runs', 'signals', 'candidates', 'issues', 'observations', 'reference_documents', 'scenarios', 'telemetry_events', 'settings', 'audit_events', 'evidence_events'}

def backend():
    return os.environ.get('SHADOWAI_DB_BACKEND', 'postgresql')

def schema():
    name = os.environ.get('SHADOWAI_DB_SCHEMA', 'public')
    if not re.fullmatch(r'[a-z_][a-z0-9_]*', name):
        raise ValueError('Invalid database schema')
    return name

@lru_cache(maxsize=1)
def saved_password():
    raise RuntimeError('Set SHADOWAI_DB_PASSWORD in backend/.env or run start.bat to enter it securely.')

def connection_parameters(database=None):
    path = ROOT / '.runtime/database.json'
    settings = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    return dict(host=os.environ.get('SHADOWAI_DB_HOST', settings.get('host', '127.0.0.1')), port=int(os.environ.get('SHADOWAI_DB_PORT', settings.get('port', 5432))),
        user=os.environ.get('SHADOWAI_DB_USER', settings.get('user', 'postgres')), password=os.environ.get('SHADOWAI_DB_PASSWORD') or saved_password(),
        dbname=database or os.environ.get('SHADOWAI_DB_NAME', settings.get('database', 'shadow_ai_discovery')), connect_timeout=5)

def decode(value):
    return json.loads(value) if isinstance(value, str) else value

class PostgresConnection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, args=()):
        from psycopg.types.json import Jsonb
        converted = []
        for value in args:
            if isinstance(value, str) and value[:1] in ('{', '['):
                value = Jsonb(json.loads(value))
            converted.append(value)
        return self.raw.execute(sql.replace('?', '%s'), converted)

@contextmanager
def connection():
    if backend() == 'sqlite':
        (ROOT / 'data').mkdir(exist_ok=True)
        raw = sqlite3.connect(ROOT / 'data/discovery.sqlite', timeout=30)
        raw.execute('PRAGMA journal_mode=WAL')
        raw.executescript('''
        CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY, run_id TEXT, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS signals (id TEXT PRIMARY KEY, run_id TEXT, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS candidates (id TEXT PRIMARY KEY, run_id TEXT, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS issues (id TEXT PRIMARY KEY, candidate_id TEXT UNIQUE, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reference_documents (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS scenarios (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS telemetry_events (id TEXT PRIMARY KEY, stream TEXT, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit_events (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS evidence_events (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        ''')
        db = raw
    elif backend() == 'postgresql':
        import psycopg
        raw = psycopg.connect(**connection_parameters())
        name = schema()
        raw.execute(f'SET search_path TO "{name}"')
        key = (raw.info.host, raw.info.port, raw.info.dbname, name)
        with _init_lock:
            if key not in _initialized:
                raw.execute(f'CREATE SCHEMA IF NOT EXISTS "{name}"')
                raw.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload JSONB NOT NULL, sequence BIGSERIAL UNIQUE)')
                raw.execute('CREATE TABLE IF NOT EXISTS observations (id BIGSERIAL PRIMARY KEY, run_id TEXT NOT NULL, payload JSONB NOT NULL)')
                raw.execute('CREATE TABLE IF NOT EXISTS signals (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, payload JSONB NOT NULL)')
                raw.execute('CREATE TABLE IF NOT EXISTS candidates (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, payload JSONB NOT NULL)')
                raw.execute('CREATE TABLE IF NOT EXISTS issues (id TEXT PRIMARY KEY, candidate_id TEXT UNIQUE NOT NULL, payload JSONB NOT NULL)')
                for table in ('reference_documents', 'scenarios', 'settings'):
                    raw.execute(f'CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, payload JSONB NOT NULL)')
                raw.execute('CREATE TABLE IF NOT EXISTS telemetry_events (id TEXT PRIMARY KEY, stream TEXT NOT NULL, payload JSONB NOT NULL)')
                raw.execute('CREATE TABLE IF NOT EXISTS audit_events (id TEXT PRIMARY KEY, payload JSONB NOT NULL, sequence BIGSERIAL UNIQUE)')
                raw.execute('CREATE TABLE IF NOT EXISTS evidence_events (id TEXT PRIMARY KEY, payload JSONB NOT NULL)')
                raw.execute('CREATE INDEX IF NOT EXISTS signals_run_idx ON signals(run_id)')
                raw.execute('CREATE INDEX IF NOT EXISTS telemetry_stream_idx ON telemetry_events(stream)')
                raw.execute('CREATE INDEX IF NOT EXISTS observations_run_idx ON observations(run_id)')
                raw.commit()
                _initialized.add(key)
        db = PostgresConnection(raw)
    else:
        raise ValueError('Unsupported SHADOWAI_DB_BACKEND')
    try:
        yield db
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()

def list_payloads(table, run_id=None):
    if table not in TABLES:
        raise ValueError('Unknown table')
    with connection() as db:
        query, args = f'SELECT payload FROM {table}', ()
        if run_id:
            query += ' WHERE run_id=?'
            args = (run_id,)
        if table in ('runs', 'audit_events'):
            query += ' ORDER BY ' + ('sequence' if backend() == 'postgresql' else 'rowid')
        elif table != 'observations':
            query += ' ORDER BY id'
        return [decode(r[0]) for r in db.execute(query, args)]

def document(table, name):
    if table not in {'settings', 'reference_documents', 'scenarios'}:
        raise ValueError('Unknown document table')
    with connection() as db:
        row = db.execute(f'SELECT payload FROM {table} WHERE id=?', (name,)).fetchone()
    return decode(row[0]) if row else None

def put_document(table, name, payload):
    if table not in {'settings', 'reference_documents', 'scenarios'}:
        raise ValueError('Unknown document table')
    with connection() as db:
        db.execute(f'INSERT INTO {table}(id,payload) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (name, json.dumps(payload)))

def status():
    with connection() as db:
        db.execute('SELECT 1')
    return {'backend': backend(), 'database': os.environ.get('SHADOWAI_DB_NAME', 'shadow_ai_discovery'), 'connected': True}
