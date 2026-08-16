"""Application wiring: singletons shared by all MCP tools/resources/prompts."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from src.cache.repository import TranscriptRepository
from src.config.settings import Settings
from src.jobs.manager import JobManager
from src.transcription.pipeline import TranscriptionPipeline
from src.utils.logging import setup_logging
from src.youtube.client import YouTubeClient

settings = Settings.from_env()
setup_logging(settings.log_level)

client = YouTubeClient(settings)
repo = TranscriptRepository(settings)
pipeline = TranscriptionPipeline(settings, client, repo)
jobs = JobManager()

INSTRUCTIONS = """\
YouTube transcription & research server.

Core flow: youtube_transcribe(url) once per video -> then use youtube_get_transcript /
youtube_search_transcript / youtube_get_segment / youtube_list_chapters on the cached
transcript. Transcription is caption-first: existing YouTube captions are preferred
(fast, free); local faster-whisper is the fallback when captions are missing.

Timestamps appear as [HH:MM:SS]. Long transcripts are chunked; responses include
instructions for fetching the remaining sections. Clickable timestamps use
https://www.youtube.com/watch?v=VIDEO_ID&t=SECONDSs
"""

mcp = FastMCP("youtube-transcript", instructions=INSTRUCTIONS)
