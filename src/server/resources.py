"""MCP resources: stable URIs for transcripts, metadata and chapters (spec section 14)."""
from __future__ import annotations

from src.server import context
from src.transcript import formatter
from src.transcript.chapters import from_description, from_metadata, heuristic_chapters

_mcp = context.mcp


def _cached_transcript(video_id: str) -> dict | None:
    return context.repo.find_latest(video_id)


@_mcp.resource("youtube://video/{video_id}/transcript")
def transcript_resource(video_id: str) -> str:
    """Full transcript (compact format) for a video; error text when not cached."""
    payload = _cached_transcript(video_id)
    if payload is None:
        return (f"No transcript cached for {video_id}. "
                f"Call the youtube_transcribe tool first, then re-read this resource.")
    return formatter.render_compact(payload, payload.get("segments", []))


@_mcp.resource("youtube://video/{video_id}/metadata")
def metadata_resource(video_id: str) -> str:
    """Video metadata as JSON (from cache; fetch via the tool if uncached)."""
    meta = context.repo.get_metadata(video_id)
    if meta is None:
        return (f"No metadata cached for {video_id}. "
                f"Call youtube_video_metadata(url=...) first.")
    import json
    return json.dumps(meta, ensure_ascii=False, indent=2)


@_mcp.resource("youtube://video/{video_id}/chapters")
def chapters_resource(video_id: str) -> str:
    """Chapters as JSON: YouTube-native > description-parsed > heuristic (if transcript cached)."""
    import json
    meta = context.repo.get_metadata(video_id)
    chapters = from_metadata(meta or {}) or from_description(meta or {})
    source = chapters[0]["source"] if chapters else None
    if chapters is None:
        payload = _cached_transcript(video_id)
        if payload:
            chapters = heuristic_chapters(payload.get("segments", []),
                                          duration=payload.get("duration"))
            source = "heuristic"
    if not chapters:
        return json.dumps({"video_id": video_id, "chapters": []})
    return json.dumps({"video_id": video_id, "source": source, "chapters": chapters},
                      ensure_ascii=False, indent=2)
