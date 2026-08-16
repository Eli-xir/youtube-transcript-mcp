"""Output formatters: compact / detailed / json / srt / vtt (spec section 6)."""
from __future__ import annotations

from datetime import datetime, timezone

from src.utils.timestamps import format_seconds, srt_timestamp, vtt_timestamp


def _iso(ts: float) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def build_header(payload: dict, extra_notes: list[str] | None = None) -> str:
    snap = payload.get("snapshot") or {}
    lines = [
        f"Video: {snap.get('title') or payload.get('video_id', '?')}",
        f"Video ID: {payload.get('video_id')} | URL: {snap.get('url') or ''}",
        f"Duration: {format_seconds(payload.get('duration') or 0)} | Channel: {snap.get('channel') or 'unknown'}",
        f"Transcript source: {payload.get('transcript_source')} | Language: {payload.get('language') or '?'}"
        f" | Model: {payload.get('model') or '-'} | Segments: {payload.get('segment_count', len(payload.get('segments', [])))}",
    ]
    if payload.get("created_at"):
        lines.append(f"Generated: {_iso(float(payload['created_at']))}")
    for note in (extra_notes or []):
        lines.append(f"Note: {note}")
    return "\n".join(lines)


def compact_lines(segments: list[dict], ts_style: str = "hhmmss") -> list[str]:
    return [f"[{format_seconds(s['start'], ts_style)}] {s['text']}" for s in segments]


def detailed_lines(segments: list[dict], ts_style: str = "hhmmss") -> list[str]:
    out = []
    for s in segments:
        a = format_seconds(s["start"], ts_style)
        b = format_seconds(s["end"], ts_style)
        out.append(f"[{a} -> {b}] (#{s.get('id', '?')}) {s['text']}")
    return out


def render_compact(payload: dict, segments: list[dict], ts_style: str = "hhmmss",
                   header_extra: list[str] | None = None, footer: str | None = None) -> str:
    parts = [build_header(payload, header_extra), ""]
    parts.extend(compact_lines(segments, ts_style))
    if footer:
        parts += ["", footer]
    return "\n".join(parts)


def render_detailed(payload: dict, segments: list[dict], ts_style: str = "hhmmss",
                    header_extra: list[str] | None = None, footer: str | None = None) -> str:
    parts = [build_header(payload, header_extra), ""]
    parts.extend(detailed_lines(segments, ts_style))
    if footer:
        parts += ["", footer]
    return "\n".join(parts)


def render_plain(payload: dict, segments: list[dict], header_extra: list[str] | None = None) -> str:
    parts = [build_header(payload, header_extra), "", " ".join(s["text"] for s in segments)]
    return "\n".join(parts)


def render_srt(payload: dict, segments: list[dict], header_extra: list[str] | None = None) -> str:
    parts = []
    if header_extra:
        parts.extend(f"# {n}" for n in header_extra)
    for i, s in enumerate(segments, start=1):
        parts.append(str(i))
        parts.append(f"{srt_timestamp(s['start'])} --> {srt_timestamp(s['end'])}")
        parts.append(s["text"])
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def render_vtt(payload: dict, segments: list[dict], header_extra: list[str] | None = None) -> str:
    parts = ["WEBVTT"]
    if header_extra:
        parts.append("NOTE " + " ".join(header_extra))
        parts.append("")
    for i, s in enumerate(segments, start=1):
        parts.append(f"{i}")
        parts.append(f"{vtt_timestamp(s['start'])} --> {vtt_timestamp(s['end'])}")
        parts.append(s["text"])
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def render(payload: dict, segments: list[dict], fmt: str, ts_style: str = "hhmmss",
           include_timestamps: bool = True, header_extra: list[str] | None = None,
           footer: str | None = None) -> str:
    if not include_timestamps:
        return render_plain(payload, segments, header_extra)
    if fmt == "compact":
        return render_compact(payload, segments, ts_style, header_extra, footer)
    if fmt == "detailed":
        return render_detailed(payload, segments, ts_style, header_extra, footer)
    if fmt == "srt":
        return render_srt(payload, segments, header_extra)
    if fmt == "vtt":
        return render_vtt(payload, segments, header_extra)
    raise ValueError(f"unknown format {fmt!r}")
