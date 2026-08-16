"""Transcript + metadata repository on top of the cache database.

Cache key incorporates video_id + language + provider + model + options so the
same video is never stored twice for one configuration (duplicate detection),
and different configurations coexist (e.g. captions vs whisper = transcript diff).
"""
from __future__ import annotations

import hashlib
import logging

from src.cache.database import CacheDatabase
from src.config.settings import Settings

logger = logging.getLogger(__name__)


def make_cache_key(video_id: str, language: str, provider: str, model: str,
                   word_timestamps: bool, include_speakers: bool) -> str:
    raw = "|".join([
        "v1", video_id, (language or "auto").lower(), (provider or "").lower(),
        (model or "").lower(), str(bool(word_timestamps)), str(bool(include_speakers)),
    ]).lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class TranscriptRepository:
    """Persistent cache for transcripts and video metadata."""

    def __init__(self, settings: Settings):
        self._s = settings
        self._db = CacheDatabase(settings.cache_dir / "transcripts.sqlite3")

    # ------------------------------------------------------------ transcripts

    def get(self, cache_key: str) -> dict | None:
        if not self._s.cache_enabled:
            return None
        row = self._db.query_one(
            "SELECT payload, created_at FROM transcripts WHERE cache_key = ?", (cache_key,))
        if not row:
            return None
        payload, created = row
        if self._expired(created):
            self._db.execute("DELETE FROM transcripts WHERE cache_key = ?", (cache_key,))
            return None
        data = self._db.loads(payload)
        data.setdefault("cache", {})["cache_key"] = cache_key
        return data

    def put(self, cache_key: str, payload: dict) -> None:
        if not self._s.cache_enabled:
            return
        self._db.execute(
            "INSERT OR REPLACE INTO transcripts "
            "(cache_key, video_id, language, source, model, options, payload, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (cache_key,
             payload.get("video_id", ""),
             payload.get("language", ""),
             payload.get("transcript_source", payload.get("source", "")),
             payload.get("model", ""),
             self._db.dumps({k: payload.get(k) for k in ("word_timestamps", "provider")}),
             self._db.dumps(payload),
             self._db.now()))
        self.prune()

    def find_latest(self, video_id: str, language: str | None = None) -> dict | None:
        """Newest cached transcript for a video (optionally language-filtered)."""
        if not self._s.cache_enabled:
            return None
        if language:
            rows = self._db.query_all(
                "SELECT cache_key, created_at FROM transcripts WHERE video_id = ? AND language LIKE ? "
                "ORDER BY created_at DESC, rowid DESC", (video_id, language.lower().split("-")[0] + "%"))
        else:
            rows = self._db.query_all(
                "SELECT cache_key, created_at FROM transcripts WHERE video_id = ? "
                "ORDER BY created_at DESC, rowid DESC", (video_id,))
        for cache_key, created in rows:
            if self._expired(created):
                continue
            row = self._db.query_one("SELECT payload FROM transcripts WHERE cache_key = ?", (cache_key,))
            if row:
                data = self._db.loads(row[0])
                data.setdefault("cache", {})["cache_key"] = cache_key
                return data
        return None

    def versions(self, video_id: str) -> list[dict]:
        """All cached versions (used for transcript diff + duplicate awareness)."""
        rows = self._db.query_all(
            "SELECT cache_key, language, source, model, created_at FROM transcripts "
            "WHERE video_id = ? ORDER BY created_at DESC", (video_id,))
        return [
            {"cache_key": r[0], "language": r[1], "source": r[2], "model": r[3], "created_at": r[4]}
            for r in rows
        ]

    def delete(self, cache_key: str) -> None:
        self._db.execute("DELETE FROM transcripts WHERE cache_key = ?", (cache_key,))

    def prune(self) -> None:
        """Enforce MAX_CACHE_ENTRIES by evicting the oldest rows."""
        count = self._db.query_one("SELECT COUNT(*) FROM transcripts")[0]
        if count > self._s.max_cache_entries:
            self._db.execute(
                "DELETE FROM transcripts WHERE cache_key IN ("
                "  SELECT cache_key FROM transcripts ORDER BY created_at ASC LIMIT ?)",
                (count - self._s.max_cache_entries,))
            logger.info("cache pruned %d entries", count - self._s.max_cache_entries)

    # ------------------------------------------------------------ metadata

    def get_metadata(self, video_id: str) -> dict | None:
        if not self._s.cache_enabled:
            return None
        row = self._db.query_one("SELECT payload, fetched_at FROM metadata WHERE video_id = ?", (video_id,))
        if not row or self._expired(row[1]):
            return None
        return self._db.loads(row[0])

    def put_metadata(self, video_id: str, meta: dict) -> None:
        if not self._s.cache_enabled:
            return
        self._db.execute(
            "INSERT OR REPLACE INTO metadata (video_id, payload, fetched_at) VALUES (?,?,?)",
            (video_id, self._db.dumps(meta), self._db.now()))

    # ------------------------------------------------------------ internals

    def _expired(self, created_at: float) -> bool:
        # ttl 0 -> expire immediately; negative -> never expire
        return self._s.cache_ttl_days >= 0 and \
            (self._db.now() - created_at) >= self._s.cache_ttl_days * 86400
