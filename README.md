# youtube-transcript-mcp

A production-grade **YouTube transcription & research MCP server**. Gives any MCP client
(Claude Desktop, ZCode, Cursor, ChatGPT, coding agents, ...) the ability to go from a
YouTube URL to a **timestamped, searchable, chunked transcript** — with a caption-first
pipeline that avoids needless transcription, local faster-whisper as the fallback, and a
persistent SQLite cache.

```
YouTube URL -> metadata -> captions? --yes--> normalize ----\
                            |                                  --> cache --> MCP response
                            no                                 /
                        download audio -> faster-whisper ----/
```

## Highlights

- **Caption-first**: uses YouTube manual/auto captions when usable (seconds, no model, free);
  falls back to **local faster-whisper** only when captions are missing or forced.
  Transcript responses always state their source: `youtube_manual` / `youtube_auto` / `whisper`.
- **Word-level timestamps** from json3 auto-captions and whisper, when requested.
- **LLM-first responses**: compact `[HH:MM:SS] text` lines by default (not giant JSON),
  pagination + chunking for hours-long videos, hard response-size cap with navigation hints.
- **Search**: literal / case-sensitive / regex / fuzzy (rapidfuzz) with context windows and
  clickable `&t=SECONDSs` jump links.
- **Persistent SQLite cache** keyed by `video + language + provider + model + options` —
  never transcribes the same configuration twice; different configs coexist for diffing.
- **Background jobs** with progress stages and cancellation for long transcriptions.
- **Honest heuristics**: extractive summaries, topic maps, key moments and auto-chapters are
  clearly labeled heuristics — no fake confidence scores, no faked speaker labels.
- **Structured errors**: `{error: VIDEO_PRIVATE, message, retryable, hint}` — never stack traces.

## Requirements

- **Python 3.10–3.13** (built and tested on 3.12; ctranslate2 has no 3.14 wheels yet)
- **No ffmpeg required** — faster-whisper decodes audio via bundled PyAV
- Windows / macOS / Linux; CPU works (int8), CUDA used automatically when available
- Internet access for YouTube; first whisper run downloads the model from HuggingFace

## Installation

```bash
# conda example (any Python 3.10-3.13 env works, venv included)
conda create -n ytmcp python=3.12
conda activate ytmcp

cd mcp_server
pip install -e .            # or: pip install -e ".[dev]" for pytest

cp .env.example .env        # optional; defaults are sane
```

### GPU acceleration (optional, Windows + NVIDIA)

ctranslate2 uses CUDA when a GPU is detected. If the driver is present but the CUDA 12
runtime DLLs are not, the server automatically falls back to CPU. To enable GPU:

```bash
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12 nvidia-cuda-runtime-cu12
```

The server registers those DLL directories automatically on Windows. On Linux install
CUDA 12 + cuDNN 9 system-wide. If your GPU setup misbehaves, force CPU with `DEVICE=cpu`.

## Running

```bash
python -m src.server.mcp_server          # stdio (for MCP clients)
# or the installed console script:
youtube-transcript-mcp
```

## Web UI (optional)

A local browser UI over the same pipeline and cache — video player, synced transcript,
search with highlighting, chapters, summaries:

```bash
python -m src.webapp.app                 # -> http://127.0.0.1:8765
```

- Click any transcript line, search result or chapter to seek the player.
- "Follow playback" highlights the current line as the video plays.
- Anything transcribed in the UI is cached for MCP clients (and vice versa).
- Binds to 127.0.0.1 only — personal tool, not a public service.

## MCP client configuration

Claude Desktop / ZCode / Cursor (`claude_desktop_config.json` or equivalent):

```json
{
  "mcpServers": {
    "youtube-transcript": {
      "command": "C:\\Users\\Ali Irfan\\miniconda3\\envs\\ytmcp\\python.exe",
      "args": ["-m", "src.server.mcp_server"],
      "cwd": "C:\\Users\\Ali Irfan\\Desktop\\mcp_server"
    }
  }
}
```

macOS/Linux example:

```json
{
  "mcpServers": {
    "youtube-transcript": {
      "command": "/home/you/miniconda3/envs/ytmcp/bin/python",
      "args": ["-m", "src.server.mcp_server"],
      "cwd": "/home/you/mcp_server"
    }
  }
}
```

