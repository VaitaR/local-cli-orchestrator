"""Entry point for running the orx MCP server.

Usage:
    python -m orx.mcp                          # stdio (default)
    python -m orx.mcp --transport sse          # SSE  on :8422
"""

from __future__ import annotations

from orx.mcp.server import mcp

if __name__ == "__main__":
    mcp.run()
