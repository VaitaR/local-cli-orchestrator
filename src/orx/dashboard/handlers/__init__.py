"""Route handlers for the dashboard."""

from orx.dashboard.handlers.api import router as api_router
from orx.dashboard.handlers.pages import router as pages_router
from orx.dashboard.handlers.partials import router as partials_router

__all__ = ["api_router", "pages_router", "partials_router"]
