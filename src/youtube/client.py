"""YouTube access layer built on yt-dlp (as a library -- no shell, no injection).

Responsibilities:
- normalized metadata extraction
- caption track retrieval (json3 preferred, vtt fallback)
- audio-only download with size/cancel hooks
All errors are mapped to structured YoutubeMcpError.
"""
from __future__ import annotations

import glob
import logging
import os
import tempfile
from pathlib import Path

import yt_dlp

from src.config.settings import Settings
from src.utils.errors import ErrorCode, YoutubeMcpError, map_ytdlp_error
from src.youtube.captions import CaptionPayload, select_caption_track
from src.youtube.url_parser import VideoRef

logger = logging.getLogger(__name__)


class _QuietLogger:
    """Swallow yt-dlp's internal logging; errors come back as exceptions."""

    def debug(self, msg, *args):
        pass

    def info(self, msg, *args):
        pass

    def warning(self, msg, *args):
        pass

    def error(self, msg, *args):
        pass


def _normalize_info(info: dict) -> dict:
    upload = info.get("upload_date") or ""
    upload_iso = f"{upload[:4]}-{upload[4:6]}-{upload[6:8]}" if len(upload) == 8 else None
    chapters = None
    if info.get("chapters"):
        chapters = [
            {"title": (c.get("title") or "").strip() or f"Chapter {i + 1}",
             "start": float(c.get("start_time", 0) or 0),
             "end": float(c.get("end_time", 0) or 0)}
            for i, c in enumerate(info["chapters"])
        ]
    subs = info.get("subtitles") or {}
    autos = info.get("automatic_captions") or {}
    return {
        "video_id": info.get("id"),
        "title": info.get("title") or "(untitled)",
        "channel": info.get("channel") or info.get("uploader") or None,
        "channel_id": info.get("channel_id"),
        "url": info.get("webpage_url") or info.get("original_url"),
        "duration": float(info.get("duration") or 0),
        "upload_date": upload_iso,
        "description": info.get("description") or "",
        "thumbnail": info.get("thumbnail"),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "language": info.get("language"),
        "is_live": bool(info.get("is_live")),
        "chapters": chapters,
        "caption_languages": {
            "manual": sorted(k for k, v in subs.items() if v),
            "auto": sorted(k for k, v in autos.items() if v),
        },
    }


class YouTubeClient:
    """Thin, injectable wrapper around yt-dlp used by the pipeline and tools."""

    def __init__(self, settings: Settings):
        self._s = settings

    def _base_opts(self) -> dict:
        return {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "socket_timeout": self._s.http_timeout,
            "retries": 3,
            "logger": _QuietLogger(),
        }

    def _extract(self, ref: VideoRef, opts: dict, download: bool) -> dict:
        try:
            with yt_dlp.YoutubeDL({**self._base_opts(), **opts}) as ydl:
                info = ydl.extract_info(ref.url, download=download)
        except yt_dlp.utils.DownloadError as e:
            raise map_ytdlp_error(e) from e
        except YoutubeMcpError:
            raise
        except Exception as e:  # unexpected yt-dlp internals
            raise YoutubeMcpError(ErrorCode.NETWORK_ERROR, str(e)[:300], retryable=True) from e
        if not info:
            raise YoutubeMcpError(ErrorCode.VIDEO_UNAVAILABLE, "YouTube returned no data for this video.")
        if info.get("_type") == "playlist":
            entries = [e for e in (info.get("entries") or []) if e]
            if not entries:
                raise YoutubeMcpError(ErrorCode.PLAYLIST_UNSUPPORTED, "Playlist contained no videos.")
            info = entries[0]
        return info

    # ------------------------------------------------------------ metadata

    def fetch_metadata(self, ref: VideoRef) -> dict:
        info = self._extract(ref, {"skip_download": True}, download=False)
        return _normalize_info(info)

    # ------------------------------------------------------------ captions

    def get_captions(self, ref: VideoRef, language: str | None = None) -> CaptionPayload | None:
        """Fetch the best caption track. Returns None when nothing usable exists."""
        info = self._extract(ref, {"skip_download": True}, download=False)
        subs = info.get("subtitles") or {}
        autos = info.get("automatic_captions") or {}
        sel = select_caption_track(subs, autos, language, self._s.language_fallbacks)
        if not sel:
            return None
        kind, lang = sel
        self._s.temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="caps-", dir=str(self._s.temp_dir)) as td:
            opts = {
                "skip_download": True,
                "subtitleslangs": [lang],
                "subtitlesformat": "json3/vtt",
                "outtmpl": os.path.join(td, "subs.%(ext)s"),
                "overwrites": True,
            }
            if kind == "manual":
                opts["writesubtitles"] = True
            else:
                opts["writeautomaticsub"] = True
            self._extract(ref, opts, download=True)
            files = sorted(glob.glob(os.path.join(td, "*.json3"))) or sorted(glob.glob(os.path.join(td, "*.vtt")))
            if not files:
                logger.warning("caption track %s (%s) selected but no file written", lang, kind)
                return None
            with open(files[0], "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            if not text.strip():
                return None
            return CaptionPayload(kind=kind, language=lang, ext=Path(files[0]).suffix.lstrip("."), text=text)

    # ------------------------------------------------------------ audio

    def download_audio(self, ref: VideoRef, dest_dir: Path, progress=None) -> Path:
        """Download best-quality audio-only media into dest_dir. Returns the file path.

        progress(fraction) is called with download progress; may raise to abort.
        Retries once per alternative player client on 403 (YouTube throttling).
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        max_bytes = self._s.max_download_bytes

        def hook(d):
            if progress:
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                done = d.get("downloaded_bytes") or 0
                if total:
                    progress(min(0.99, done / total))
            if d.get("status") == "finished" and progress:
                progress(1.0)

        opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(str(dest_dir), "audio.%(ext)s"),
            "max_filesize": max_bytes,
            "progress_hooks": [hook],
            "overwrites": True,
        }
        last_err: Exception | None = None
        info = None
        for client in (None, "ios", "mweb", "tv"):
            try:
                run_opts = dict(opts)
                if client:
                    run_opts["extractor_args"] = {"youtube": {"player_client": [client]}}
                info = self._extract(ref, run_opts, download=True)
                last_err = None
                break
            except YoutubeMcpError as e:
                if e.code not in (ErrorCode.DOWNLOAD_FAILED, ErrorCode.RATE_LIMITED):
                    raise
                last_err = e
                logger.warning("audio download via %s failed (%s); trying next client",
                               client or "default", e.code)
        if last_err is not None:
            raise last_err

        path = os.path.join(str(dest_dir), "audio." + (info.get("ext") or "m4a"))
        candidates = sorted(glob.glob(os.path.join(str(dest_dir), "audio.*")))
        if not os.path.exists(path) and candidates:
            path = candidates[0]
        if not os.path.exists(path):
            raise YoutubeMcpError(
                ErrorCode.DOWNLOAD_FAILED, "Audio download produced no file (format may be unavailable).",
                retryable=True)
        size = os.path.getsize(path)
        if size > max_bytes:
            os.unlink(path)
            raise YoutubeMcpError(
                ErrorCode.DOWNLOAD_TOO_LARGE,
                f"Audio file is {size / 1024 / 1024:.0f} MB, over the {self._s.max_download_size_mb} MB limit.",
                hint="Raise MAX_DOWNLOAD_SIZE_MB if this is expected.")
        logger.info("downloaded audio for %s: %.1f MB", ref.video_id, size / 1024 / 1024)
        return Path(path)
