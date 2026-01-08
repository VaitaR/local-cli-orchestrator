"""Page route handlers - full HTML pages."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["pages"])


@router.get("/", response_class=HTMLResponse)
async def runs_list(request: Request):
    """Render the main runs list page."""
    templates = request.app.state.templates
    config = request.app.state.config

    return templates.TemplateResponse(
        "pages/runs.html",
        {
            "request": request,
            "title": "ORX Dashboard",
            "poll_interval_active": config.poll_interval_active,
        },
    )


@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(request: Request, run_id: str):
    """Render the run detail page."""
    templates = request.app.state.templates
    store = request.app.state.store
    config = request.app.state.config

    run = store.get_run(run_id)
    if run is None:
        return templates.TemplateResponse(
            "pages/not_found.html",
            {"request": request, "message": f"Run {run_id} not found"},
            status_code=404,
        )

    return templates.TemplateResponse(
        "pages/run_detail.html",
        {
            "request": request,
            "title": f"Run {run_id}",
            "run": run,
            "poll_interval": config.poll_interval_active,
            "poll_interval_logs": config.poll_interval_logs,
        },
    )
