"""faster-whisper provider: local, CTranslate2-based, CPU or GPU, no API keys."""
from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

from src.config.settings import Settings
from src.transcription.provider import (ProviderResult, ProviderSegment, ProviderWord,
                                        TranscriptionProvider, check_cancel)
from src.utils.errors import ErrorCode, YoutubeMcpError

logger = logging.getLogger(__name__)

_CUDA_PROBLEM = re.compile(
    r"cublas|cudnn|cuda|libcudart|driver version is insufficient|no cuda capable device",
    re.IGNORECASE)

_dll_dirs_added = False


def _register_nvidia_dll_dirs() -> None:
    """Make CUDA DLLs from pip packages (nvidia-*-cu12) discoverable on Windows.

    ctranslate2 loads cublas/cudnn lazily; the DLLs live in
    site-packages/nvidia/*/bin. Some loaders ignore os.add_dll_directory, so the
    directories are ALSO prepended to PATH (read per LoadLibrary call).
    """
    global _dll_dirs_added
    if _dll_dirs_added or sys.platform != "win32":
        return
    _dll_dirs_added = True
    try:
        import site
        sps = set(site.getsitepackages())
        try:
            sps.add(site.getusersitepackages())
        except Exception:
            pass
        for sp in sps:
            nvidia = Path(sp) / "nvidia"
            if not nvidia.is_dir():
                continue
            for sub in nvidia.iterdir():
                for cand in (sub / "bin", sub / "lib"):
                    if cand.is_dir():
                        os.add_dll_directory(str(cand))
                        os.environ["PATH"] = str(cand) + os.pathsep + os.environ.get("PATH", "")
    except Exception as e:  # non-fatal; CPU fallback still possible
        logger.debug("nvidia dll dir registration failed: %s", e)


class FasterWhisperProvider(TranscriptionProvider):
    name = "faster-whisper"

    def __init__(self, settings: Settings):
        self._s = settings
        self._models: dict[tuple, object] = {}  # (model, device, compute) -> WhisperModel
        self._cuda_broken = False  # set after a CUDA runtime failure; forces CPU

    def _resolve_hardware(self) -> tuple[str, str]:
        device = self._s.whisper_device
        compute = self._s.whisper_compute_type
        if device == "auto":
            # A driver alone is not enough: ctranslate2 needs the CUDA runtime
            # (cublas/cudnn) which may be missing -> validated on first use.
            if self._cuda_broken:
                device = "cpu"
            else:
                try:
                    import ctranslate2
                    device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
                except Exception:
                    device = "cpu"
        if device == "cuda" and self._cuda_broken:
            device = "cpu"
        if compute == "auto":
            compute = "float16" if device == "cuda" else "int8"
        return device, compute

    def _get_model(self, model_name: str, force_cpu: bool = False):
        if force_cpu:
            device, compute = "cpu", "int8"
        else:
            device, compute = self._resolve_hardware()
        key = (model_name, device, compute)
        if key not in self._models:
            try:
                if device == "cuda":
                    _register_nvidia_dll_dirs()
                from faster_whisper import WhisperModel
                logger.info("loading whisper model %r on %s (%s)", model_name, device, compute)
                self._models[key] = WhisperModel(model_name, device=device, compute_type=compute)
            except YoutubeMcpError:
                raise
            except Exception as e:
                if device == "cuda" and _CUDA_PROBLEM.search(str(e)):
                    logger.warning("CUDA unusable (%s); falling back to CPU", str(e)[:120])
                    self._cuda_broken = True
                    return self._get_model(model_name, force_cpu=True)
                raise YoutubeMcpError(
                    ErrorCode.MODEL_LOAD_FAILED,
                    f"Failed to load Whisper model {model_name!r}: {str(e)[:300]}",
                    hint="First use downloads the model from HuggingFace (needs internet). "
                         "Try a smaller WHISPER_MODEL (tiny/base) or check disk space. "
                         "Set DEVICE=cpu if GPU drivers are broken.") from e
        return self._models[key]

    def transcribe(self, audio_path, *, language=None, model=None, word_timestamps=False,
                   progress=None, cancel_event=None, deadline=None) -> ProviderResult:
        model_name = model or self._s.whisper_model
        wm = self._get_model(model_name)
        try:
            return self._run(wm, audio_path, language, word_timestamps, progress,
                             cancel_event, deadline, model_name)
        except YoutubeMcpError as e:
            device, _ = self._resolve_hardware()
            if device == "cuda" and _CUDA_PROBLEM.search(e.message or ""):
                return self._cpu_retry(audio_path, language, word_timestamps, progress,
                                       cancel_event, deadline, model_name, str(e))
            raise
        except Exception as e:
            device, _ = self._resolve_hardware()
            if device == "cuda" and _CUDA_PROBLEM.search(str(e)):
                return self._cpu_retry(audio_path, language, word_timestamps, progress,
                                       cancel_event, deadline, model_name, str(e))
            raise YoutubeMcpError(
                ErrorCode.TRANSCRIPTION_FAILED, f"faster-whisper failed: {str(e)[:300]}",
                retryable=True) from e

    def _cpu_retry(self, audio_path, language, word_timestamps, progress, cancel_event,
                   deadline, model_name, cause: str) -> ProviderResult:
        """CUDA runtime broke (lazy DLL loads surface at first op); retry once on CPU."""
        logger.warning("CUDA failed during transcription (%s); retrying on CPU", cause[:120])
        self._cuda_broken = True
        for key in [k for k in list(self._models) if k[1] == "cuda"]:
            self._models.pop(key)
        wm = self._get_model(model_name, force_cpu=True)
        return self._run(wm, audio_path, language, word_timestamps, progress,
                         cancel_event, deadline, model_name)

    def _run(self, wm, audio_path, language, word_timestamps, progress, cancel_event,
             deadline, model_name) -> ProviderResult:
        # NOTE: exceptions from wm.transcribe are intentionally NOT wrapped here so
        # the caller can inspect raw CUDA/DLL errors and retry on CPU.
        segments_iter, info = wm.transcribe(
            str(audio_path),
            language=language,
            word_timestamps=word_timestamps,
            vad_filter=self._s.vad_filter,
            beam_size=self._s.beam_size,
        )

        total = float(getattr(info, "duration", 0) or 0)
        out: list[ProviderSegment] = []
        try:
            for seg in segments_iter:
                check_cancel(cancel_event, deadline)
                if progress and total > 0:
                    progress(min(0.99, seg.end / total))
                words = [ProviderWord(w.start, w.end, w.word.strip())
                         for w in (seg.words or []) if w.word and w.word.strip()]
                text = (seg.text or "").strip()
                if text or words:
                    out.append(ProviderSegment(seg.start, seg.end, text, words))
        except YoutubeMcpError:
            raise
        except Exception as e:
            raise YoutubeMcpError(
                ErrorCode.TRANSCRIPTION_FAILED, f"faster-whisper failed mid-transcription: {str(e)[:300]}",
                retryable=True) from e
        if progress:
            progress(1.0)
        return ProviderResult(
            segments=out,
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
            model=model_name,
        )
