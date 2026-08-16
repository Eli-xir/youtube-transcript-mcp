"""youtube_transcribe: the entry-point tool (with background jobs for long videos)."""
from __future__ import annotations

import asyncio
import logging

from src.server import context
from src.server.tools import common
from src.transcription.pipeline import TranscribeRequest
from src.utils.errors import ErrorCode, YoutubeMcpError
from src.youtube.url_parser import parse_video_ref

logger = logging.getLogger(__name__)

_mcp = context.mcp


async def _execute_job(job, request: TranscribeRequest):
    try:
        result = await asyncio.to_thread(context.pipeline.run, request)
        job.update(status="complete", progress=1.0,
                   message=f"Done ({'cache hit' if result.cache_hit else 'generated'} in {result.elapsed_s:.1f}s)")
        job.cache_hit = result.cache_hit
    except YoutubeMcpError as e:
        if e.code == ErrorCode.CANCELLED:
            job.update(status="cancelled", message="Cancelled.")
        else:
            job.update(status="failed", message=e.message)
            job.error = e.to_dict()
    except Exception as e:
        logger.exception("job %s crashed", job.id)
        job.update(status="failed", message=str(e)[:200])
        job.error = common.internal_error(e)


@_mcp.tool()
async def youtube_transcribe(
    url: str,
    language: str | None = None,
    model: str | None = None,
    include_timestamps: bool = True,
    include_speakers: bool = False,
    word_timestamps: bool = False,
    force_retranscribe: bool = False,
    prefer_captions: bool | None = None,
    format: str = "compact",
    timestamp_format: str = "hhmmss",
    wait: bool = True,
    wait_timeout_seconds: float = 90.0,
) -> str | dict:
    """Transcribe a YouTube video and return a timestamped transcript (cached for all other tools).

    Caption-first: uses existing YouTube captions when usable (fast, free) and falls back to
    local faster-whisper transcription when missing. The result is cached; later calls and all
    other youtube_* tools reuse it.

    Args:
        url: YouTube video URL or 11-character video ID.
        language: Preferred transcript language (BCP-47-ish code like 'en', 'de', 'en-US'). Defaults to video language with English fallback.
        model: Whisper model override (tiny/base/small/medium/large-v3) when transcription runs.
        include_timestamps: False -> plain text without [HH:MM:SS] markers.
        include_speakers: Request speaker labels. NOTE: diarization is not implemented; a note is returned instead (labels are never faked).
        word_timestamps: Include per-word timings (only from whisper or json3 captions; increases size a lot).
        force_retranscribe: Skip cache AND captions; always run whisper.
        prefer_captions: Override PREFER_CAPTIONS setting for this call.
        format: 'compact' | 'detailed' | 'json' | 'srt' | 'vtt'.
        timestamp_format: 'hhmmss' | 'mmss' | 'seconds'.
        wait: Block until done (up to wait_timeout_seconds); otherwise return a job handle immediately.
        wait_timeout_seconds: Max time to wait before returning a job handle.

    Returns:
        The transcript (string format or JSON object), a job status object if still
        processing, or an error object {error, message, retryable, hint?}.
    """
    try:
        ref = parse_video_ref(url)
        job = context.jobs.create(ref.video_id)
        request = TranscribeRequest(
            ref=ref.url, language=language, model=model,
            include_speakers=include_speakers, word_timestamps=word_timestamps,
            force_retranscribe=force_retranscribe, prefer_captions=prefer_captions,
            job=job)
        asyncio.get_running_loop()  # ensure we're async
        runner = asyncio.create_task(_execute_job(job, request))

        if wait:
            deadline = asyncio.get_running_loop().time() + wait_timeout_seconds
            while not job.done and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.25)
            if not job.done:
                return {
                    "job_id": job.id, "video_id": ref.video_id, "status": job.status,
                    "progress": round(job.progress, 2), "message": job.message,
                    "note": "Still processing. Poll youtube_transcription_status(job_id=...) or "
                            "re-invoke this tool later; the finished transcript will be cached.",
                }
        else:
            await asyncio.sleep(0)
            return {
                "job_id": job.id, "video_id": ref.video_id, "status": job.status,
                "progress": round(job.progress, 2), "message": job.message,
                "note": "Use youtube_transcription_status(job_id) to poll; when complete, fetch "
                        "with youtube_get_transcript or re-call youtube_transcribe (instant cache hit).",
            }

        if job.status == "failed":
            return job.error or {"error": ErrorCode.INTERNAL_ERROR, "message": job.message}
        if job.status == "cancelled":
            return {"error": ErrorCode.CANCELLED, "message": "Transcription cancelled.", "retryable": False}

        payload = context.repo.get(job.cache_key) if job.cache_key else None
        if payload is None:
            return {"error": ErrorCode.INTERNAL_ERROR,
                    "message": "Job completed but transcript not found in cache.", "retryable": True}
        await runner  # surface runner exceptions if any slipped through

        segments = payload.get("segments", [])
        limit = context.settings.max_response_chars
        # long transcripts: show first chunk + navigation info instead of dumping everything
        shown = segments
        footer = None
        if format != "json" and len("\n".join(s.get("text", "") for s in segments)) > limit:
            shown = [s for s in segments if s["start"] < 600]
            footer = (f"[Showing the first ~10 minutes of {len(segments)} segments. Retrieve more with "
                      f"youtube_get_transcript(start=..., end=...) or offset pagination; use "
                      f"youtube_search_transcript to jump to specific topics.]")
        return common.render_response(
            payload, shown, format, timestamp_format, include_timestamps, limit,
            header_extra=[f"cache: {'HIT' if job.cache_hit else 'MISS'}"], footer=footer)
    except YoutubeMcpError as e:
        return common.error_response(e)
    except Exception as e:
        return common.internal_error(e)
