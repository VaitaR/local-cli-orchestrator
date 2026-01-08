"""ORX Dashboard - Local web UI for monitoring and controlling orx runs.

This package provides a FastAPI-based dashboard that:
- Shows active and recent runs with live status updates
- Provides access to run artifacts, diffs, and logs
- Allows starting and cancelling runs
- Displays run metrics and timeline

Usage:
    # Start the dashboard server
    python -m orx.dashboard

    # Or via CLI
    orx dashboard

Environment variables:
    ORX_RUNS_ROOT: Directory containing runs/ (default: ./runs or ~/.orx/runs)
    ORX_DASHBOARD_HOST: Host to bind (default: 127.0.0.1)
    ORX_DASHBOARD_PORT: Port to bind (default: 8000)
"""

from orx.dashboard.config import DashboardConfig
from orx.dashboard.server import create_app

__all__ = ["create_app", "DashboardConfig"]
