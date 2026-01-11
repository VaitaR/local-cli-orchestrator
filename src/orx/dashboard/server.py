"""FastAPI application for ORX Dashboard."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from orx.dashboard.config import DashboardConfig
from orx.dashboard.handlers import api_router, pages_router, partials_router
from orx.dashboard.store.filesystem import FileSystemRunStore
from orx.dashboard.worker import LocalWorker

# Package directories
PACKAGE_DIR = Path(__file__).parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"


def format_short_time(dt: datetime | None) -> str:
    """Format datetime to short time string (e.g., '14:32' or '2:32 PM').

    Args:
        dt: Datetime object or None.

    Returns:
        Formatted time string or empty string if dt is None.
    """
    if dt is None:
        return ""
    return dt.strftime("%H:%M")


def create_app(config: DashboardConfig | None = None) -> FastAPI:
    """Create the FastAPI application.

    Args:
        config: Optional configuration. If not provided, loads from env.

    Returns:
        Configured FastAPI application.
    """
    if config is None:
        config = DashboardConfig()

    # Create app
    app = FastAPI(
        title="ORX Dashboard",
        description="Local dashboard for monitoring and controlling orx runs",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
    )

    # Initialize services
    store = FileSystemRunStore(config)
    worker = LocalWorker(config)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # Register custom filters
    templates.env.filters["format_short_time"] = format_short_time

    # Store in app state
    app.state.config = config
    app.state.store = store
    app.state.worker = worker
    app.state.templates = templates

    # Mount static files
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Include routers
    app.include_router(pages_router)
    app.include_router(partials_router, prefix="/partials")
    app.include_router(api_router, prefix="/api")

    # Startup/shutdown events
    @app.on_event("startup")
    async def startup():
        """Start background worker on app startup."""
        worker.start()

    @app.on_event("shutdown")
    async def shutdown():
        """Stop background worker on app shutdown."""
        worker.stop()

    return app


def get_store(request: Request) -> FileSystemRunStore:
    """Get the run store from request.

    Args:
        request: FastAPI request.

    Returns:
        FileSystemRunStore instance.
    """
    return request.app.state.store


def get_worker(request: Request) -> LocalWorker:
    """Get the worker from request.

    Args:
        request: FastAPI request.

    Returns:
        LocalWorker instance.
    """
    return request.app.state.worker


def get_templates(request: Request) -> Jinja2Templates:
    """Get templates from request.

    Args:
        request: FastAPI request.

    Returns:
        Jinja2Templates instance.
    """
    return request.app.state.templates


def get_config(request: Request) -> DashboardConfig:
    """Get config from request.

    Args:
        request: FastAPI request.

    Returns:
        DashboardConfig instance.
    """
    return request.app.state.config
