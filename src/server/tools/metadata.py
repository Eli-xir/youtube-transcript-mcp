"""youtube_video_metadata: video info + caption availability + transcript status."""
from __future__ import annotations

import asyncio

from src.server import context
from src.server.tools import common
from src.utils.errors import YoutubeMcpError
from src.utils.timestamps import human_duration
from src.youtube.url_parser import parse_video_ref

_mcp = context.mcp


@_mcp.tool()
async def youtube_video_metadata(url: str, refresh: bool = False) -> dict:
    """Get YouTube video metadata: title, channel, duration, upload date, description,
    thumbnail, available caption languages, cached-transcript availability and job status.

    Args:
        url: YouTube video URL or 11-character video ID.
        refresh: Bypass the metadata cache and re-fetch.
    """
    try:
        ref = parse_video_ref(url)
        meta = None if refresh else context.repo.get_metadata(ref.video_id)
        if meta is None:
            meta = await asyncio.to_thread(context.client.fetch_metadata, ref)
            context.repo.put_metadata(ref.video_id, meta)

        versions = context.repo.versions(ref.video_id)
        active = [j.to_dict() for j in context.jobs.for_video(ref.video_id) if not j.done]
        caps = meta.get("caption_languages") or {}
        return {
            "video_id": meta.get("video_id"),
            "title": meta.get("title"),
            "channel": meta.get("channel"),
            "channel_id": meta.get("channel_id"),
            "url": meta.get("url"),
            "duration": meta.get("duration"),
            "duration_hms": human_duration(meta.get("duration") or 0),
            "upload_date": meta.get("upload_date"),
            "description": (meta.get("description") or "")[:1500],
            "thumbnail": meta.get("thumbnail"),
            "view_count": meta.get("view_count"),
            "is_live": meta.get("is_live"),
            "language": meta.get("language"),
            "captions_available": bool(caps.get("manual") or caps.get("auto")),
            "manual_caption_languages": (caps.get("manual") or [])[:60],
            "auto_caption_languages": (caps.get("auto") or [])[:60],
            "transcript_cached": bool(versions),
            "cached_transcript_versions": versions,
            "processing_status": active[0]["status"] if active else
                ("complete" if versions else "not_transcribed"),
        }
    except YoutubeMcpError as e:
        return common.error_response(e)
    except Exception as e:
        return common.internal_error(e)
