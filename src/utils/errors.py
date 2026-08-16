"""Structured, LLM-friendly errors. Never leak raw stack traces to MCP responses."""
from __future__ import annotations

import re


class ErrorCode:
    INVALID_URL = "INVALID_URL"
    PLAYLIST_UNSUPPORTED = "PLAYLIST_UNSUPPORTED"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    VIDEO_UNAVAILABLE = "VIDEO_UNAVAILABLE"
    VIDEO_PRIVATE = "VIDEO_PRIVATE"
    MEMBERS_ONLY = "MEMBERS_ONLY"
    AGE_RESTRICTED = "AGE_RESTRICTED"
    GEO_BLOCKED = "GEO_BLOCKED"
    BOT_CHECK = "BOT_CHECK"
    RATE_LIMITED = "RATE_LIMITED"
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    CAPTIONS_UNAVAILABLE = "CAPTIONS_UNAVAILABLE"
    TRANSCRIPTION_FAILED = "TRANSCRIPTION_FAILED"
    MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
    DISK_SPACE = "DISK_SPACE"
    VIDEO_TOO_LONG = "VIDEO_TOO_LONG"
    DOWNLOAD_TOO_LARGE = "DOWNLOAD_TOO_LARGE"
    UNSUPPORTED_LANGUAGE = "UNSUPPORTED_LANGUAGE"
    NOT_FOUND = "NOT_FOUND"
    CANCELLED = "CANCELLED"
    CONFIG_ERROR = "CONFIG_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class YoutubeMcpError(Exception):
    """Error carrying a machine-readable code, message, retryability and an optional hint."""

    def __init__(self, code: str, message: str, retryable: bool = False,
                 hint: str | None = None, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.hint = hint
        self.details = details or {}

    def to_dict(self) -> dict:
        d = {"error": self.code, "message": self.message, "retryable": self.retryable}
        if self.hint:
            d["hint"] = self.hint
        if self.details:
            d.update(self.details)
        return d


# (pattern, code, retryable, hint) -- order matters, most specific first
_YTDLP_PATTERNS = [
    (r"private video", ErrorCode.VIDEO_PRIVATE, False,
     "The uploader made this video private. There is no way to access it."),
    (r"members[- ]only|join this channel", ErrorCode.MEMBERS_ONLY, False,
     "This video is members-only. Requires an authenticated YouTube session, which this server does not hold."),
    (r"sign in to confirm your age|age.{0,12}restrict", ErrorCode.AGE_RESTRICTED, False,
     "Age-restricted video. Requires YouTube cookies which this server does not hold."),
    (r"video unavailable|has been removed|does not exist|404.{0,20}not found|removed by the uploader",
     ErrorCode.VIDEO_UNAVAILABLE, False, "The video may be deleted or the ID is wrong."),
    (r"not available in your country|geo.{0,10}restrict|blocked it in your country",
     ErrorCode.GEO_BLOCKED, False, "The uploader blocked this video in your region."),
    (r"sign in to confirm you.{0,4}re not a bot|verify you.{0,4}re a human|confirm you.{0,4}re not a bot",
     ErrorCode.BOT_CHECK, True,
     "YouTube flagged this client as a bot. Wait and retry, or configure cookies in yt-dlp."),
    (r"\b429\b|too many requests", ErrorCode.RATE_LIMITED, True,
     "YouTube rate-limited this IP. Wait a few minutes before retrying."),
    (r"unable to download webpage|network|connection|getaddrinfo|timed out|timeout|ssl",
     ErrorCode.NETWORK_ERROR, True, "Transient network problem. Retry."),
    (r"no space|disk full|not enough disk", ErrorCode.DISK_SPACE, False,
     "Free disk space or lower MAX_DOWNLOAD_SIZE_MB."),
]


def map_ytdlp_error(exc: Exception) -> YoutubeMcpError:
    """Map a yt-dlp DownloadError to a structured error using its message."""
    msg = str(exc)
    low = msg.lower()
    for pattern, code, retryable, hint in _YTDLP_PATTERNS:
        if re.search(pattern, low):
            return YoutubeMcpError(code, msg.split("\n")[0][:300], retryable=retryable, hint=hint)
    return YoutubeMcpError(ErrorCode.DOWNLOAD_FAILED, msg.split("\n")[0][:300], retryable=True,
                           hint="yt-dlp could not process this video. It may work in a browser but not for automated access.")
