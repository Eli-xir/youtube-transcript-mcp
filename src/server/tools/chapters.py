"""youtube_list_chapters: YouTube chapters, description-parsed, or heuristic."""
from __future__ import annotations

import asyncio

from src.server import context
from src.server.tools import common
from src.transcript.chapters import from_description, from_metadata, heuristic_chapters, render_chapters
from src.utils.errors import ErrorCode, YoutubeMcpError
from src.youtube.url_parser import parse_video_ref

_mcp = context.mcp


@_mcp.tool()
async def youtube_list_chapters(url: str, ai_chapters: bool = False,
                                format: str = "text") -> str | dict:
    """List video chapters. Priority: YouTube-native chapters > description timestamps >
    (optionally) heuristic topic-window chapters.

    Args:
        url: YouTube video URL or 11-character video ID.
        ai_chapters: When no real chapters exist, generate heuristic topic-window chapters
            from the cached transcript (term-frequency titles, labeled 'heuristic' -- not an LLM;
            requires youtube_transcribe to have run).
        format: 'text' or 'json'.
    """
    try:
        ref = parse_video_ref(url)
        meta = context.repo.get_metadata(ref.video_id)
        if meta is None:
            meta = await asyncio.to_thread(context.client.fetch_metadata, ref)
            context.repo.put_metadata(ref.video_id, meta)

        chapters = from_metadata(meta) or from_description(meta)
        source = chapters[0]["source"] if chapters else None

        if chapters is None and ai_chapters:
            payload = context.repo.find_latest(ref.video_id)
            if payload is None:
                raise YoutubeMcpError(
                    ErrorCode.NOT_FOUND, "No cached transcript for heuristic chaptering.",
                    hint="Call youtube_transcribe(url=...) first.")
            chapters = heuristic_chapters(payload.get("segments", []),
                                          duration=payload.get("duration"))
            source = "heuristic"

        if not chapters:
            return {"video_id": ref.video_id, "chapters": [],
                    "message": "No chapters found (no YouTube chapters, none parsed from description).",
                    "hint": "Run youtube_transcribe then retry with ai_chapters=true for heuristic chapters."}
        if format == "json":
            return {"video_id": ref.video_id, "source": source, "chapters": chapters}
        return render_chapters(chapters, meta.get("title"))
    except YoutubeMcpError as e:
        return common.error_response(e)
    except Exception as e:
        return common.internal_error(e)
