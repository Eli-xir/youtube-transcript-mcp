"""Timestamp parsing/formatting used everywhere."""
from __future__ import annotations

import re

_TS_RE = re.compile(r"^(?:(\d+):)?([0-5]?\d):([0-5]?\d(?:\.\d{1,3})?)$")


def format_seconds(seconds: float, style: str = "hhmmss", ms: bool = False) -> str:
    """Format seconds as a timestamp string.

    style: 'hhmmss' -> 01:02:03 | 'mmss' -> 1:02:03 or 2:03 | 'seconds' -> 3723.5
    ms appends .mmm to non-seconds styles.
    """
    seconds = max(0.0, float(seconds))
    if style == "seconds":
        return f"{seconds:.2f}"
    frac = seconds - int(seconds)
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if style == "mmss":
        base = f"{m}:{s:02d}" if h == 0 else f"{h}:{m:02d}:{s:02d}"
    else:  # hhmmss
        base = f"{h:02d}:{m:02d}:{s:02d}"
    if ms and frac > 0:
        base += f".{int(round(frac * 1000)):03d}"
    return base


def parse_timestamp(value: str | float | int) -> float:
    """Parse 'SS', 'MM:SS', 'HH:MM:SS[.mmm]' or a raw number of seconds into seconds."""
    if isinstance(value, (int, float)):
        v = float(value)
        if v < 0:
            raise ValueError(f"negative timestamp: {value}")
        return v
    v = str(value).strip()
    if not v:
        raise ValueError("empty timestamp")
    if ":" not in v:
        try:
            f = float(v)
            if f < 0:
                raise ValueError
            return f
        except ValueError:
            raise ValueError(f"invalid timestamp: {value!r}") from None
    m = _TS_RE.match(v)
    if not m:
        raise ValueError(f"invalid timestamp: {value!r} (expected MM:SS, HH:MM:SS or seconds)")
    h = int(m.group(1)) if m.group(1) else 0
    return h * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def human_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def srt_timestamp(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    ms = int(round((seconds - int(seconds)) * 1000))
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def vtt_timestamp(seconds: float) -> str:
    return srt_timestamp(seconds).replace(",", ".")
