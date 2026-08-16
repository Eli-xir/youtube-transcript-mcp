"""Transcript diff: compare two cached versions (e.g. YouTube captions vs whisper)."""
from __future__ import annotations

import difflib

from src.utils.timestamps import format_seconds


def compare_payloads(a: dict, b: dict, max_diffs: int = 10, sim_threshold: float = 0.7) -> dict:
    """Align two transcripts by nearest start time and report the worst matches."""
    segs_a, segs_b = a.get("segments", []), b.get("segments", [])

    def words(segs):
        return sum(len(s.get("text", "").split()) for s in segs)

    def stats(p, segs):
        avg = (sum(s["end"] - s["start"] for s in segs) / len(segs)) if segs else 0
        return {
            "source": p.get("transcript_source"),
            "model": p.get("model") or None,
            "language": p.get("language"),
            "segments": len(segs),
            "words": words(segs),
            "avg_segment_s": round(avg, 2),
            "has_word_timestamps": bool(segs and segs[0].get("words")),
        }

    diffs = []
    j = 0
    for sa in segs_a:
        while j < len(segs_b) - 1 and abs(segs_b[j + 1]["start"] - sa["start"]) <= abs(segs_b[j]["start"] - sa["start"]):
            j += 1
        sb = segs_b[j] if j < len(segs_b) else None
        if sb is None or abs(sb["start"] - sa["start"]) > 2.5:
            continue
        sim = difflib.SequenceMatcher(None, sa.get("text", ""), sb.get("text", "")).ratio()
        if sim < sim_threshold:
            diffs.append({
                "timestamp": format_seconds(sa["start"]),
                "similarity": round(sim, 2),
                a.get("transcript_source", "a"): sa.get("text", ""),
                b.get("transcript_source", "b"): sb.get("text", ""),
            })
        if len(diffs) >= max_diffs:
            break

    return {
        "a": stats(a, segs_a),
        "b": stats(b, segs_b),
        "aligned_pairs_compared": min(len(segs_a), len(segs_b)) if segs_a and segs_b else 0,
        "differing_pairs_found": len(diffs),
        "sample_differences": diffs,
    }


def render_compare(result: dict) -> str:
    a, b = result["a"], result["b"]
    parts = [
        "Transcript comparison (cached versions of the same video):",
        "",
        f"A: source={a['source']} model={a['model'] or '-'} lang={a['language']} "
        f"segments={a['segments']} words={a['words']} word_ts={a['has_word_timestamps']}",
        f"B: source={b['source']} model={b['model'] or '-'} lang={b['language']} "
        f"segments={b['segments']} words={b['words']} word_ts={b['has_word_timestamps']}",
        f"Aligned pairs compared: {result['aligned_pairs_compared']} | "
        f"meaningfully different: {result['differing_pairs_found']}",
        "",
    ]
    if result["sample_differences"]:
        parts.append("Sample differences (similarity < 0.7):")
        for d in result["sample_differences"]:
            parts.append(f"[{d['timestamp']}] (sim {d['similarity']})")
            for k, v in d.items():
                if k in ("timestamp", "similarity"):
                    continue
                parts.append(f"  {k}: {v}")
            parts.append("")
    else:
        parts.append("Aligned segments are textually near-identical.")
    return "\n".join(parts).rstrip()
