"""Chapter extraction: YouTube-native, description-parsed, or heuristic (spec section 1 & 17C)."""
from __future__ import annotations

import re
from collections import Counter

from src.utils.timestamps import format_seconds

_DESC_LINE = re.compile(
    r"^\s*(?:\(\s*\d+\s*\)|\d+\s*[.)]\s*)?"          # optional "(3)" / "3." list numbering
    r"((?:\d{1,2}:)?\d{1,2}:\d{2})\s*(?:-{1,2}|—|:)?\s*"  # timestamp + optional dash
    r"(.+?)\s*$")

_TS = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "so", "because", "of", "to", "in",
    "on", "for", "with", "at", "by", "from", "up", "about", "into", "over", "after", "is",
    "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "should", "could", "can", "may", "might", "shall", "this", "that",
    "these", "those", "it", "its", "we", "you", "they", "he", "she", "i", "me", "my", "our",
    "your", "their", "them", "us", "him", "her", "as", "not", "no", "yes", "just", "like",
    "know", "get", "got", "going", "really", "very", "much", "more", "most", "some", "any",
    "what", "when", "where", "which", "who", "how", "all", "also", "there", "here", "now",
}


def _parse_ts(tok: str) -> float | None:
    m = _TS.match(tok.strip())
    if not m:
        return None
    h = int(m.group(1) or 0)
    return h * 3600 + int(m.group(2)) * 60 + int(m.group(3))


def from_metadata(meta: dict) -> list[dict] | None:
    """YouTube-provided chapters (uploader-defined, from the chapter bar)."""
    chapters = meta.get("chapters")
    if not chapters:
        return None
    out = []
    for i, c in enumerate(chapters):
        start = c.get("start", c.get("start_time", 0))
        end = c.get("end", c.get("end_time", 0))
        out.append({"title": (c.get("title") or "").strip() or f"Chapter {i + 1}",
                    "start": float(start or 0), "end": float(end or 0),
                    "timestamp": format_seconds(float(start or 0)), "source": "youtube"})
    return out


def from_description(meta: dict) -> list[dict] | None:
    """Parse the '0:00 Intro' chapter convention from the description."""
    desc = meta.get("description") or ""
    duration = float(meta.get("duration") or 0)
    found: list[tuple[float, str]] = []
    for line in desc.splitlines():
        m = _DESC_LINE.match(line)
        if not m:
            continue
        ts = _parse_ts(m.group(1))
        title = m.group(2).strip().strip("-–—:")
        if ts is None or not title or len(title) > 100:
            continue
        found.append((ts, title))
    if len(found) < 2:
        return None
    found.sort(key=lambda x: x[0])
    # validity: strictly ascending
    if any(found[i + 1][0] <= found[i][0] for i in range(len(found) - 1)):
        return None
    out = []
    for i, (start, title) in enumerate(found):
        end = found[i + 1][0] if i + 1 < len(found) else (duration if duration else start + 600)
        out.append({"title": title, "start": start, "end": end,
                    "timestamp": format_seconds(start), "source": "description"})
    return out


def _top_terms(text: str, n: int = 3) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z'-]{2,}", text.lower())
    words = [w for w in words if w not in _STOPWORDS]
    if not words:
        return []
    return [t for t, _ in Counter(words).most_common(n)]


def heuristic_chapters(segments: list[dict], target_minutes: float = 8.0,
                       duration: float | None = None) -> list[dict]:
    """Heuristic topic-window chaptering (clearly labeled; NOT an LLM).

    Splits the timeline into ~target-minute windows at segment boundaries and
    titles each with its most frequent content terms.
    """
    if not segments:
        return []
    dur = duration or max(s["end"] for s in segments)
    window = target_minutes * 60
    out = []
    boundaries = [0.0]
    t = window
    while t < dur - 60:
        boundaries.append(t)
        t += window
    boundaries.append(dur)
    for i in range(len(boundaries) - 1):
        a, b = boundaries[i], boundaries[i + 1]
        in_range = [s for s in segments if s["end"] > a and s["start"] < b]
        if not in_range:
            continue
        terms = _top_terms(" ".join(s["text"] for s in in_range))
        title = ", ".join(t.capitalize() for t in terms) if terms else f"Part {len(out) + 1}"
        out.append({"title": title, "start": a, "end": b,
                    "timestamp": format_seconds(a), "source": "heuristic"})
    return out


def render_chapters(chapters: list[dict], title: str | None = None) -> str:
    parts = []
    if title:
        parts.append(f"Chapters for: {title}")
        parts.append("")
    for c in chapters:
        parts.append(f"[{c['timestamp']} - {format_seconds(c['end'])}] {c['title']}  (source: {c['source']})")
    return "\n".join(parts)
