"""Shared helpers for MCP tool implementations."""
from __future__ import annotations

import logging

from src.cache.repository import TranscriptRepository
from src.transcript import chunker, formatter
from src.utils.errors import ErrorCode, YoutubeMcpError
from src.utils.timestamps import parse_timestamp
from src.youtube.url_parser import parse_video_ref

logger = logging.getLogger(__name__)


def error_response(e: YoutubeMcpError) -> dict:
    logger.warning("tool error: %s", e.to_dict())
    return e.to_dict()


def internal_error(e: Exception) -> dict:
    logger.exception("unexpected tool failure")
    return {"error": ErrorCode.INTERNAL_ERROR,
            "message": "Unexpected internal error (details in server logs).",
            "retryable": False}


def parse_ts_param(value, name: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return parse_timestamp(value)
    except ValueError as e:
        raise YoutubeMcpError(ErrorCode.INVALID_ARGUMENT,
                              f"Invalid {name}={value!r}: use seconds or MM:SS / HH:MM:SS.") from e


def resolve_cached(repo: TranscriptRepository, video: str, language: str | None = None) -> tuple[dict, str]:
    """Find the cached transcript for a video. Raises NOT_FOUND with a helpful hint."""
    ref = parse_video_ref(video)
    payload = repo.find_latest(ref.video_id, language)
    if payload is None:
        versions = repo.versions(ref.video_id)
        if versions:
            raise YoutubeMcpError(
                ErrorCode.NOT_FOUND,
                f"No cached transcript for {ref.video_id} matching language={language or 'any'}; "
                f"cached languages: {sorted({v['language'] for v in versions})}.",
                hint="Call youtube_transcribe with that language first.")
        raise YoutubeMcpError(
            ErrorCode.NOT_FOUND,
            f"No transcript cached for {ref.video_id}.",
            hint="Call youtube_transcribe(url=...) first -- it caches for all other tools.")
    return payload, ref.video_id


def enforce_limit(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_nl = cut.rfind("\n")
    if last_nl > limit // 2:
        cut = cut[:last_nl]
    return (cut +
            f"\n\n[OUTPUT TRUNCATED at {limit} chars. Use youtube_get_transcript with start/end, "
            f"offset pagination, or format='json' + smaller ranges.]")
_VALID_FMT = {"compact", "detailed", "json", "srt", "vtt"}
_VALID_TS = {"hhmmss", "mmss", "seconds"}


def validate_formats(fmt: str, ts_style: str) -> None:
    if fmt not in _VALID_FMT:
        raise YoutubeMcpError(ErrorCode.INVALID_ARGUMENT,
                              f"format must be one of {sorted(_VALID_FMT)}, got {fmt!r}")
    if ts_style not in _VALID_TS:
        raise YoutubeMcpError(ErrorCode.INVALID_ARGUMENT,
                              f"timestamp_format must be one of {sorted(_VALID_TS)}, got {ts_style!r}")


def render_response(payload: dict, segments: list[dict], fmt: str, ts_style: str,
                    include_timestamps: bool, limit: int,
                    header_extra: list[str] | None = None, footer: str | None = None):
    """Render segments in the requested output format (dict for json, str otherwise)."""
    validate_formats(fmt, ts_style)
    if fmt == "json":
        out = dict(payload)
        out["segments"] = segments
        return out
    text = formatter.render(payload, segments, fmt, ts_style, include_timestamps,
                            header_extra, footer)
    return enforce_limit(text, limit)
