"""Small transactional JSON store; every connection stays in its own thread."""
import json
import sqlite3
import threading
from pathlib import Path


class Store:
    def __init__(self, db_path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            conn.execute('PRAGMA user_version=1')

    def connect(self):
        conn = sqlite3.connect(str(self.path), timeout=15)
        conn.execute('PRAGMA busy_timeout=15000')
        return conn

    def get(self, key, default=None):
        with self.lock, self.connect() as conn:
            row = conn.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set(self, key, value):
        serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
        with self.lock, self.connect() as conn:
            conn.execute('INSERT INTO kv(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, serialized))
        return value

    def delete(self, key):
        with self.lock, self.connect() as conn:
            conn.execute('DELETE FROM kv WHERE key=?', (key,))

    def update(self, key, fn, default=None):
        with self.lock, self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
            value = fn(json.loads(row[0]) if row else default)
            conn.execute('INSERT INTO kv(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(value, ensure_ascii=False, allow_nan=False)))
            return value

    def backup(self, target):
        with self.lock, self.connect() as source, sqlite3.connect(str(target)) as dest:
            source.backup(dest)
