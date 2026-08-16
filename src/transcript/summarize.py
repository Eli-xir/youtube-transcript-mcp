"""Extractive summaries, topics and key moments.

IMPORTANT: these are transparent term-frequency/cue-phrase heuristics, NOT an
LLM and NOT scientific confidence scores. Every output is labeled as such.
The calling LLM is encouraged to reason over the transcript itself (spec section 1).
"""
from __future__ import annotations

import re
from collections import Counter

from src.transcript.chapters import _STOPWORDS, _top_terms
from src.utils.timestamps import format_seconds
from src.youtube.url_parser import timestamp_url

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

_ACTION_CUES = re.compile(
    r"\b(make sure|be sure|you should|you need to|you must|don't forget|next step|"
    r"action item|homework|try (this|it) yourself|go ahead and|before you (go|start))\b", re.I)

_MOMENT_CUES = re.compile(
    r"\b(most important|key (point|takeaway|idea)|in conclusion|to (summarize|conclude)|"
    r"let me (show|demonstrate)|here'?s a demonstration|demo|biggest (mistake|difference|change)|"
    r"announcement|important to (note|remember|understand)|the (catch|trick|secret) is|"
    r"question (from|for) (you|the)|common (mistake|question))\b", re.I)


def sentences_from_segments(segments: list[dict]) -> list[dict]:
    """Split segments into sentences; each keeps its start timestamp.

    Uses word timestamps for exact timing when present, else the segment start.
    """
    out: list[dict] = []
    for s in segments:
        text = s.get("text", "")
        if not text:
            continue
        if s.get("words"):
            words = s["words"]
            wi = 0
            for piece in _SENT_SPLIT.split(text):
                if not piece.strip():
                    continue
                # find first word of this piece by consuming tokens
                tokens = piece.split()
                while wi < len(words) and words[wi].get("word", "").strip() not in piece:
                    wi += 1
                start = words[wi]["start"] if wi < len(words) else s["start"]
                out.append({"text": piece.strip(), "start": start})
                wi += len(tokens)
        else:
            start = s["start"]
            for piece in _SENT_SPLIT.split(text):
                if piece.strip():
                    out.append({"text": piece.strip(), "start": start})
    return out


def _tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z'-]{2,}", text.lower()) if w not in _STOPWORDS]


def _score_sentences(sentences: list[dict]) -> list[float]:
    tf = Counter()
    for s in sentences:
        tf.update(_tokenize(s["text"]))
    if not tf:
        return [0.0] * len(sentences)
    scores = []
    for s in sentences:
        toks = _tokenize(s["text"])
        if not toks:
            scores.append(0.0)
            continue
        scores.append(sum(tf[t] for t in set(toks)) / len(toks) ** 0.5)
    return scores


