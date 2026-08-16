import pytest

from src.transcript import formatter
from src.utils.errors import ErrorCode, YoutubeMcpError


@pytest.fixture
def payload():
    return {
        "video_id": "abc12345678",
        "transcript_source": "youtube_auto",
        "language": "en",
        "model": "",
        "duration": 400.0,
        "created_at": 1726000000.0,
        "segment_count": 2,
        "snapshot": {"title": "My Video", "channel": "Chan", "url": "https://youtu.be/abc12345678"},
        "segments": [
            {"id": 0, "start": 382.41, "end": 389.72, "text": "First segment."},
            {"id": 1, "start": 389.72, "end": 395.0, "text": "Second segment."},
        ],
    }


def test_compact(payload):
    out = formatter.render_compact(payload, payload["segments"])
    assert "Video: My Video" in out
    assert "[00:06:22] First segment." in out
    assert "Transcript source: youtube_auto" in out


def test_detailed(payload):
    out = formatter.render_detailed(payload, payload["segments"])
    assert "(#0)" in out and "->" in out


def test_plain(payload):
    out = formatter.render(payload, payload["segments"], "compact", include_timestamps=False)
    assert "[00:06:22]" not in out
    assert "First segment." in out


def test_srt(payload):
    out = formatter.render_srt(payload, payload["segments"])
    assert "1\n00:06:22,410 --> 00:06:29,720\nFirst segment." in out


def test_vtt(payload):
    out = formatter.render_vtt(payload, payload["segments"])
    assert out.startswith("WEBVTT")
    assert "00:06:22.410 --> 00:06:29.720" in out


def test_mmss_style(payload):
    out = formatter.render_compact(payload, payload["segments"], ts_style="mmss")
    assert "[6:22]" in out


def test_unknown_format(payload):
    with pytest.raises(ValueError):
        formatter.render(payload, payload["segments"], "bogus")