`cwd` can be omitted if the package is pip-installed (non-editable works too).

## MCP tools (12)

| Tool | Purpose |
|---|---|
| `youtube_transcribe` | Entry point: caption-first transcript, cached. Options: language, model, word_timestamps, force_retranscribe, format (compact/detailed/json/srt/vtt), wait/timeout for long jobs. |
| `youtube_get_transcript` | Cached retrieval with start/end slicing (`"12:30"` or seconds), offset/max_segments pagination, timestamp_format. |
| `youtube_get_segment` | Exact interval, e.g. start=`01:22:15` end=`01:27:30`. |
| `youtube_search_transcript` | Literal/case/regex/fuzzy search with context segments and `&t=`s jump links. |
| `youtube_video_metadata` | Title, channel, duration, description, caption languages, cached versions, processing status. |
| `youtube_list_chapters` | YouTube-native > description-parsed > optional heuristic (clearly labeled). |
| `youtube_generate_summary` | Extractive styles: executive/detailed/bullets/key_takeaways/chapter_summaries/action_items/quotes/all. |
| `youtube_find_key_moments` | Cue-phrase scan (conclusions, demos, announcements) with timestamps + links. |
| `youtube_extract_topics` | Timestamped topic map (top terms per chapter/window). |
| `youtube_compare_transcripts` | Diff two cached versions (e.g. captions vs whisper). |
| `youtube_transcription_status` | Job progress: queued -> fetching_metadata -> fetching_captions -> downloading_audio -> transcribing -> processing_timestamps -> indexing -> complete. |
| `youtube_cancel_transcription` | Cancel a running job. |

**Resources**: `youtube://video/{id}/transcript`, `.../metadata`, `.../chapters`
**Prompts**: `analyze_youtube_video`, `research_youtube_video`, `summarize_youtube_video`

## Example session

```
> youtube_transcribe(url="https://www.youtube.com/watch?v=VIDEO_ID")
Video: Some Conference Talk
Video ID: VIDEO_ID | URL: https://www.youtube.com/watch?v=VIDEO_ID
Duration: 00:58:12 | Channel: Someone
Transcript source: youtube_auto | Language: en | Model: - | Segments: 812

[00:00:00] ...
[Showing 40 of 812 segments (through 00:05:12). More: youtube_get_transcript with
 start=00:05:12 or offset=40 ...]

> youtube_search_transcript(video="VIDEO_ID", query="PostgreSQL", context_segments=2)
[00:14:32 - 00:14:41]  https://www.youtube.com/watch?v=VIDEO_ID&t=872s
   [00:14:29] ...
>> [00:14:32] we migrated our database to PostgreSQL because ...
   [00:14:39] ...
```

## Configuration

All settings live in `.env` (see `.env.example`); key ones:

| Variable | Default | Notes |
|---|---|---|
| `TRANSCRIPTION_PROVIDER` | `faster-whisper` | or `openai-compatible`, `none` (captions-only) |
| `WHISPER_MODEL` | `small` | tiny/base/small/medium/large-v3 |
| `DEVICE` / `COMPUTE_TYPE` | `auto` | auto = CUDA+float16 when usable, else CPU+int8; broken CUDA runtimes auto-fall back to CPU |
| `PREFER_CAPTIONS` | `true` | caption-first optimization |
| `LANGUAGE_FALLBACKS` | `en` | when video language is unavailable |
| `CACHE_DIR` / `CACHE_TTL_DAYS` / `MAX_CACHE_ENTRIES` | `./data/cache` / 30 / 1000 | SQLite cache; ttl `0` = expire immediately, negative = never |
| `MAX_VIDEO_DURATION` | `14400` (4h) | safety limit |
| `MAX_DOWNLOAD_SIZE_MB` | `4096` | safety limit |
| `MAX_RESPONSE_CHARS` | `60000` | response truncation with navigation hints |
| `ENABLE_DIARIZATION` | `false` | architecture exists, model not wired (see Limitations) |
| `ENABLE_SEMANTIC_SEARCH` | `false` | search index designed for later vector search |

### About API keys (important)

