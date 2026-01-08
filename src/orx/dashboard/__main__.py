"""Entry point for running the dashboard as a module.

Usage:
    python -m orx.dashboard
    python -m orx.dashboard --host 0.0.0.0 --port 8080
"""

import argparse
import sys

import uvicorn

from .config import DashboardConfig


def main() -> int:
    """Run the ORX Dashboard server."""
    parser = argparse.ArgumentParser(
        description="ORX Dashboard - Local web UI for monitoring orx runs"
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Host to bind to (default: 127.0.0.1, or ORX_DASHBOARD_HOST env var)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to bind to (default: 8421, or ORX_DASHBOARD_PORT env var)",
    )
    parser.add_argument(
        "--runs-root",
        default=None,
        help="Path to runs directory (default: ./runs, or ORX_RUNS_ROOT env var)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode",
    )

    args = parser.parse_args()

    # Build config from env vars and CLI args
    config = DashboardConfig()
    
    # CLI args override env vars
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.runs_root:
        from pathlib import Path
        config.runs_root = Path(args.runs_root)
    if args.debug:
        config.debug = True

    print(f"🚀 Starting ORX Dashboard")
    print(f"   Runs root: {config.runs_root}")
    print(f"   URL: http://{config.host}:{config.port}")
    print()

    uvicorn.run(
        "orx.dashboard:create_app",
        factory=True,
        host=config.host,
        port=config.port,
        reload=args.reload,
        log_level="debug" if config.debug else "info",
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
