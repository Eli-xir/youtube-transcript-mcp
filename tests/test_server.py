"""Server-level tests: tool registration, schema sanity, tool behavior with fakes."""
import asyncio
import time

import pytest

from src.transcription.pipeline import PipelineResult
from src.transcript.models import Segment, Transcript

EXPECTED_TOOLS = {
    "youtube_transcribe", "youtube_get_transcript", "youtube_search_transcript",
    "youtube_video_metadata", "youtube_get_segment", "youtube_list_chapters",
    "youtube_generate_summary", "youtube_find_key_moments", "youtube_extract_topics",
    "youtube_compare_transcripts", "youtube_transcription_status", "youtube_cancel_transcription",
}


@pytest.fixture(scope="module")
def app():
    from src.server.mcp_server import create_app
    return create_app()


def test_all_tools_registered(app):
    tools = asyncio.run(app.list_tools())
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS


def test_transcribe_schema_documents_options(app):
    tools = {t.name: t for t in asyncio.run(app.list_tools())}
    props = tools["youtube_transcribe"].inputSchema["properties"]
    for p in ("url", "language", "model", "include_timestamps", "include_speakers",
              "word_timestamps", "force_retranscribe"):
        assert p in props
    assert tools["youtube_transcribe"].inputSchema["required"] == ["url"]


def test_resource_templates_and_prompts(app):
    templates = {str(t.uriTemplate) for t in asyncio.run(app.list_resource_templates())}
    assert templates == {"youtube://video/{video_id}/transcript",
                         "youtube://video/{video_id}/metadata",
                         "youtube://video/{video_id}/chapters"}
    prompts = {p.name for p in asyncio.run(app.list_prompts())}
    assert prompts == {"analyze_youtube_video", "research_youtube_video", "summarize_youtube_video"}


# ------------------------------------------------------------------ helpers


def make_payload():
    return {
        "video_id": "dQw4w9WgXcQ", "language": "en", "transcript_source": "youtube_auto",
        "model": "", "duration": 30.0, "created_at": time.time(), "segment_count": 3,
        "has_word_timestamps": False, "chapters": [], "notes": [],
        "snapshot": {"title": "Test Video", "channel": "Chan",
                     "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "duration": 30.0},
        "segments": [
            {"id": 0, "start": 0.0, "end": 5.0, "timestamp": "00:00:00", "text": "hello world"},
            {"id": 1, "start": 5.0, "end": 10.0, "timestamp": "00:00:05", "text": "postgresql rocks"},
            {"id": 2, "start": 10.0, "end": 15.0, "timestamp": "00:00:10", "text": "goodbye now"},
        ],
    }


class FakeRepo:
    def __init__(self, payload):
        self.payload = payload

    def get(self, key):
        return self.payload

    def find_latest(self, video_id, language=None):
        return self.payload

    def versions(self, video_id):
        return [{"cache_key": "k1", "language": "en", "source": "youtube_auto", "model": "", "created_at": 1},
                {"cache_key": "k2", "language": "en", "source": "whisper", "model": "small", "created_at": 2}]

    def get_metadata(self, video_id):
        return {"video_id": video_id, "title": "Test Video", "duration": 30.0,
                "description": "0:00 Intro\n0:10 End\n",
                "caption_languages": {"manual": ["en"], "auto": []}, "chapters": None}


class FakePipeline:
    def __init__(self):
        self.calls = []

    def run(self, request):
        self.calls.append(request)
        tr = Transcript(video_id="dQw4w9WgXcQ", language="en", source="youtube_auto", model="",
                        segments=[Segment(0, 0.0, 5.0, "hello world")], duration=30.0)
        request.job.cache_key = "k1"
        request.job.update(status="complete", progress=1.0, message="done")
        return PipelineResult(tr, {"video_id": "dQw4w9WgXcQ"}, False, 0.1, "k1")


@pytest.fixture
def patched(monkeypatch):
    from src.server import context
    payload = make_payload()
    monkeypatch.setattr(context, "repo", FakeRepo(payload))
    fake_pipeline = FakePipeline()
    monkeypatch.setattr(context, "pipeline", fake_pipeline)
    return context, payload, fake_pipeline


# ------------------------------------------------------------------ tools


def test_transcribe_tool_returns_compact(patched):
    from src.server.tools.transcribe import youtube_transcribe
    ctx, payload, _ = patched
    out = asyncio.run(youtube_transcribe("https://youtu.be/dQw4w9WgXcQ"))
    assert "[00:00:00] hello world" in out
    assert "Transcript source: youtube_auto" in out


def test_transcribe_tool_invalid_url(patched):
    from src.server.tools.transcribe import youtube_transcribe
    out = asyncio.run(youtube_transcribe("https://example.com/x"))
    assert out["error"] == "INVALID_URL" and out["retryable"] is False


def test_get_transcript_slices(patched):
    from src.server.tools.transcript import youtube_get_transcript
    out = asyncio.run(youtube_get_transcript("dQw4w9WgXcQ", start="0:05", end="0:12"))
    assert "postgresql rocks" in out and "hello world" not in out


def test_get_transcript_pagination(patched):
    from src.server.tools.transcript import youtube_get_transcript
    out = asyncio.run(youtube_get_transcript("dQw4w9WgXcQ", offset=1, max_segments=1))
    assert "postgresql rocks" in out and "of 3 segments" in out


def test_get_transcript_json(patched):
    from src.server.tools.transcript import youtube_get_transcript
    out = asyncio.run(youtube_get_transcript("dQw4w9WgXcQ", format="json"))
    assert out["segments"][0]["text"] == "hello world"


def test_get_segment_requires_range(patched):
    from src.server.tools.transcript import youtube_get_segment
    out = asyncio.run(youtube_get_segment("dQw4w9WgXcQ", start="0:05", end="0:00:05"))
    assert out["error"] == "INVALID_ARGUMENT"


def test_search_tool(patched):
    from src.server.tools.search import youtube_search_transcript
    out = asyncio.run(youtube_search_transcript("dQw4w9WgXcQ", "postgresql"))
    assert "1 match" in out and "postgresql rocks" in out


def test_summary_tool(patched):
    from src.server.tools.summary import youtube_generate_summary
    out = asyncio.run(youtube_generate_summary("dQw4w9WgXcQ", style="executive"))
    assert "Extractive summary" in out


def test_metadata_tool(patched):
    from src.server.tools.metadata import youtube_video_metadata
    out = asyncio.run(youtube_video_metadata("dQw4w9WgXcQ"))
    assert out["title"] == "Test Video"
    assert out["transcript_cached"] is True
    assert out["processing_status"] == "complete"


def test_chapters_tool(patched):
    from src.server.tools.chapters import youtube_list_chapters
    out = asyncio.run(youtube_list_chapters("dQw4w9WgXcQ"))
    assert "Intro" in out and "description" in out


def test_status_tool_lists(patched):
    from src.server.tools.jobs import youtube_transcription_status
    out = asyncio.run(youtube_transcription_status())
    assert "jobs" in out
    out2 = asyncio.run(youtube_transcription_status(job_id="nope"))
    assert out2["error"] == "NOT_FOUND"