Transcription is **local** — no API keys needed or used. The optional
`openai-compatible` provider is for real speech-to-text endpoints (`WHISPER_API_BASE_URL`
+ `WHISPER_API_KEY`, e.g. OpenAI or Groq whisper). **Chat-LLM keys (DeepSeek, Grok chat)
cannot be used for transcription** — those APIs have no audio endpoints.

## Performance expectations

- Captions path: a 3.5-minute video resolved in ~3.6s in the verified E2E run
  (metadata + captions + cache). Hour-long videos typically take seconds.
- Whisper path (CPU, int8): roughly realtime ÷ 2–6 depending on model and CPU.
  `tiny` ≫ `base` > `small` > `medium`. GPU (float16): large-v3 handles hour-long
  videos comfortably.
- First whisper use downloads the model from HuggingFace (`tiny` ~75 MB, `small` ~460 MB,
  `large-v3` ~1.5 GB) into the local HF cache.
- Cached transcripts return in milliseconds until TTL/entry eviction.

## Privacy & security

- URLs are strictly validated against a YouTube host allowlist; media access goes through
  yt-dlp as a library (no shell, no string-built commands).
- Audio temp files are written to `TEMP_DIR` and deleted after transcription.
- Everything runs locally; transcripts stay in your `CACHE_DIR` SQLite file.
- Download size and video duration limits are enforced before/after fetch.

## Testing

```bash
pip install -e ".[dev]"
pytest               # 120 tests: URL parsing, timestamps, caption parsing (json3/vtt),
                     # formatters (SRT/VTT/compact), chunking, search, chapters, cache,
                     # error mapping, pipeline routing/cancel, MCP tool schemas
python scripts/smoke_client.py [url]   # real end-to-end over stdio against YouTube
```

## Troubleshooting

- **`DOWNLOAD_FAILED` / HTTP 403 on audio**: YouTube is throttling your IP after repeated
  downloads. The client rotates player clients automatically; wait a few minutes if it
  persists. Captions (the default path) are unaffected.
- **`MODEL_LOAD_FAILED`**: first run needs HuggingFace access to fetch the model; check
  internet/disk. `WHISPER_MODEL=tiny` is the lightest option.
- **CUDA errors** (`cublas64_12.dll ...`): GPU runtime DLLs missing — either install the
  `nvidia-*-cu12` wheels (see GPU section) or set `DEVICE=cpu`.
- **`BOT_CHECK` / `AGE_RESTRICTED`**: YouTube wants cookies; yt-dlp supports cookie
  configuration but it is intentionally not enabled by default.
- **Server logs** go to stderr (`LOG_LEVEL=DEBUG` for verbose); stdout carries only the
  MCP protocol.

## Limitations (honest list)

- **Speaker diarization**: plumbed (segments carry `speaker`, cache keys include the flag,
  requests are answered with an explicit "not identified" note) but no diarization model is
  wired in — pyannote + HF token would be the natural add. Speaker labels, if ever present,
  distinguish voices only; they never identify people.
- **Semantic search**: keyword/regex/fuzzy only. The search interface is structured so a
  vector index can slot in behind the same tool.
- Auto-caption **vtt fallback** (when json3 is unavailable) has segment-level timestamps
  only; rolling-window dedup is best-effort.
- Age-restricted / members-only / bot-checked videos fail with clear errors unless yt-dlp
  is configured with cookies (not enabled by default).
- Summaries/topics/chapters are transparent heuristics, not LLM output.
- Live streams: metadata is fetched, but transcription of ongoing streams is unsupported.

## Project layout

```
src/
  server/         mcp_server, context (wiring), tools/ (12), resources, prompts
  webapp/         local web UI (Starlette API + static front-end, port 8765)
  youtube/        url_parser, client (yt-dlp), captions (json3/vtt parsing + selection)
  transcription/  provider abstraction, faster_whisper, whisper_api, pipeline
  transcript/     models, formatter, chunker, search, chapters, summarize, compare
  cache/          database (SQLite), repository (keys, TTL, versions)
  jobs/           manager (progress, cancellation)
  config/         settings (.env)
  utils/          errors, timestamps, logging
tests/            120 unit/integration tests (network mocked)
scripts/          smoke_client.py (real E2E)
```
