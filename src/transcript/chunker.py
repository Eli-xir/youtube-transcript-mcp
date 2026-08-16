"""Long-video handling: time slicing, pagination and chunk indexes (spec section 7)."""
from __future__ import annotations

from src.utils.timestamps import format_seconds


def slice_segments(segments: list[dict], start_s: float | None, end_s: float | None) -> list[dict]:
    """Segments overlapping [start_s, end_s]. None = open-ended."""
    out = []
    for s in segments:
        if start_s is not None and s["end"] <= start_s:
            continue
        if end_s is not None and s["start"] >= end_s:
            continue
        out.append(s)
    return out


def paginate_segments(segments: list[dict], offset: int = 0, limit: int | None = None) -> list[dict]:
    """Segment-level pagination."""
    if offset < 0:
        offset = 0
    chunk = segments[offset:]
    return chunk if limit is None else chunk[:max(0, limit)]


def chunk_ranges(segments: list[dict], window_s: float = 600.0) -> list[dict]:
    """Split the timeline into fixed windows aligned to segment boundaries."""
    if not segments:
        return []
    last_end = max(s["end"] for s in segments)
    n_chunks = max(1, int(last_end // window_s) + (1 if last_end % window_s else 0))
    ranges = []
    for i in range(n_chunks):
        a, b = i * window_s, (i + 1) * window_s
        idx = [j for j, s in enumerate(segments) if s["end"] > a and s["start"] < b]
        if not idx:
            continue
        ranges.append({
            "chunk": len(ranges) + 1,
            "total_chunks": None,  # filled by caller
            "start": a,
            "end": b,
            "start_timestamp": format_seconds(a),
            "end_timestamp": format_seconds(b),
            "segment_count": len(idx),
        })
    total = len(ranges)
    for r in ranges:
        r["total_chunks"] = total
    return ranges


def chunk_footer(payload: dict, shown: list[dict], total_segments: int,
                 offset: int, window_s: float = 600.0) -> str | None:
    """Pagination footer telling the LLM how to get the rest."""
    if total_segments and len(shown) < total_segments:
        last_end = shown[-1]["end"] if shown else 0
        return (
            f"[Showing {len(shown)} of {total_segments} segments "
            f"(through {format_seconds(last_end)}). More: youtube_get_transcript with "
            f"start={format_seconds(last_end)} or offset={offset + len(shown)}, or "
            f"format='json' for full data.]"
        )
    return None
