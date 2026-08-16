"""Strict YouTube URL/ID parsing. All user-supplied refs go through here (SSRF-conscious)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from src.utils.errors import ErrorCode, YoutubeMcpError

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

_ALLOWED_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtu.be", "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com",
}


@dataclass(frozen=True)
class VideoRef:
    video_id: str
    url: str

    @property
    def short_url(self) -> str:
        return f"https://youtu.be/{self.video_id}"


def canonical_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def timestamp_url(video_id: str, seconds: float) -> str:
    return f"https://www.youtube.com/watch?v={video_id}&t={int(max(0, seconds))}s"


def parse_video_ref(value: str) -> VideoRef:
    """Accepts a YouTube URL (watch / youtu.be / shorts / embed / live) or a bare 11-char video ID."""
    v = (value or "").strip()
    if not v:
        raise YoutubeMcpError(ErrorCode.INVALID_URL, "Empty video reference.")

    if _VIDEO_ID_RE.match(v):
        return VideoRef(v, canonical_url(v))

    if not re.match(r"^https?://", v, re.I):
        # tolerate scheme-less youtube links
        if "youtu" in v.lower() and "/" in v:
            v = "https://" + v
        else:
            raise YoutubeMcpError(
                ErrorCode.INVALID_URL, f"Not a YouTube URL or 11-character video ID: {v[:100]!r}",
                hint="Example: https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    try:
        parsed = urlparse(v)
    except ValueError:
        raise YoutubeMcpError(ErrorCode.INVALID_URL, f"Malformed URL: {v[:100]!r}") from None

    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_HOSTS:
        raise YoutubeMcpError(
            ErrorCode.INVALID_URL, f"Host {host!r} is not a YouTube host.",
            hint="Only youtube.com / youtu.be URLs (or a bare video ID) are accepted.")

    path_segments = [p for p in parsed.path.split("/") if p]

    video_id = None
    if host.endswith("youtu.be"):
        if path_segments:
            video_id = path_segments[0]
    elif path_segments and path_segments[0] in ("shorts", "embed", "live", "v"):
        if len(path_segments) >= 2:
            video_id = path_segments[1]
    elif path_segments and path_segments[0] == "watch":
        qs = parse_qs(parsed.query)
        vid = qs.get("v", [None])[0]
        if vid:
            video_id = vid
        elif qs.get("list", [None])[0]:
            raise YoutubeMcpError(
                ErrorCode.PLAYLIST_UNSUPPORTED,
                "This is a playlist URL without a specific video.",
                hint="Open the playlist in a browser, pick a video, and pass its watch?v=... URL or video ID.")

    if "list" in parse_qs(parsed.query) and not video_id:
        raise YoutubeMcpError(
            ErrorCode.PLAYLIST_UNSUPPORTED, "Playlist URLs are not supported.",
            hint="Pass a single video URL (watch?v=...) or an 11-character video ID.")

    if not video_id:
        raise YoutubeMcpError(
            ErrorCode.INVALID_URL, f"Could not extract a video ID from {v[:100]!r}",
            hint="Expected /watch?v=ID, youtu.be/ID, /shorts/ID, /embed/ID or a bare ID.")

    if not _VIDEO_ID_RE.match(video_id):
        raise YoutubeMcpError(
            ErrorCode.INVALID_URL, f"Extracted ID {video_id!r} is not a valid 11-character video ID.")

    return VideoRef(video_id, canonical_url(video_id))
