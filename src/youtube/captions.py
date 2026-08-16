"""Caption track selection and parsing (json3 + vtt) into normalized segments.

json3 is preferred: auto-captions carry genuine per-word timings, which gives
high-quality word-level timestamps without any transcription.
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass

from src.transcript.models import Segment, Word

_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class CaptionPayload:
    kind: str        # "manual" | "auto"
    language: str
    ext: str         # "json3" | "vtt"
    text: str


def _clean(text: str) -> str:
    text = _TAG_RE.sub("", text)
    text = html.unescape(text).replace("\xa0", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def select_caption_track(subtitles: dict, automatic_captions: dict,
                         requested: str | None, fallbacks: tuple[str, ...] = ("en",)) -> tuple[str, str] | None:
    """Pick the best caption track. Returns (kind, language_key) or None.

    Priority: manual[requested] > auto[requested] > manual/auto same-base-language >
    manual/auto for each fallback > any manual > any auto (original language).
    """
    subs = {k.lower(): v for k, v in (subtitles or {}).items() if v}
    autos = {k.lower(): v for k, v in (automatic_captions or {}).items() if v}

    def base(l: str) -> str:
        return l.split("-")[0].lower()

    def find(store: dict, kind: str, langs: list[str], exact_only: bool) -> tuple[str, str] | None:
        for lang in langs:
            for key in store:
                if key == lang or (not exact_only and base(key) == base(lang)):
                    return kind, key
        return None

    if requested:
        req = requested.lower()
        return (find(subs, "manual", [req], True) or find(autos, "auto", [req], True)
                or find(subs, "manual", [req], False) or find(autos, "auto", [req], False))

    chain = list(fallbacks) + ["en"]
    for lang in chain:
        hit = (find(subs, "manual", [lang], True) or find(autos, "auto", [lang], True)
               or find(subs, "manual", [lang], False) or find(autos, "auto", [lang], False))
        if hit:
            return hit
    # last resort: any manual track, then any auto track (usually the video's original language)
    if subs:
        return "manual", sorted(subs)[0]
    if autos:
        return "auto", sorted(autos)[0]
    return None


# ---------------------------------------------------------------- json3

def parse_json3_words(raw: str) -> list[Word]:
    """Parse YouTube json3 caption format into a word timeline.

    Auto-caption rolling-window duplicates are removed by deduping exact
    (text, start) pairs, which is what the duplicated events produce.
    """
    data = json.loads(raw)
    seen: set[tuple[str, float]] = set()
    words: list[Word] = []
    for ev in data.get("events", []):
        segs = ev.get("segs")
        if not segs:
            continue
        t0 = ev.get("tStartMs", 0) / 1000.0
        for seg in segs:
            text = _clean(seg.get("utf8") or "")
            if not text:
                continue
            start = t0 + (seg.get("tOffsetMs", 0) / 1000.0)
            key = (text, round(start, 3))
            if key in seen:
                continue
            seen.add(key)
            words.append(Word(start=start, end=start, text=text))
    words.sort(key=lambda w: w.start)
    # assign ends: next word's start, else a short default
    for i, w in enumerate(words):
        nxt = words[i + 1].start if i + 1 < len(words) else None
        w.end = nxt if (nxt is not None and nxt > w.start) else w.start + 0.4
    return words


def words_to_segments(words: list[Word], max_words: int = 28, max_chars: int = 220,
                      max_dur: float = 8.0, pause: float = 0.9) -> list[Segment]:
    """Group a word timeline into naturally-sized, readable segments.

    Breaks after sentence-final punctuation, long pauses, or size limits.
    """
    segments: list[Segment] = []
    buf: list[Word] = []

    def flush():
        nonlocal buf
        if not buf:
            return
        text = " ".join(w.text for w in buf).strip()
        if text:
            segments.append(Segment(
                id=len(segments),
                start=buf[0].start,
                end=max(buf[-1].end, buf[-1].start + 0.15),
                text=text,
                words=list(buf),
            ))
        buf = []

    for i, w in enumerate(words):
        buf.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        chars = sum(len(x.text) for x in buf) + len(buf)
        if (
            w.text.endswith((".", "!", "?"))
            or len(buf) >= max_words
            or chars >= max_chars
            or (w.end - buf[0].start) >= max_dur
            or (nxt is not None and nxt.start - w.end > pause)
            # word-start gap catches pauses when ends were synthesized from next starts
            or (nxt is not None and nxt.start - w.start > pause + 0.6)
        ):
            flush()
    flush()
    return segments


# ---------------------------------------------------------------- vtt

_CUE_RE = re.compile(
    r"((?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3})")


def _ts(tok: str) -> float:
    parts = tok.replace(",", ".").split(":")
    parts = [float(p) for p in parts]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def parse_vtt(raw: str) -> list[Segment]:
    """Parse VTT into segments. No word timestamps from this format.

    Handles auto-caption rolling windows: cues identical to or starting with
    the previous cue's text are collapsed to their new suffix.
    """
    segments: list[Segment] = []
    prev_text = ""
    blocks = re.split(r"\n\s*\n", raw)
    for block in blocks:
        lines = [l.rstrip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        m = None
        for i, line in enumerate(lines):
            m = _CUE_RE.search(line)
            if m:
                text_lines = lines[i + 1:]
                break
        if not m:
            continue
        start, end = _ts(m.group(1)), _ts(m.group(2))
        text = _clean(" ".join(text_lines))
        if not text:
            continue
        if text == prev_text:
            continue  # exact rolling duplicate
        if prev_text and text.lower().startswith(prev_text.lower()) and len(text) > len(prev_text):
            text = text[len(prev_text):].strip()  # keep only the new suffix
            if not text:
                continue
        prev_text = " ".join(_clean(" ".join(text_lines)).split())
        segments.append(Segment(id=len(segments), start=start, end=max(end, start + 0.1), text=text))
    return segments


def caption_payload_to_segments(payload: CaptionPayload) -> tuple[list[Segment], bool]:
    """Parse a CaptionPayload into (segments, has_word_timestamps)."""
    if payload.ext == "json3":
        try:
            words = parse_json3_words(payload.text)
            if words:
                return words_to_segments(words), True
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    return parse_vtt(payload.text), False
