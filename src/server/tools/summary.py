"""youtube_generate_summary, key moments, topics, and transcript comparison."""
from __future__ import annotations

from src.server import context
from src.server.tools import common
from src.transcript.chapters import from_description, from_metadata, heuristic_chapters
from src.transcript.compare import compare_payloads, render_compare
from src.transcript.summarize import (build_summary, extract_topics, key_moments,
                                      render_key_moments, render_topics)
from src.utils.errors import ErrorCode, YoutubeMcpError
from src.youtube.url_parser import parse_video_ref

_mcp = context.mcp

_STYLES = ("executive", "detailed", "bullets", "key_takeaways", "chapter_summaries",
           "action_items", "quotes", "all")


def _chapters_for(payload: dict) -> list[dict]:
    snap = payload.get("snapshot") or {}
    meta = context.repo.get_metadata(payload.get("video_id", "")) or snap
    return from_metadata(meta) or from_description(meta) or \
        heuristic_chapters(payload.get("segments", []), duration=payload.get("duration"))


@_mcp.tool()
async def youtube_generate_summary(video: str, style: str = "executive",
                                   max_points: int = 6, language: str | None = None) -> str:
    """Generate a structured extractive summary of a cached transcript.

    Styles: executive | detailed | bullets | key_takeaways | chapter_summaries |
    action_items | quotes | all. Summaries are transparent term-frequency heuristics
    (labeled as such) -- for real reasoning, read the transcript itself via
    youtube_get_transcript / youtube_search_transcript.

    Args:
        video: YouTube URL or 11-character video ID.
        style: Summary style (above) or 'all'.
        max_points: Max bullets/points per section.
        language: Cached language variant.
    """
    try:
        if style not in _STYLES:
            raise YoutubeMcpError(ErrorCode.INVALID_ARGUMENT,
                                  f"style must be one of {_STYLES}, got {style!r}")
        payload, _ = common.resolve_cached(context.repo, video, language)
        chapters = _chapters_for(payload) if style in ("chapter_summaries", "all") else None
        text = build_summary(payload, chapters, style, max_points)
        return common.enforce_limit(text, context.settings.max_response_chars)
    except YoutubeMcpError as e:
        return common.error_response(e)
    except Exception as e:
        return common.internal_error(e)


@_mcp.tool()
async def youtube_find_key_moments(video: str, max_results: int = 12,
                                   language: str | None = None) -> str | dict:
    """Find noteworthy moments (conclusions, demos, announcements, key points) by scanning
    a cached transcript for cue phrases. Heuristic detection, honestly labeled -- use the
    timestamps to jump to the real content.

    Args:
        video: YouTube URL or 11-character video ID.
        max_results: Max moments returned.
        language: Cached language variant.
    """
    try:
        payload, _ = common.resolve_cached(context.repo, video, language)
        moments = key_moments(payload, max_results)
        if isinstance(moments, list) and not moments:
            return {"moments": [], "message": "No cue-phrase moments detected (heuristic scan)."}
        return render_key_moments(moments, (payload.get("snapshot") or {}).get("title"))
    except YoutubeMcpError as e:
        return common.error_response(e)
    except Exception as e:
        return common.internal_error(e)


@_mcp.tool()
async def youtube_extract_topics(video: str, top: int = 6,
                                 language: str | None = None) -> str | dict:
    """Build a timestamped topic map from a cached transcript (top terms per chapter or
    per 10-minute window). Term-frequency heuristic; useful as a navigation index.

    Args:
        video: YouTube URL or 11-character video ID.
        top: Terms per window.
        language: Cached language variant.
    """
    try:
        payload, _ = common.resolve_cached(context.repo, video, language)
        chapters = _chapters_for(payload)
        topics = extract_topics(payload, chapters, top)
        return render_topics(topics, (payload.get("snapshot") or {}).get("title"))
    except YoutubeMcpError as e:
        return common.error_response(e)
    except Exception as e:
        return common.internal_error(e)


@_mcp.tool()
async def youtube_compare_transcripts(video: str, source_a: str | None = None,
                                      source_b: str | None = None) -> str | dict:
    """Compare two cached transcripts of the same video (e.g. YouTube auto captions vs
    whisper) and show where they differ. Requires 2+ cached versions.

    Args:
        video: YouTube URL or 11-character video ID.
        source_a: Optional filter: 'youtube_manual' | 'youtube_auto' | 'whisper'.
        source_b: Optional filter (same values).
    """
    try:
        ref = parse_video_ref(video)
        versions = context.repo.versions(ref.video_id)
        if len(versions) < 2:
            raise YoutubeMcpError(
                ErrorCode.NOT_FOUND,
                f"Only {len(versions)} cached transcript version(s); need >= 2 to compare.",
                hint="Run youtube_transcribe twice with different settings, e.g. once normally "
                     "(captions) and once with force_retranscribe=true (whisper).")

        def pick(idx: int, want: str | None) -> dict | None:
            if not want:
                payload = context.repo.get(versions[idx]["cache_key"])
                return payload
            for v in versions:
                if v["source"] == want:
                    return context.repo.get(v["cache_key"])
            return None

        a = pick(0, source_a) or pick(0, None)
        b = pick(1, source_b) or pick(1, None)
        if not a or not b or a is b:
            raise YoutubeMcpError(ErrorCode.NOT_FOUND,
                                  "Could not load two distinct transcript versions to compare.")
        result = compare_payloads(a, b)
        return render_compare(result)
    except YoutubeMcpError as e:
        return common.error_response(e)
    except Exception as e:
        return common.internal_error(e)
