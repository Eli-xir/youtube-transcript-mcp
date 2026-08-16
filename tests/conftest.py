"""Shared fixtures: isolated settings, fake YouTube client, fake provider."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cache.repository import TranscriptRepository          # noqa: E402
from src.config.settings import Settings                        # noqa: E402
from src.transcription.pipeline import TranscriptionPipeline    # noqa: E402
from src.transcription.provider import (ProviderResult, ProviderSegment,  # noqa: E402
                                        ProviderWord, TranscriptionProvider)
from src.youtube.captions import CaptionPayload                 # noqa: E402
from src.youtube.url_parser import VideoRef, parse_video_ref    # noqa: E402


def make_settings(tmp_path: Path, **overrides) -> Settings:
    env = {
        "CACHE_DIR": str(tmp_path / "cache"),
        "TEMP_DIR": str(tmp_path / "tmp"),
        "CACHE_ENABLED": "true",
        "LOG_LEVEL": "WARNING",
    }
    env.update({k: str(v) for k, v in overrides.items()})
    return Settings.from_env(env)


META = {
    "video_id": "dQw4w9WgXcQ",
    "title": "Test Video",
    "channel": "Test Channel",
    "channel_id": "UC123",
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "duration": 60.0,
    "upload_date": "2009-10-25",
    "description": "0:00 Intro\n0:30 Main part\n",
    "thumbnail": None,
    "view_count": 1,
    "like_count": 1,
    "language": "en",
    "is_live": False,
    "chapters": None,
    "caption_languages": {"manual": ["en"], "auto": ["en", "es"]},
}


class FakeClient:
    """In-memory YouTube client -- no network."""

    def __init__(self, captions: CaptionPayload | None = None,
                 provider_error: Exception | None = None):
        self.captions = captions
        self.provider_error = provider_error
        self.downloaded: list[str] = []
        self.meta = dict(META)

    def fetch_metadata(self, ref: VideoRef) -> dict:
        if isinstance(self.provider_error, Exception) and "meta" in str(self.provider_error):
            raise self.provider_error
        return self.meta

    def get_captions(self, ref: VideoRef, language: str | None = None) -> CaptionPayload | None:
        return self.captions

    def download_audio(self, ref: VideoRef, dest_dir, progress=None) -> Path:
        self.downloaded.append(ref.video_id)
        if self.provider_error:
            raise self.provider_error
        p = dest_dir / "audio.m4a"
        p.write_bytes(b"fakeaudio")
        return p


class FakeProvider(TranscriptionProvider):
    name = "fake-whisper"

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[dict] = []

    def transcribe(self, audio_path, *, language=None, model=None, word_timestamps=False,
                   progress=None, cancel_event=None, deadline=None) -> ProviderResult:
        self.calls.append({"language": language, "model": model,
                           "word_timestamps": word_timestamps})
        if progress:
            progress(1.0)
        if self.error:
            raise self.error
        return ProviderResult(
            segments=[
                ProviderSegment(0.0, 2.5, "Hello world from whisper.",
                                [ProviderWord(0.0, 0.5, "Hello"), ProviderWord(0.5, 1.1, "world")]),
                ProviderSegment(2.5, 5.0, "This is a test transcript."),
                ProviderSegment(5.0, 8.0, "PostgreSQL is a great database."),
            ],
            language="en", language_probability=0.98, model=model or "small")


@pytest.fixture
def settings(tmp_path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def repo(settings) -> TranscriptRepository:
    return TranscriptRepository(settings)


@pytest.fixture
def pipeline_factory(settings, repo):
    def build(captions=None, provider_error=None):
        client = FakeClient(captions=captions, provider_error=provider_error)
        provider = FakeProvider(error=provider_error)
        return TranscriptionPipeline(settings, client, repo, provider=provider), client, provider
    return build


def json3_payload():
    import json
    return CaptionPayload(
        kind="auto", language="en", ext="json3",
        text=json.dumps({"events": [
            {"tStartMs": 0, "dDurationMs": 3000, "segs": [
                {"utf8": "hello", "tOffsetMs": 0},
                {"utf8": "world", "tOffsetMs": 600},
                {"utf8": "today", "tOffsetMs": 1200}]},
            # rolling duplicate of the previous window (auto-caption behavior)
            {"tStartMs": 0, "dDurationMs": 3000, "segs": [
                {"utf8": "hello", "tOffsetMs": 0},
                {"utf8": "world", "tOffsetMs": 600}]},
            {"tStartMs": 3000, "dDurationMs": 3000, "segs": [
                {"utf8": "we", "tOffsetMs": 0},
                {"utf8": "talk", "tOffsetMs": 500},
                {"utf8": "about", "tOffsetMs": 900},
                {"utf8": "PostgreSQL.", "tOffsetMs": 1300}]},
        ]}))
