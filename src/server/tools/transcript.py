"""youtube_get_transcript + youtube_get_segment: cached-transcript retrieval."""
from __future__ import annotations

from src.server import context
from src.server.tools import common
from src.transcript import chunker
from src.utils.errors import YoutubeMcpError
from src.youtube.url_parser import parse_video_ref

_mcp = context.mcp

DEFAULT_MAX_SEGMENTS = 200


@_mcp.tool()
async def youtube_get_transcript(
    video: str,
    start: str | float | None = None,
    end: str | float | None = None,
    offset: int = 0,
    max_segments: int = DEFAULT_MAX_SEGMENTS,
    format: str = "compact",
    timestamp_format: str = "hhmmss",
    language: str | None = None,
    include_timestamps: bool = True,
) -> str | dict:
    """Retrieve a cached transcript (fast; no re-fetching). Use after youtube_transcribe.

    Args:
        video: YouTube URL or 11-character video ID.
        start: Start position -- seconds ('750') or timestamp ('12:30', '01:02:03').
        end: End position, same formats.
        offset: Skip this many segments (pagination).
        max_segments: Cap on returned segments (pagination).
        format: 'compact' | 'detailed' | 'json' | 'srt' | 'vtt'.
        timestamp_format: 'hhmmss' | 'mmss' | 'seconds'.
        language: Cached language variant to select (e.g. 'en', 'de').
        include_timestamps: False -> plain text.
    """
    try:
        payload, video_id = common.resolve_cached(context.repo, video, language)
        start_s = common.parse_ts_param(start, "start")
        end_s = common.parse_ts_param(end, "end")
        if start_s is not None and end_s is not None and end_s <= start_s:
            raise YoutubeMcpError("INVALID_ARGUMENT", f"end ({end}) must be after start ({start}).")
        if offset < 0:
            raise YoutubeMcpError("INVALID_ARGUMENT", f"offset must be >= 0, got {offset}.")
        if max_segments <= 0:
            raise YoutubeMcpError("INVALID_ARGUMENT", f"max_segments must be > 0, got {max_segments}.")

        all_segments = payload.get("segments", [])
        window = chunker.slice_segments(all_segments, start_s, end_s)
        seg_offset = 0 if (start_s is not None or end_s is not None) else offset
        shown = chunker.paginate_segments(window, seg_offset, max_segments)
        footer = chunker.chunk_footer(payload, shown, len(window), seg_offset)
        return common.render_response(payload, shown, format, timestamp_format,
                                      include_timestamps, context.settings.max_response_chars,
                                      footer=footer)
    except YoutubeMcpError as e:
        return common.error_response(e)
    except Exception as e:
        return common.internal_error(e)


@_mcp.tool()
async def youtube_get_segment(
    video: str,
    start: str | float,
    end: str | float,
    format: str = "compact",
    timestamp_format: str = "hhmmss",
    language: str | None = None,
) -> str | dict:
    """Retrieve an exact transcript interval, e.g. start='01:22:15' end='01:27:30'.

    Args:
        video: YouTube URL or 11-character video ID.
        start: Interval start -- seconds or MM:SS / HH:MM:SS (required).
        end: Interval end -- same formats (required).
        format: 'compact' | 'detailed' | 'json' | 'srt' | 'vtt'.
        timestamp_format: 'hhmmss' | 'mmss' | 'seconds'.
        language: Cached language variant to select.
    """
    try:
        payload, video_id = common.resolve_cached(context.repo, video, language)
        start_s = common.parse_ts_param(start, "start")
        end_s = common.parse_ts_param(end, "end")
        if start_s is None or end_s is None:
            raise YoutubeMcpError("INVALID_ARGUMENT", "Both start and end are required.")
        if end_s <= start_s:
            raise YoutubeMcpError("INVALID_ARGUMENT", f"end ({end}) must be after start ({start}).")
        window = chunker.slice_segments(payload.get("segments", []), start_s, end_s)
        if not window:
            raise YoutubeMcpError(
                "NOT_FOUND",
                f"No transcript segments overlap [{start} .. {end}]. "
                f"Transcript covers 0 to {payload.get('duration', 0):.0f}s.",
                hint="Check youtube_video_metadata for the real duration.")
        return common.render_response(payload, window, format, timestamp_format, True,
                                      context.settings.max_response_chars)
    except YoutubeMcpError as e:
        return common.error_response(e)
    except Exception as e:
        return common.internal_error(e)
