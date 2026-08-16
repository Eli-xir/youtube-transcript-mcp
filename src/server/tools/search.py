"""youtube_search_transcript: keyword/regex/fuzzy search with context + jump links."""
from __future__ import annotations

from src.server import context
from src.server.tools import common
from src.transcript.search import render_search, search_segments
from src.utils.errors import YoutubeMcpError
from src.youtube.url_parser import parse_video_ref

_mcp = context.mcp


@_mcp.tool()
async def youtube_search_transcript(
    video: str,
    query: str,
    case_sensitive: bool = False,
    max_results: int = 10,
    context_segments: int = 1,
    regex: bool = False,
    fuzzy: bool = False,
    fuzzy_threshold: float = 70.0,
    format: str = "text",
    language: str | None = None,
) -> str | dict:
    """Search inside a cached transcript and get timestamped matches with context.

    Example: find every mention of 'PostgreSQL' -> returns [00:14:32], [01:07:19], ...
    with surrounding lines and clickable timestamp URLs for jumping straight there.

    Args:
        video: YouTube URL or 11-character video ID.
        query: Search text (or regex pattern when regex=True).
        case_sensitive: Case-sensitive literal/regex matching.
        max_results: Max match groups returned.
        context_segments: Surrounding segments shown per match.
        regex: Treat query as a Python regex.
        fuzzy: Approximate matching (good for exact-ish quotes and misspellings).
        fuzzy_threshold: 0-100 similarity cutoff for fuzzy matching.
        format: 'text' (readable) or 'json' (structured).
        language: Cached language variant to search.
    """
    try:
        payload, video_id = common.resolve_cached(context.repo, video, language)
        result = search_segments(
            video_id, payload.get("segments", []), query,
            case_sensitive=case_sensitive, regex=regex, fuzzy=fuzzy,
            fuzzy_threshold=fuzzy_threshold, max_results=max_results,
            context=max(0, context_segments))
        if format == "json":
            result["title"] = (payload.get("snapshot") or {}).get("title")
            return result
        text = render_search(result, (payload.get("snapshot") or {}).get("title"))
        return common.enforce_limit(text, context.settings.max_response_chars)
    except YoutubeMcpError as e:
        return common.error_response(e)
    except Exception as e:
        return common.internal_error(e)
