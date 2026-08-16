"""Logging setup. MCP stdio uses stdout for the protocol, so ALL logs go to stderr."""
from __future__ import annotations

import logging
import sys

_NOISY = ("httpx", "httpcore", "urllib3", "asyncio")


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if root.handlers:  # already configured
        root.setLevel(getattr(logging, level, logging.INFO))
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s"))
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
