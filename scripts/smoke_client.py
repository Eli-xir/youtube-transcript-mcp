"""Real end-to-end smoke test: spawns the MCP server over stdio and calls tools.

Usage:  python scripts/smoke_client.py [video_url]
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


async def call(session, name, args):
    t0 = time.monotonic()
    result = await session.call_tool(name, args)
    dt = time.monotonic() - t0
    print(f"\n=== {name} ({dt:.1f}s) ===")
    for block in result.content:
        text = getattr(block, "text", None)
        if text is None:
            continue
        if len(text) > 1200:
            text = text[:1200] + f"\n... [{len(text)} chars total]"
        print(text)
    return result


async def main():
    video = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.server.mcp_server"],
        cwd=str(ROOT),
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print(f"Connected. {len(tools.tools)} tools: "
                  f"{', '.join(t.name for t in tools.tools)}")

            await call(session, "youtube_video_metadata", {"url": video})
            await call(session, "youtube_transcribe", {"url": video})
            await call(session, "youtube_search_transcript",
                       {"video": video, "query": "never gonna give you up", "context_segments": 1})
            await call(session, "youtube_get_segment",
                       {"video": video, "start": "0:05", "end": "0:15"})
            await call(session, "youtube_list_chapters", {"url": video, "ai_chapters": True})
            await call(session, "youtube_generate_summary", {"video": video, "style": "bullets"})
            await call(session, "youtube_find_key_moments", {"video": video})
    print("\nSMOKE TEST COMPLETE")


if __name__ == "__main__":
    asyncio.run(main())
