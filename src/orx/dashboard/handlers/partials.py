"""HTMX partial route handlers."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["partials"])


@router.get("/active-runs", response_class=HTMLResponse)
async def active_runs(request: Request):
    """Render active runs table (polled every 3s)."""
    templates = request.app.state.templates
    store = request.app.state.store

    runs = store.list_runs(active_only=True)

    return templates.TemplateResponse(
        "partials/active_runs.html",
        {"request": request, "runs": runs},
    )


@router.get("/recent-runs", response_class=HTMLResponse)
async def recent_runs(request: Request, limit: int = Query(20, le=100)):
    """Render recent runs table."""
    templates = request.app.state.templates
    store = request.app.state.store

    runs = store.list_runs(active_only=False, limit=limit)
    # Filter out active runs (they're shown separately)
    runs = [r for r in runs if not r.is_active]

    return templates.TemplateResponse(
        "partials/recent_runs.html",
        {"request": request, "runs": runs},
    )


@router.get("/start-run-form", response_class=HTMLResponse)
async def start_run_form(request: Request):
    """Render the start run form."""
    templates = request.app.state.templates
    config = request.app.state.config

    return templates.TemplateResponse(
        "partials/start_run_form.html",
        {
            "request": request,
            "default_repo_path": str(config.get_runs_dir().parent),
        },
    )


@router.get("/run-header/{run_id}", response_class=HTMLResponse)
async def run_header(request: Request, run_id: str):
    """Render run header (polled while running)."""
    templates = request.app.state.templates
    store = request.app.state.store
    config = request.app.state.config

    run = store.get_run(run_id)
    if run is None:
        return HTMLResponse("<div>Run not found</div>", status_code=404)

    return templates.TemplateResponse(
        "partials/run_header.html",
        {
            "request": request,
            "run": run,
            "poll_interval": config.poll_interval_active,
        },
    )


@router.get("/run-tab/{run_id}", response_class=HTMLResponse)
async def run_tab(
    request: Request,
    run_id: str,
    tab: str = Query("overview", pattern="^(overview|artifacts|diff|logs|metrics)$"),
):
    """Render a tab content for run detail page."""
    templates = request.app.state.templates
    store = request.app.state.store
    config = request.app.state.config

    run = store.get_run(run_id)
    if run is None:
        return HTMLResponse("<div>Run not found</div>", status_code=404)

    template_name = f"partials/tab_{tab}.html"

    context: dict = {
        "request": request,
        "run": run,
        "run_id": run_id,
    }

    # Add tab-specific data
    if tab == "artifacts":
        context["artifacts"] = store.list_artifacts(run_id)
    elif tab == "logs":
        context["logs"] = store.list_logs(run_id)
        context["poll_interval"] = config.poll_interval_logs
    elif tab == "metrics" and run.has_metrics:
        context["run_metrics"] = store.get_run_metrics(run_id)
        context["stage_metrics"] = store.get_stage_metrics(run_id)

    return templates.TemplateResponse(template_name, context)


@router.get("/artifact/{run_id}", response_class=HTMLResponse)
async def artifact_preview(
    request: Request,
    run_id: str,
    path: str = Query(..., description="Relative path to artifact"),
):
    """Render artifact content preview."""
    templates = request.app.state.templates
    store = request.app.state.store

    content = store.get_artifact(run_id, path)
    if content is None:
        return HTMLResponse("<div>Artifact not found or not allowed</div>", status_code=404)

    # Try to decode as text
    try:
        text_content = content.decode("utf-8")
    except UnicodeDecodeError:
        text_content = f"[Binary file: {len(content)} bytes]"

    return templates.TemplateResponse(
        "partials/artifact_preview.html",
        {
            "request": request,
            "path": path,
            "content": text_content,
            "run_id": run_id,
        },
    )


@router.get("/diff/{run_id}", response_class=HTMLResponse)
async def diff_view(request: Request, run_id: str):
    """Render diff content."""
    templates = request.app.state.templates
    store = request.app.state.store

    diff = store.get_diff(run_id)

    return templates.TemplateResponse(
        "partials/diff_view.html",
        {
            "request": request,
            "run_id": run_id,
            "diff": diff,
            "has_diff": diff is not None,
        },
    )


@router.get("/log-tail/{run_id}", response_class=HTMLResponse)
async def log_tail(
    request: Request,
    run_id: str,
    name: str = Query(..., description="Log file name"),
    cursor: int = Query(0, description="Line offset"),
    lines: int = Query(200, le=1000, description="Number of lines"),
) -> HTMLResponse:
    """Render log tail content."""
    templates = request.app.state.templates
    store = request.app.state.store
    config = request.app.state.config

    chunk = store.tail_log(run_id, name, cursor=cursor, lines=lines)

    return cast(
        HTMLResponse,
        templates.TemplateResponse(
            "partials/log_tail.html",
            {
                "request": request,
                "run_id": run_id,
                "log_name": name,
                "chunk": chunk,
                "poll_interval": config.poll_interval_logs,
            },
        ),
    )
