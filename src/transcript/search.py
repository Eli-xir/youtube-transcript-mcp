"""Transcript search: literal, regex and fuzzy, with context windows (spec section 8).

Designed so a semantic/vector index can be added later behind the same interface.
"""
from __future__ import annotations

import re

from src.utils.errors import ErrorCode, YoutubeMcpError
from src.utils.timestamps import format_seconds
from src.youtube.url_parser import timestamp_url

try:
    from rapidfuzz import fuzz
    _HAVE_RAPIDFUZZ = True
except ImportError:  # pragma: no cover
    import difflib
    _HAVE_RAPIDFUZZ = False


def _fuzzy_score(query: str, text: str) -> float:
    if _HAVE_RAPIDFUZZ:
        return fuzz.partial_ratio(query, text)
    m = difflib.SequenceMatcher(None, query, text).find_longest_match(0, len(query), 0, len(text))
    return (m.size / len(query) * 100) if query else 0.0


def search_segments(video_id: str, segments: list[dict], query: str, *,
                    case_sensitive: bool = False, regex: bool = False, fuzzy: bool = False,
                    fuzzy_threshold: float = 70.0, max_results: int = 10,
                    context: int = 1) -> dict:
    """Returns {query, match_count, results:[{start,end,timestamp,url,matched,context_lines}]}.

    Adjacent matching segments are merged into one result; context_lines carry
    `>>` markers on the matched lines.
    """
    if not query or not query.strip():
        raise YoutubeMcpError(ErrorCode.INVALID_ARGUMENT, "query must be a non-empty string")
    if regex:
        try:
            pattern = re.compile(query, 0 if case_sensitive else re.IGNORECASE)
        except re.error as e:
            raise YoutubeMcpError(ErrorCode.INVALID_ARGUMENT, f"Invalid regex: {e}") from e

    q = query if case_sensitive else query.lower()

    def matches(text: str) -> bool:
        t = text if case_sensitive else text.lower()
        if regex:
            return bool(pattern.search(text))
        if fuzzy:
            return _fuzzy_score(q, t) >= fuzzy_threshold
        return q in t

    hit_idx = [i for i, s in enumerate(segments) if matches(s.get("text", ""))]
    # merge adjacent/near-adjacent hits into single results
    groups: list[list[int]] = []
    for i in hit_idx:
        if groups and i - groups[-1][-1] <= context + 1:
            groups[-1].append(i)
        else:
            groups.append([i])
    truncated = len(groups) > max(0, max_results)
    groups = groups[:max(0, max_results)]

    results = []
    for group in groups:
        lo = max(0, group[0] - context)
        hi = min(len(segments), group[-1] + context + 1)
        ctx_lines = []
        for j in range(lo, hi):
            s = segments[j]
            marker = ">> " if j in group else "   "
            ctx_lines.append(f"{marker}[{format_seconds(s['start'])}] {s['text']}")
        first, last = segments[group[0]], segments[group[-1]]
        results.append({
            "start": first["start"],
            "end": last["end"],
            "timestamp": format_seconds(first["start"]),
            "end_timestamp": format_seconds(last["end"]),
            "url": timestamp_url(video_id, first["start"]),
            "matched": [segments[j]["text"] for j in group],
            "context_lines": ctx_lines,
        })
    return {
        "video_id": video_id,
        "query": query,
        "match_count": len(groups),
        "total_matching_segments": len(hit_idx),
        "truncated": truncated,
        "results": results,
    }


def render_search(result: dict, title: str | None = None) -> str:
    parts = []
    if title:
        parts.append(f"Video: {title}")
    parts.append(f"Found {result['match_count']} match(es) for {result['query']!r}:")
    parts.append("")
    for r in result["results"]:
        parts.append(f"[{r['timestamp']} - {r['end_timestamp']}]  {r['url']}")
        parts.extend(r["context_lines"])
        parts.append("")
    if result["results"]:
        parts.append("Timestamped link format: https://www.youtube.com/watch?v=VIDEO_ID&t=SECONDSs")
    return "\n".join(parts).rstrip()
