"""SQLite connection management for the persistent cache."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transcripts (
    cache_key  TEXT PRIMARY KEY,
    video_id   TEXT NOT NULL,
    language   TEXT,
    source     TEXT,
    model      TEXT,
    options    TEXT,
    payload    TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transcripts_video ON transcripts(video_id);
CREATE TABLE IF NOT EXISTS metadata (
    video_id   TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
"""


class CacheDatabase:
    """Thread-safe wrapper around a single SQLite connection."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock, self._conn:
            return self._conn.execute(sql, params)

    def query_all(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple = ()) -> tuple | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    @staticmethod
    def dumps(obj) -> str:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def loads(raw: str):
        return json.loads(raw)

    @staticmethod
    def now() -> float:
        return time.time()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
