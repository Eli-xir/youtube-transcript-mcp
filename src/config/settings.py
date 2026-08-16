"""Central configuration, loaded from environment + optional .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_TRUTHY = {"1", "true", "yes", "on"}


def _get(env: dict, key: str, default: str) -> str:
    v = env.get(key)
    return default if v is None or str(v).strip() == "" else str(v).strip()


def _bool(env: dict, key: str, default: bool) -> bool:
    v = env.get(key)
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip().lower() in _TRUTHY


def _int(env: dict, key: str, default: int) -> int:
    v = env.get(key)
    try:
        return int(str(v).strip()) if v is not None and str(v).strip() != "" else default
    except ValueError:
        return default


def _csv(env: dict, key: str, default: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in _get(env, key, default).split(",") if x.strip())


def _path(env: dict, key: str, default: Path) -> Path:
    p = Path(_get(env, key, str(default)))
    return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()


@dataclass(frozen=True)
class Settings:
    """All runtime settings. Frozen so it can be shared safely across threads."""

    # transcription engine
    transcription_provider: str = "faster-whisper"
    whisper_model: str = "small"
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"
    beam_size: int = 5
    vad_filter: bool = True
    whisper_api_base_url: str = ""
    whisper_api_key: str = ""
    whisper_api_model: str = "whisper-1"

    # caption-first behavior
    prefer_captions: bool = True
    language_fallbacks: tuple[str, ...] = ("en",)
    default_language: str = ""

    # storage
    cache_enabled: bool = True
    cache_dir: Path = PROJECT_ROOT / "data" / "cache"
    cache_ttl_days: int = 30
    max_cache_entries: int = 1000
    temp_dir: Path = PROJECT_ROOT / "data" / "tmp"

    # limits / safety
    max_video_duration: int = 14400
    max_download_size_mb: int = 4096
    max_response_chars: int = 60000

    # timeouts (seconds)
    http_timeout: int = 30
    metadata_timeout: int = 45
    caption_timeout: int = 90
    audio_download_timeout: int = 1800
    transcription_timeout: int = 7200

    # optional features
    enable_diarization: bool = False
    enable_semantic_search: bool = False

    # server
    log_level: str = "INFO"
    mcp_transport: str = "stdio"

    @property
    def max_download_bytes(self) -> int:
        return self.max_download_size_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Settings":
        if env is None:
            load_dotenv(PROJECT_ROOT / ".env")
            env = dict(os.environ)
        s = cls(
            transcription_provider=_get(env, "TRANSCRIPTION_PROVIDER", "faster-whisper").lower(),
            whisper_model=_get(env, "WHISPER_MODEL", "small"),
            # DEVICE / WHISPER_DEVICE and COMPUTE_TYPE / WHISPER_COMPUTE_TYPE are aliases
            whisper_device=_get(env, "WHISPER_DEVICE", _get(env, "DEVICE", "auto")).lower(),
            whisper_compute_type=_get(env, "WHISPER_COMPUTE_TYPE", _get(env, "COMPUTE_TYPE", "auto")).lower(),
            beam_size=_int(env, "WHISPER_BEAM_SIZE", 5),
            vad_filter=_bool(env, "WHISPER_VAD_FILTER", True),
            whisper_api_base_url=_get(env, "WHISPER_API_BASE_URL", ""),
            whisper_api_key=_get(env, "WHISPER_API_KEY", ""),
            whisper_api_model=_get(env, "WHISPER_API_MODEL", "whisper-1"),
            prefer_captions=_bool(env, "PREFER_CAPTIONS", True),
            language_fallbacks=_csv(env, "LANGUAGE_FALLBACKS", "en"),
            default_language=_get(env, "DEFAULT_LANGUAGE", ""),
            cache_enabled=_bool(env, "CACHE_ENABLED", True),
            cache_dir=_path(env, "CACHE_DIR", PROJECT_ROOT / "data" / "cache"),
            cache_ttl_days=_int(env, "CACHE_TTL_DAYS", 30),
            max_cache_entries=_int(env, "MAX_CACHE_ENTRIES", 1000),
            temp_dir=_path(env, "TEMP_DIR", PROJECT_ROOT / "data" / "tmp"),
            max_video_duration=_int(env, "MAX_VIDEO_DURATION", 14400),
            max_download_size_mb=_int(env, "MAX_DOWNLOAD_SIZE_MB", 4096),
            max_response_chars=_int(env, "MAX_RESPONSE_CHARS", 60000),
            http_timeout=_int(env, "HTTP_TIMEOUT", 30),
            metadata_timeout=_int(env, "METADATA_TIMEOUT", 45),
            caption_timeout=_int(env, "CAPTION_TIMEOUT", 90),
            audio_download_timeout=_int(env, "AUDIO_DOWNLOAD_TIMEOUT", 1800),
            transcription_timeout=_int(env, "TRANSCRIPTION_TIMEOUT", 7200),
            enable_diarization=_bool(env, "ENABLE_DIARIZATION", False),
            enable_semantic_search=_bool(env, "ENABLE_SEMANTIC_SEARCH", False),
            log_level=_get(env, "LOG_LEVEL", "INFO").upper(),
            mcp_transport=_get(env, "MCP_TRANSPORT", "stdio").lower(),
        )
        s.ensure_dirs()
        return s
