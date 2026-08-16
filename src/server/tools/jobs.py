"""youtube_transcription_status + youtube_cancel_transcription."""
from __future__ import annotations

from src.server import context
from src.server.tools import common
from src.utils.errors import ErrorCode, YoutubeMcpError
from src.utils.timestamps import format_seconds

_mcp = context.mcp


@_mcp.tool()
async def youtube_transcription_status(job_id: str | None = None,
                                       video: str | None = None) -> dict:
    """Check transcription job progress (stages: queued -> fetching_metadata ->
    fetching_captions -> downloading_audio -> transcribing -> processing_timestamps ->
    indexing -> complete/failed/cancelled).

    Args:
        job_id: Specific job to inspect.
        video: Alternatively list jobs for a video URL/ID.
    """
    try:
        if job_id:
            job = context.jobs.get(job_id)
            if not job:
                raise YoutubeMcpError(ErrorCode.NOT_FOUND, f"Unknown job_id {job_id!r}.",
                                      hint="Call without job_id to list recent jobs.")
            out = job.to_dict()
            if job.done and job.cache_key:
                payload = context.repo.get(job.cache_key)
                if payload:
                    out["transcript_ready"] = True
                    out["segment_count"] = payload.get("segment_count")
                    out["duration"] = format_seconds(payload.get("duration") or 0)
            return out
        if video:
            from src.youtube.url_parser import parse_video_ref
            ref = parse_video_ref(video)
            js = context.jobs.for_video(ref.video_id)
            return {"jobs": [j.to_dict() for j in js]} if js else {
                "jobs": [], "message": "No jobs for this video in this server session."}
        return {"jobs": [j.to_dict() for j in context.jobs.recent(20)]}
    except YoutubeMcpError as e:
        return common.error_response(e)
    except Exception as e:
        return common.internal_error(e)


@_mcp.tool()
async def youtube_cancel_transcription(job_id: str) -> dict:
    """Cancel a running transcription job.

    Args:
        job_id: The job to cancel (from youtube_transcribe / youtube_transcription_status).
    """
    try:
        job = context.jobs.cancel(job_id)
        if not job:
            raise YoutubeMcpError(ErrorCode.NOT_FOUND, f"Unknown job_id {job_id!r}.")
        return job.to_dict()
    except YoutubeMcpError as e:
        return common.error_response(e)
    except Exception as e:
        return common.internal_error(e)
