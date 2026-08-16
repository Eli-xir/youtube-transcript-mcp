"""Local web UI for youtube-transcript-mcp.

Reuses the same pipeline, cache and search index as the MCP server (imported from
src.server.context), so anything transcribed here is also available to MCP clients
and vice versa.

Run:  python -m src.webapp.app     ->  http://127.0.0.1:8765
Binds to localhost only; this is a personal tool, not a public service.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from src.server import context
from src.transcript.chapters import from_description, from_metadata, heuristic_chapters
from src.transcript.models import Transcript
from src.transcript.search import search_segments
from src.transcript.summarize import build_summary
from src.transcription.pipeline import TranscribeRequest
from src.utils.errors import ErrorCode, YoutubeMcpError
from src.youtube.url_parser import parse_video_ref

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"

_BAD_REQUEST = {ErrorCode.INVALID_URL, ErrorCode.INVALID_ARGUMENT, ErrorCode.PLAYLIST_UNSUPPORTED}


def _error_response(e: YoutubeMcpError) -> JSONResponse:
    status = 404 if e.code == ErrorCode.NOT_FOUND else 400 if e.code in _BAD_REQUEST else 502
    return JSONResponse(e.to_dict(), status_code=status)


def _ref_from(value: str):
    if not value or not str(value).strip():
        raise YoutubeMcpError(ErrorCode.INVALID_ARGUMENT, "Missing 'url' / 'video' value.")
    return parse_video_ref(str(value).strip())


# ---------------------------------------------------------------- endpoints


async def health(request):
    return JSONResponse({"ok": True, "app": "youtube-transcript-mcp", "version": "0.1.0"})


async def metadata_endpoint(request):
    try:
        body = await request.json()
        ref = _ref_from(body.get("url"))
        meta = context.repo.get_metadata(ref.video_id)
        if meta is None:
            meta = await asyncio.to_thread(context.client.fetch_metadata, ref)
            context.repo.put_metadata(ref.video_id, meta)
        meta["cached_transcripts"] = context.repo.versions(ref.video_id)
        return JSONResponse(meta)
    except YoutubeMcpError as e:
        return _error_response(e)
    except Exception as e:
        logger.exception("metadata endpoint failed")
        return JSONResponse({"error": ErrorCode.INTERNAL_ERROR, "message": str(e)[:200],
                             "retryable": False}, status_code=500)


async def transcribe_endpoint(request):
    try:
        body = await request.json()
        ref = _ref_from(body.get("url"))
        req = TranscribeRequest(
            ref=ref.url,
            language=body.get("language") or None,
            model=body.get("model") or None,
            force_retranscribe=bool(body.get("force_retranscribe")),
        )
        result = await asyncio.to_thread(context.pipeline.run, req)
        payload = result.transcript.to_dict(include_words=False)
        payload["cache_hit"] = result.cache_hit
        payload["elapsed_s"] = round(result.elapsed_s, 1)
        return JSONResponse(payload)
    except YoutubeMcpError as e:
        return _error_response(e)
    except Exception as e:
        logger.exception("transcribe endpoint failed")
        return JSONResponse({"error": ErrorCode.INTERNAL_ERROR, "message": str(e)[:200],
                             "retryable": False}, status_code=500)


async def transcript_endpoint(request):
    try:
        ref = _ref_from(request.query_params.get("video"))
        payload = context.repo.find_latest(ref.video_id, request.query_params.get("language"))
        if payload is None:
            raise YoutubeMcpError(
                ErrorCode.NOT_FOUND, f"No transcript cached for {ref.video_id}.",
                hint="POST /api/transcribe first.")
        return JSONResponse(payload)
    except YoutubeMcpError as e:
        return _error_response(e)


async def search_endpoint(request):
    try:
        ref = _ref_from(request.query_params.get("video"))
        payload = context.repo.find_latest(ref.video_id, request.query_params.get("language"))
        if payload is None:
            raise YoutubeMcpError(
                ErrorCode.NOT_FOUND, f"No transcript cached for {ref.video_id}.",
                hint="Transcribe the video first.")
        result = search_segments(
            ref.video_id, payload.get("segments", []),
            request.query_params.get("q", ""),
            regex=request.query_params.get("regex") in ("1", "true"),
            fuzzy=request.query_params.get("fuzzy") in ("1", "true"),
            case_sensitive=request.query_params.get("case") in ("1", "true"),
            max_results=int(request.query_params.get("max", "20") or 20),
            context=int(request.query_params.get("context", "1") or 1),
        )
        return JSONResponse(result)
    except YoutubeMcpError as e:
        return _error_response(e)
    except ValueError as e:
        return JSONResponse({"error": ErrorCode.INVALID_ARGUMENT, "message": str(e)[:200],
                             "retryable": False}, status_code=400)


async def chapters_endpoint(request):
    try:
        ref = _ref_from(request.query_params.get("video"))
        want_ai = request.query_params.get("ai") in ("1", "true")
        meta = context.repo.get_metadata(ref.video_id)
        if meta is None:
            meta = await asyncio.to_thread(context.client.fetch_metadata, ref)
            context.repo.put_metadata(ref.video_id, meta)
        chapters = from_metadata(meta) or from_description(meta)
        source = chapters[0]["source"] if chapters else None
        if chapters is None and want_ai:
            payload = context.repo.find_latest(ref.video_id)
            if payload is not None:
                chapters = heuristic_chapters(payload.get("segments", []),
                                              duration=payload.get("duration"))
                source = "heuristic"
        return JSONResponse({"video_id": ref.video_id, "source": source,
                             "chapters": chapters or []})
    except YoutubeMcpError as e:
        return _error_response(e)


async def summary_endpoint(request):
    try:
        body = await request.json()
        ref = _ref_from(body.get("video"))
        style = body.get("style", "executive")
        payload = context.repo.find_latest(ref.video_id, body.get("language"))
        if payload is None:
            raise YoutubeMcpError(
                ErrorCode.NOT_FOUND, f"No transcript cached for {ref.video_id}.",
                hint="Transcribe the video first.")
        meta = context.repo.get_metadata(ref.video_id) or {}
        chapters = None
        if style in ("chapter_summaries", "all"):
            chapters = (from_metadata(meta) or from_description(meta)
                        or heuristic_chapters(payload.get("segments", []),
                                              duration=payload.get("duration")))
        text = build_summary(payload, chapters, style, int(body.get("max_points", 6) or 6))
        return JSONResponse({"style": style, "text": text})
    except YoutubeMcpError as e:
        return _error_response(e)
    except Exception as e:
        logger.exception("summary endpoint failed")
        return JSONResponse({"error": ErrorCode.INTERNAL_ERROR, "message": str(e)[:200],
                             "retryable": False}, status_code=500)


async def index(request):
    return FileResponse(STATIC_DIR / "index.html")


def create_app() -> Starlette:
    return Starlette(routes=[
        Route("/", index),
        Route("/api/health", health),
        Route("/api/metadata", metadata_endpoint, methods=["POST"]),
        Route("/api/transcribe", transcribe_endpoint, methods=["POST"]),
        Route("/api/transcript", transcript_endpoint),
        Route("/api/search", search_endpoint),
        Route("/api/chapters", chapters_endpoint),
        Route("/api/summary", summary_endpoint, methods=["POST"]),
        Mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static"),
    ])


app = create_app()


def main() -> None:
    import uvicorn
    print("youtube-transcript-mcp web UI -> http://127.0.0.1:8765")
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")


if __name__ == "__main__":
    main()
