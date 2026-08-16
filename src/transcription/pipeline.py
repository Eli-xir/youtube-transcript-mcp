"""Caption-first transcription pipeline (spec section 3).

URL -> metadata -> captions? -> use captions | download audio -> whisper
      -> normalized timestamped segments -> cache -> result

Runs synchronously (in a worker thread); progress is reported through an
optional Job object, which also carries the cancellation flag.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.cache.repository import TranscriptRepository, make_cache_key
from src.config.settings import Settings
from src.jobs.manager import Job
from src.transcript.models import Segment, Transcript, Word
from src.transcription.provider import TranscriptionProvider, build_provider
from src.utils.errors import ErrorCode, YoutubeMcpError
from src.youtube.captions import caption_payload_to_segments
from src.youtube.client import YouTubeClient
from src.youtube.url_parser import VideoRef, parse_video_ref

logger = logging.getLogger(__name__)


@dataclass
class TranscribeRequest:
    ref: str
    language: str | None = None
    model: str | None = None
    provider_name: str | None = None
    word_timestamps: bool = False
    include_speakers: bool = False
    force_retranscribe: bool = False   # skip cache AND captions; always run whisper
    prefer_captions: bool | None = None  # None -> settings default
    job: Job | None = field(default=None, repr=False)


@dataclass
class PipelineResult:
    transcript: Transcript
    meta: dict
    cache_hit: bool
    elapsed_s: float
    cache_key: str


class TranscriptionPipeline:
    def __init__(self, settings: Settings, client: YouTubeClient, repo: TranscriptRepository,
                 provider: TranscriptionProvider | None = None):
        self._s = settings
        self._client = client
        self._repo = repo
        self._provider = provider

    # ------------------------------------------------------------ helpers

    def _u(self, job: Job | None, status: str | None = None, progress: float | None = None,
           message: str | None = None) -> None:
        if job:
            job.update(status=status, progress=progress, message=message)

    def _cancelled(self, job: Job | None) -> None:
        if job and job.cancelled:
            raise YoutubeMcpError(ErrorCode.CANCELLED, "Cancelled by user.")

    def _provider_for(self, request: TranscribeRequest) -> TranscriptionProvider | None:
        if self._provider is not None:
            return self._provider
        return build_provider(self._s, request.provider_name)

    # ------------------------------------------------------------ main

    def run(self, request: TranscribeRequest) -> PipelineResult:
        t0 = time.monotonic()
        job = request.job
        self._u(job, status="queued", progress=0.0, message="Starting...")

        ref: VideoRef = parse_video_ref(request.ref)
        self._cancelled(job)

        # 1. metadata (repo cache, refreshed when stale or forced)
        self._u(job, status="fetching_metadata", progress=0.02, message="Fetching video metadata...")
        meta = None if request.force_retranscribe else self._repo.get_metadata(ref.video_id)
        if meta is None:
            meta = self._client.fetch_metadata(ref)
            self._repo.put_metadata(ref.video_id, meta)
        self._cancelled(job)

        duration = float(meta.get("duration") or 0)
        if duration and duration > self._s.max_video_duration:
            raise YoutubeMcpError(
                ErrorCode.VIDEO_TOO_LONG,
                f"Video is {duration/3600:.1f}h; MAX_VIDEO_DURATION is {self._s.max_video_duration/3600:.1f}h.",
                hint="Raise MAX_VIDEO_DURATION in .env if this is expected.")

        # 2. captions-first (unless forced to retranscribe)
        provider = self._provider_for(request)
        prefer_captions = request.prefer_captions if request.prefer_captions is not None else self._s.prefer_captions
        caption_segments: list[Segment] | None = None
        has_words = False
        caption_lang = request.language
        caption_kind = None

        if prefer_captions and not request.force_retranscribe:
            self._u(job, status="fetching_captions", progress=0.06, message="Checking YouTube captions...")
            try:
                caps = self._client.get_captions(ref, request.language)
            except YoutubeMcpError as e:
                if e.code in (ErrorCode.CAPTIONS_UNAVAILABLE,):
                    caps = None
                else:
                    raise
            self._cancelled(job)
            if caps is not None:
                caption_segments, has_words = caption_payload_to_segments(caps)
                if caption_segments:
                    caption_lang = caps.language
                    caption_kind = caps.kind
                    logger.info("using %s captions (%s) for %s: %d segments",
                                caps.kind, caps.language, ref.video_id, len(caption_segments))

        # 3. cache key on the RESOLVED language so lookups are stable.
        # Caption-route transcripts are provider/model-independent; whisper ones are not.
        used_provider_name = provider.name if provider else "none"
        used_model = (request.model or (self._s.whisper_model if provider else ""))
        key = make_cache_key(
            ref.video_id, caption_lang or request.language or "auto",
            used_provider_name if caption_segments is None else "captions",
            used_model if caption_segments is None else "",
            request.word_timestamps, request.include_speakers)
        if job:
            job.cache_key = key

        if not request.force_retranscribe:
            cached = self._repo.get(key)
            if cached is not None:
                logger.info("cache hit for %s", ref.video_id)
                if job:
                    job.cache_hit = True
                tr = Transcript.from_dict(cached)
                return PipelineResult(tr, meta, True, time.monotonic() - t0, key)

        # 4. build transcript
        notes: list[str] = []
        if request.include_speakers:
            if self._s.enable_diarization:
                notes.append("Speaker diarization is architecturally supported but not implemented; "
                             "speakers were NOT identified.")
            else:
                notes.append("Speaker diarization is disabled (ENABLE_DIARIZATION=false); "
                             "speakers were NOT identified.")
        notes.append("SPEAKER labels (when present) distinguish voices only; they never identify "
                     "actual people.")

        if caption_segments is not None:
            self._u(job, status="processing_timestamps", progress=0.35,
                    message="Normalizing caption timestamps...")
            segments = caption_segments
            source = "youtube_manual" if caption_kind == "manual" else "youtube_auto"
            model_name = ""
            detected, prob = caption_lang, None
            if not has_words:
                notes.append("Caption format lacks word-level timing; only segment timestamps available.")
        else:
            if provider is None:
                raise YoutubeMcpError(
                    ErrorCode.CAPTIONS_UNAVAILABLE,
                    "No usable captions and TRANSCRIPTION_PROVIDER=none (captions-only mode).",
                    hint="Set TRANSCRIPTION_PROVIDER=faster-whisper to enable transcription.")
            self._u(job, status="downloading_audio", progress=0.1, message="Downloading audio...")
            self._s.temp_dir.mkdir(parents=True, exist_ok=True)
            tmp = tempfile.mkdtemp(prefix=f"yt-{ref.video_id}-", dir=str(self._s.temp_dir))
            audio_path: Path | None = None
            try:
                def dl_progress(frac):
                    self._u(job, progress=0.1 + 0.2 * frac, message="Downloading audio...")
                    self._cancelled(job)

                audio_path = self._client.download_audio(ref, Path(tmp), progress=dl_progress)
                self._cancelled(job)
                self._u(job, status="transcribing", progress=0.32, message="Transcribing audio...")

                def tr_progress(frac):
                    self._u(job, progress=0.32 + 0.55 * frac, message="Transcribing audio...")
                    self._cancelled(job)

                deadline = time.monotonic() + self._s.transcription_timeout
                result = provider.transcribe(
                    audio_path, language=request.language, model=request.model,
                    word_timestamps=request.word_timestamps, progress=tr_progress,
                    cancel_event=job.cancel_event if job else None, deadline=deadline)
                self._cancelled(job)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

            self._u(job, status="processing_timestamps", progress=0.9,
                    message="Processing timestamps...")
            segments = [
                Segment(id=i, start=s.start, end=s.end, text=s.text,
                        words=[Word(w.start, w.end, w.text) for w in s.words] if s.words else None)
                for i, s in enumerate(result.segments)
            ]
            source = "whisper"
            model_name = result.model
            detected, prob = result.language, result.language_probability
            if not request.word_timestamps:
                for s in segments:
                    s.words = None

        tr = Transcript(
            video_id=ref.video_id,
            language=caption_lang or request.language or detected or "",
            source=source,
            model=model_name,
            segments=segments,
            duration=duration or (segments[-1].end if segments else 0.0),
            detected_language=detected,
            language_probability=prob,
            snapshot={k: meta.get(k) for k in ("title", "channel", "channel_id", "duration",
                                               "upload_date", "url")},
            created_at=time.time(),
            notes=notes,
        )

        self._u(job, status="indexing", progress=0.95, message="Caching transcript...")
        payload = tr.to_dict(include_words=request.word_timestamps)
        payload["provider"] = used_provider_name
        payload["word_timestamps"] = request.word_timestamps
        self._repo.put(key, payload)
        self._u(job, status="complete", progress=1.0, message="Done")
        return PipelineResult(tr, meta, False, time.monotonic() - t0, key)
