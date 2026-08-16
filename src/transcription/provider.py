"""Replaceable transcription engine abstraction (spec section 2).

A TranscriptionProvider turns an audio file into timed segments. Implement:
faster-whisper (local, default), openai-compatible (any /audio/transcriptions
endpoint). New engines plug in here without touching the pipeline or MCP layer.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from src.config.settings import Settings
from src.utils.errors import ErrorCode, YoutubeMcpError


@dataclass
class ProviderWord:
    start: float
    end: float
    text: str


@dataclass
class ProviderSegment:
    start: float
    end: float
    text: str
    words: list[ProviderWord] = field(default_factory=list)


@dataclass
class ProviderResult:
    segments: list[ProviderSegment]
    language: str | None = None
    language_probability: float | None = None
    model: str = ""


class TranscriptionProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    def transcribe(self, audio_path: Path | str, *, language: str | None = None,
                   model: str | None = None, word_timestamps: bool = False,
                   progress=None, cancel_event=None, deadline: float | None = None) -> ProviderResult:
        """Transcribe audio.

        progress(fraction)   -- optional 0..1 progress callback
        cancel_event         -- optional threading.Event; check often, raise CANCELLED
        deadline             -- optional time.monotonic() cutoff; raise TIMEOUT
        """


def check_cancel(cancel_event, deadline) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise YoutubeMcpError(ErrorCode.CANCELLED, "Transcription cancelled by user.")
    if deadline is not None and time.monotonic() > deadline:
        raise YoutubeMcpError(
            ErrorCode.TIMEOUT, "Transcription exceeded TRANSCRIPTION_TIMEOUT.",
            hint="Raise TRANSCRIPTION_TIMEOUT or use a smaller WHISPER_MODEL.")


def build_provider(settings: Settings, name: str | None = None) -> TranscriptionProvider | None:
    """Factory. Returns None for captions-only mode ('none')."""
    from src.transcription.faster_whisper import FasterWhisperProvider
    from src.transcription.whisper_api import OpenAICompatibleWhisperProvider

    key = (name or settings.transcription_provider).lower()
    if key in ("faster-whisper", "faster_whisper", "local", "whisper"):
        return FasterWhisperProvider(settings)
    if key in ("openai-compatible", "whisper-api", "api", "openai"):
        return OpenAICompatibleWhisperProvider(settings)
    if key in ("none", "captions-only", "disabled", "off"):
        return None
    raise YoutubeMcpError(
        ErrorCode.CONFIG_ERROR, f"Unknown TRANSCRIPTION_PROVIDER: {key!r}",
        hint="Use 'faster-whisper', 'openai-compatible' or 'none'.")
