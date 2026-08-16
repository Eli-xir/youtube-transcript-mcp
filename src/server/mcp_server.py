"""MCP server entrypoint.

Run:  python -m src.server.mcp_server        (stdio, for MCP clients)
      youtube-transcript-mcp                 (installed console script)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def create_app():
    """Import context (wires settings/cache/pipeline) and register tools/resources/prompts."""
    from src.server import context          # noqa: F401  (creates the FastMCP app)
    from src.server import resources, prompts  # noqa: F401  (register via decorators)
    from src.server import tools            # noqa: F401  (registers all tools)
    return context.mcp


def main() -> None:
    mcp = create_app()
    from src.server import context
    transport = context.settings.mcp_transport
    if transport not in ("stdio", "sse", "streamable-http"):
        transport = "stdio"
    logger.info("starting youtube-transcript MCP server (%s)", transport)
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