def _overlap(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def build_summary(payload: dict, chapters: list[dict] | None = None,
                  style: str = "executive", max_points: int = 6) -> str:
    segments = payload.get("segments", [])
    sentences = sentences_from_segments(segments)
    if not sentences:
        return "No transcript available to summarize."
    scores = _score_sentences(sentences)
    ranked = sorted(range(len(sentences)), key=lambda i: scores[i], reverse=True)
    label = "Extractive summary (term-frequency heuristic, not LLM-generated)"

    def ts(i: int) -> str:
        return format_seconds(sentences[i]["start"])

    def top_n_distinct(n: int) -> list[int]:
        chosen: list[int] = []
        chosen_sets: list[set] = []
        for i in ranked:
            if len(chosen) >= n:
                break
            toks = set(_tokenize(sentences[i]["text"]))
            if any(_overlap(toks, cs) > 0.5 for cs in chosen_sets):
                continue
            chosen.append(i)
            chosen_sets.append(toks)
        return sorted(chosen)

    lines: list[str] = [label, ""]

    if style in ("executive", "all"):
        picks = top_n_distinct(3 if len(sentences) > 10 else min(3, len(sentences)))
        lines.append("EXECUTIVE SUMMARY")
        lines.append(" ".join(sentences[i]["text"] for i in picks))
        lines.append("")

    if style in ("bullets", "all"):
        lines.append("KEY POINTS")
        for i in top_n_distinct(max_points):
            lines.append(f"- [{ts(i)}] {sentences[i]['text']}")
        lines.append("")

    if style in ("key_takeaways", "all"):
        lines.append("KEY TAKEAWAYS")
        for i in top_n_distinct(max_points):
            lines.append(f"* {sentences[i]['text']} ({ts(i)})")
        lines.append("")

    if style in ("detailed", "all"):
        lines.append("DETAILED SUMMARY")
        step = max(1, len(sentences) // max_points)
        for i in range(0, len(sentences), step):
            lines.append(f"[{ts(i)}] {sentences[i]['text']}")
        lines.append("")

    if style in ("chapter_summaries", "all") and chapters:
        lines.append("CHAPTER SUMMARIES")
        for c in chapters:
            in_ch = [i for i, s in enumerate(sentences) if c["start"] <= s["start"] < c["end"]]
            if not in_ch:
                continue
            in_ch_by_score = sorted(in_ch, key=lambda i: scores[i], reverse=True)[:2]
            lines.append(f"[{c['timestamp']}] {c['title']}")
            for i in sorted(in_ch_by_score):
                lines.append(f"   - {sentences[i]['text']}")
        lines.append("")

    if style in ("action_items", "all"):
        lines.append("ACTION ITEMS (cue-phrase heuristic -- verify before acting)")
        found = [i for i, s in enumerate(sentences) if _ACTION_CUES.search(s["text"])]
        if not found:
            lines.append("   (none detected)")
        for i in found[:max_points]:
            lines.append(f"- [{ts(i)}] {sentences[i]['text']}")
        lines.append("")

    if style in ("quotes", "all"):
        lines.append("NOTABLE LINES (extractive)")
        cand = [i for i in ranked if 40 <= len(sentences[i]["text"]) <= 250][:max_points]
        for i in sorted(cand):
            lines.append(f'- "{sentences[i]["text"]}" [{ts(i)}]')
        lines.append("")

    return "\n".join(lines).rstrip()


def key_moments(payload: dict, max_results: int = 12) -> list[dict]:
    """Cue-phrase scan for noteworthy moments (heuristic, honestly labeled)."""
    video_id = payload.get("video_id", "")
    out = []
    for s in payload.get("segments", []):
        m = _MOMENT_CUES.search(s.get("text", ""))
        if m:
            out.append({
                "cue": m.group(0).lower(),
                "start": s["start"],
                "end": s["end"],
                "timestamp": format_seconds(s["start"]),
                "text": s["text"],
                "url": timestamp_url(video_id, s["start"]),
            })
        if len(out) >= max_results:
            break
    return out


def extract_topics(payload: dict, chapters: list[dict] | None = None,
                   top: int = 6) -> list[dict]:
    """Topic map: top content terms per chapter (or per 10-min window)."""
    segments = payload.get("segments", [])
    windows = chapters or []
    if not windows:
        dur = payload.get("duration") or (segments[-1]["end"] if segments else 0)
        t = 0.0
        while t < dur:
            windows.append({"title": None, "start": t, "end": min(t + 600, dur)})
            t += 600
    out = []
    for w in windows:
        in_range = [s for s in segments if s["end"] > w["start"] and s["start"] < w["end"]]
        if not in_range:
            continue
        terms = _top_terms(" ".join(s["text"] for s in in_range), top)
        if not terms:
            continue
        out.append({
            "start": w["start"],
            "end": w["end"],
            "timestamp": format_seconds(w["start"]),
            "topics": [t.capitalize() for t in terms],
        })
    return out


def render_key_moments(moments: list[dict], title: str | None = None) -> str:
    parts = ["Key moments (heuristic cue-phrase detection -- not LLM judgment)"]
    if title:
        parts[0] += f" -- {title}"
    parts.append("")
    if not moments:
        parts.append("(none detected)")
    for m in moments:
        parts.append(f"[{m['timestamp']}] ({m['cue']}) {m['text']}")
        parts.append(f"    {m['url']}")
    return "\n".join(parts)


def render_topics(topics: list[dict], title: str | None = None) -> str:
    parts = ["Topic map (term-frequency heuristic)"]
    if title:
        parts[0] += f" -- {title}"
    parts.append("")
    for t in topics:
        parts.append(f"[{t['timestamp']} - {format_seconds(t['end'])}] {', '.join(t['topics'])}")
    return "\n".join(parts)
