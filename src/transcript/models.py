"""Core transcript data model.

The Transcript dataclass is used while building a transcript; everything downstream
(cache, tools, formatters) works on its plain-dict serialization so the whole
pipeline stays JSON-friendly and language-agnostic (translation-ready).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.utils.timestamps import format_seconds


@dataclass
class Word:
    start: float
    end: float
    text: str

    def to_dict(self) -> dict:
        return {"word": self.text, "start": round(self.start, 3), "end": round(self.end, 3)}


@dataclass
class Segment:
    id: int
    start: float
    end: float
    text: str
    words: list[Word] | None = None
    speaker: str | None = None  # diarization placeholder; never populated unless diarization runs

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self, include_words: bool = False) -> dict:
        d = {
            "id": self.id,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "timestamp": format_seconds(self.start),
            "duration": round(self.duration, 3),
            "text": self.text,
        }
        if self.speaker:
            d["speaker"] = self.speaker
        if include_words and self.words:
            d["words"] = [w.to_dict() for w in self.words]
        return d


@dataclass
class Chapter:
    title: str
    start: float
    end: float
    source: str = "youtube"  # youtube | description | heuristic

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "timestamp": format_seconds(self.start),
            "duration": round(max(0.0, self.end - self.start), 3),
            "source": self.source,
        }


def segment_from_dict(d: dict, index: int) -> Segment:
    words = None
    if d.get("words"):
        words = [Word(w["start"], w["end"], w["word"]) for w in d["words"]]
    return Segment(
        id=d.get("id", index),
        start=float(d["start"]),
        end=float(d["end"]),
        text=d.get("text", ""),
        words=words,
        speaker=d.get("speaker"),
    )


@dataclass
class Transcript:
    video_id: str
    language: str
    source: str  # youtube_manual | youtube_auto | whisper
    model: str
    segments: list[Segment]
    duration: float = 0.0
    detected_language: str | None = None
    language_probability: float | None = None
    chapters: list[Chapter] = field(default_factory=list)
    snapshot: dict = field(default_factory=dict)  # title/channel/etc at processing time
    created_at: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.segments).strip()

    def word_count(self) -> int:
        return sum(len(s.text.split()) for s in self.segments)

    def to_dict(self, include_words: bool = False) -> dict:
        return {
            "video_id": self.video_id,
            "language": self.language,
            "detected_language": self.detected_language,
            "language_probability": self.language_probability,
            "transcript_source": self.source,
            "model": self.model,
            "duration": self.duration,
            "created_at": self.created_at,
            "word_count": self.word_count(),
            "segment_count": len(self.segments),
            "has_word_timestamps": bool(self.segments and self.segments[0].words),
            "chapters": [c.to_dict() for c in self.chapters],
            "snapshot": self.snapshot,
            "notes": self.notes,
            "segments": [s.to_dict(include_words=include_words) for s in self.segments],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Transcript":
        return cls(
            video_id=d["video_id"],
            language=d.get("language", ""),
            source=d.get("transcript_source", d.get("source", "")),
            model=d.get("model", ""),
            segments=[segment_from_dict(s, i) for i, s in enumerate(d.get("segments", []))],
            duration=float(d.get("duration", 0) or 0),
            detected_language=d.get("detected_language"),
            language_probability=d.get("language_probability"),
            chapters=[Chapter(c["title"], c["start"], c["end"], c.get("source", "youtube"))
                      for c in d.get("chapters", [])],
            snapshot=dict(d.get("snapshot", {})),
            created_at=float(d.get("created_at", 0) or 0),
            notes=list(d.get("notes", [])),
        )

    def quality(self) -> dict:
        """Factual quality indicators only -- no invented confidence scores."""
        segs = self.segments
        avg = (sum(s.duration for s in segs) / len(segs)) if segs else 0.0
        return {
            "source": self.source,
            "model": self.model or None,
            "has_word_timestamps": bool(segs and segs[0].words),
            "segment_count": len(segs),
            "word_count": self.word_count(),
            "avg_segment_duration_s": round(avg, 2),
        }


def transcript_payload(tr: Transcript, include_words: bool) -> dict[str, Any]:
    return tr.to_dict(include_words=include_words)
