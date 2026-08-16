"""Optional OpenAI-compatible Whisper API provider.

Works with any endpoint implementing POST {base}/audio/transcriptions
(OpenAI, Groq, etc.). NOT enabled by default -- local faster-whisper is.
Note: chat-LLM APIs (DeepSeek, Grok) do not implement speech endpoints and
cannot be used here.
"""
from __future__ import annotations

import logging

import httpx

from src.config.settings import Settings
from src.transcription.provider import (ProviderResult, ProviderSegment, ProviderWord,
                                        TranscriptionProvider)
from src.utils.errors import ErrorCode, YoutubeMcpError

logger = logging.getLogger(__name__)


class OpenAICompatibleWhisperProvider(TranscriptionProvider):
    name = "openai-compatible"

    def __init__(self, settings: Settings):
        self._s = settings

    def transcribe(self, audio_path, *, language=None, model=None, word_timestamps=False,
                   progress=None, cancel_event=None, deadline=None) -> ProviderResult:
        if not self._s.whisper_api_base_url or not self._s.whisper_api_key:
            raise YoutubeMcpError(
                ErrorCode.CONFIG_ERROR,
                "WHISPER_API_BASE_URL and WHISPER_API_KEY must be set for TRANSCRIPTION_PROVIDER=openai-compatible.",
                hint="Or switch back to TRANSCRIPTION_PROVIDER=faster-whisper (local, free).")
        url = self._s.whisper_api_base_url.rstrip("/") + "/audio/transcriptions"
        model_name = model or self._s.whisper_api_model
        data = {"model": model_name, "response_format": "verbose_json"}
        if language:
            data["language"] = language
        if word_timestamps:
            data["timestamp_granularities[]"] = "word"
        try:
            with open(audio_path, "rb") as f:
                resp = httpx.post(
                    url,
                    headers={"Authorization": f"Bearer {self._s.whisper_api_key}"},
                    files={"file": ("audio", f, "application/octet-stream")},
                    data=data,
                    timeout=self._s.transcription_timeout,
                )
        except httpx.HTTPError as e:
            raise YoutubeMcpError(ErrorCode.NETWORK_ERROR, f"Whisper API request failed: {str(e)[:200]}",
                                  retryable=True) from e
        if resp.status_code in (401, 403):
            raise YoutubeMcpError(ErrorCode.CONFIG_ERROR, "Whisper API rejected the credentials (401/403).",
                                  hint="Check WHISPER_API_KEY.")
        if resp.status_code == 429:
            raise YoutubeMcpError(ErrorCode.RATE_LIMITED, "Whisper API rate limit hit.", retryable=True)
        if resp.status_code != 200:
            raise YoutubeMcpError(ErrorCode.TRANSCRIPTION_FAILED,
                                  f"Whisper API error {resp.status_code}: {resp.text[:200]}", retryable=True)
        body = resp.json()
        segments = []
        for seg in body.get("segments", []):
            words = [ProviderWord(w.get("start", 0), w.get("end", 0), (w.get("word") or "").strip())
                     for w in (seg.get("words") or [])]
            segments.append(ProviderSegment(seg.get("start", 0), seg.get("end", 0),
                                            (seg.get("text") or "").strip(), words))
        return ProviderResult(segments=segments, language=body.get("language"),
                              model=model_name)
