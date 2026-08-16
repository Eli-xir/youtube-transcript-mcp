"""Long-running transcription job tracking (spec section 12)."""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

TERMINAL = {"complete", "failed", "cancelled"}

STAGES = ["queued", "fetching_metadata", "fetching_captions", "downloading_audio",
          "transcribing", "processing_timestamps", "indexing", "complete", "failed", "cancelled"]


@dataclass
class Job:
    id: str
    video_id: str
    cache_key: str = ""
    status: str = "queued"
    progress: float = 0.0
    message: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error: dict | None = None
    cache_hit: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, status: str | None = None, progress: float | None = None,
               message: str | None = None) -> None:
        with self._lock:
            if status:
                self.status = status
            if progress is not None:
                self.progress = max(0.0, min(1.0, progress))
            if message:
                self.message = message
            self.updated_at = time.time()

    def request_cancel(self) -> None:
        self.cancel_event.set()
        self.update(status="cancelling", message="Cancellation requested...")

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    @property
    def done(self) -> bool:
        return self.status in TERMINAL

    def to_dict(self) -> dict:
        return {
            "job_id": self.id,
            "video_id": self.video_id,
            "status": self.status,
            "progress": round(self.progress, 3),
            "message": self.message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "cache_key": self.cache_key,
        }


class JobManager:
    """In-memory registry of transcription jobs (survives within a server process)."""

    def __init__(self, keep_done: int = 50):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._keep_done = keep_done

    def create(self, video_id: str, cache_key: str = "") -> Job:
        with self._lock:
            # reuse an active job for the same cache key instead of duplicating work
            for job in self._jobs.values():
                if job.video_id == video_id and not job.done and not job.cancelled:
                    if not cache_key or job.cache_key == cache_key:
                        return job
            job = Job(id=uuid.uuid4().hex[:12], video_id=video_id, cache_key=cache_key)
            self._jobs[job.id] = job
            self._cleanup_locked()
            return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if job and not job.done:
            job.request_cancel()
        return job

    def for_video(self, video_id: str) -> list[Job]:
        with self._lock:
            return [j for j in self._jobs.values() if j.video_id == video_id]

    def recent(self, limit: int = 20) -> list[Job]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return jobs[:limit]

    def _cleanup_locked(self) -> None:
        done = [j for j in self._jobs.values() if j.done]
        if len(done) > self._keep_done:
            for j in sorted(done, key=lambda j: j.updated_at)[:len(done) - self._keep_done]:
                self._jobs.pop(j.id, None)
