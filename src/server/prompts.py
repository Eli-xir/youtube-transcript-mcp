"""MCP prompts: guided workflows for common YouTube research tasks (spec section 15)."""
from __future__ import annotations

from src.server import context

_mcp = context.mcp


@_mcp.prompt()
def analyze_youtube_video(url: str) -> str:
    """Structured deep-analysis workflow for a YouTube video."""
    return f"""Analyze this YouTube video thoroughly: {url}

Work step by step using the youtube-transcript tools:
1. youtube_video_metadata(url="{url}") -- title, duration, channel, caption availability.
2. youtube_transcribe(url="{url}") -- get the timestamped transcript (chunked if long).
3. youtube_list_chapters(url="{url}") -- structure of the video; use ai_chapters=true only if no real chapters exist.
4. youtube_search_transcript for the most relevant topics to your analysis.
5. youtube_get_segment / youtube_get_transcript with start/end to read key sections in full.

Produce: an overview, a chapter-by-chapter breakdown, key claims WITH timestamp citations
([HH:MM:SS] plus https://www.youtube.com/watch?v=VIDEO_ID&t=SECONDSs links), and an
assessment. Quote exactly when quoting; mark inference as inference."""


@_mcp.prompt()
def research_youtube_video(url: str, topic: str = "") -> str:
    """Evidence-oriented research workflow with timestamped citations."""
    focus = f' focusing on "{topic}"' if topic else ""
    return f"""Research this YouTube video as primary-source material{focus}: {url}

Method:
1. youtube_video_metadata(url="{url}") for context.
2. youtube_transcribe(url="{url}") to obtain the transcript.
3. youtube_search_transcript(video="{url}", query="...", context_segments=2) for each
   relevant keyword/theme (use fuzzy=true for approximate quotes).
4. Read full context around the best hits with youtube_get_segment.

Deliver: findings supported by timestamped quotes (cite as [HH:MM:SS] and include the
&t=SECONDSs link), note which claims are the speaker's opinion vs fact, and explicitly
flag anything you could NOT verify in the transcript rather than guessing."""


@_mcp.prompt()
def summarize_youtube_video(url: str) -> str:
    """Summary workflow: overview, chapters, key ideas, key timestamps."""
    return f"""Summarize this YouTube video: {url}

Steps:
1. youtube_video_metadata(url="{url}") -- scope and duration.
2. youtube_transcribe(url="{url}") -- transcript.
3. youtube_list_chapters(url="{url}") -- structure (ai_chapters=true if none).
4. Optionally youtube_generate_summary(video="{url}", style="all") for a heuristic draft,
   then improve it by reading the transcript sections yourself.

Output: a 2-3 sentence overview, a chapter-by-chapter breakdown, the key ideas with
[HH:MM:SS] timestamps for each, and a short 'worth watching at' list of links."""
