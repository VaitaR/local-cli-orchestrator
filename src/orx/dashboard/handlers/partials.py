"""HTMX partial route handlers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["partials"])


def _get_prism_language(file_path: str) -> str | None:
    """Map file extension to Prism.js language class.

    Args:
        file_path: Path to the artifact file.

    Returns:
        Prism.js language class (e.g., 'language-python') or None for plain text.
    """
    ext = Path(file_path).suffix.lower()

    # Map extensions to Prism languages
    extension_map = {
        # Python
        ".py": "python",
        ".pyi": "python",
        # YAML
        ".yaml": "yaml",
        ".yml": "yaml",
        # Markdown
        ".md": "markdown",
        ".markdown": "markdown",
        # Bash/Shell
        ".sh": "bash",
        ".bash": "bash",
        ".zsh": "bash",
        ".fish": "bash",
        # JSON
        ".json": "json",
        # JavaScript
        ".js": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".jsx": "jsx",
        # Diff
        ".diff": "diff",
        ".patch": "diff",
        # Configuration files
        ".toml": "ini",
        ".ini": "ini",
        ".cfg": "ini",
        ".conf": "ini",
        ".xml": "markup",
        ".html": "markup",
        ".htm": "markup",
        ".css": "css",
        ".sql": "sql",
        ".rst": "markdown",
        ".txt": None,
    }

    return extension_map.get(ext)


def _is_binary_file(content: bytes, path: str) -> bool:
    """Check if content is binary based on content and extension.

    Args:
        content: File content as bytes.
        path: File path.

    Returns:
        True if file appears to be binary.
    """
    # Check for binary content indicators
    if b'\x00' in content[:8192]:
        return True

    # Check file extension
    ext = Path(path).suffix.lower()
    binary_extensions = {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
        ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z",
        ".exe", ".dll", ".so", ".dylib", ".bin",
        ".pyc", ".pyo",
    }

    return ext in binary_extensions


def _build_metrics_context(
    *,
    run_metrics: dict[str, Any],
    stage_metrics: list[dict[str, Any]],
    fallback_duration_ms: int,
    fallback_model: str | None,
) -> dict[str, Any]:
    duration_ms = int(run_metrics.get("total_duration_ms") or fallback_duration_ms)
    tokens = run_metrics.get("tokens")

    if not tokens and stage_metrics:
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0
        tool_calls = 0

        for stage_metric in stage_metrics:
            stage_tokens = stage_metric.get("tokens")
            if not isinstance(stage_tokens, dict):
                continue

            input_tokens += int(stage_tokens.get("input") or 0)
            output_tokens += int(stage_tokens.get("output") or 0)
            total_tokens += int(stage_tokens.get("total") or 0)
            tool_calls += int(stage_tokens.get("tool_calls") or 0)

        if total_tokens > 0:
            tokens = {
                "input": input_tokens,
                "output": output_tokens,
                "total": total_tokens,
            }
            if tool_calls > 0:
                tokens["tool_calls"] = tool_calls

    stages: list[dict[str, Any]] = []
    for stage_metric in stage_metrics:
        stage_tokens = stage_metric.get("tokens")
        error_info = stage_metric.get("error_info")
        failure_msg = stage_metric.get("failure_message")

        # Build error display
        error_display = None
        if error_info:
            error_display = error_info.get("message", failure_msg)
        elif failure_msg:
            error_display = failure_msg

        # Get model info with fallback
        model = stage_metric.get("model")
        executor = stage_metric.get("executor")
        fallback_applied = stage_metric.get("fallback_applied", False)
        original_model = stage_metric.get("original_model")

        stages.append(
            {
                "name": stage_metric.get("stage", "unknown"),
                "item_id": stage_metric.get("item_id"),
                "attempt": stage_metric.get("attempt", 1),
                "duration": float(stage_metric.get("duration_ms") or 0) / 1000.0,
                "status": stage_metric.get("status", "unknown"),
                "tokens": stage_tokens.get("total")
                if isinstance(stage_tokens, dict)
                else None,
                "tokens_in": stage_tokens.get("input")
                if isinstance(stage_tokens, dict)
                else None,
                "tokens_out": stage_tokens.get("output")
                if isinstance(stage_tokens, dict)
                else None,
                "tool_calls": stage_tokens.get("tool_calls")
                if isinstance(stage_tokens, dict)
                else None,
                "model": model,
                "executor": executor,
                "fallback_applied": fallback_applied,
                "original_model": original_model,
                "error": error_display,
                "failure_category": stage_metric.get("failure_category"),
                "llm_duration": float(stage_metric.get("llm_duration_ms") or 0)
                / 1000.0,
                "gates": stage_metric.get("gates", []),
            }
        )

    # Calculate total LLM time
    total_llm_time = sum(s["llm_duration"] for s in stages)

    return {
        "tokens": tokens,
        "duration": float(duration_ms) / 1000.0,
        "llm_duration": total_llm_time,
        "fix_loops": run_metrics.get("fix_attempts_total"),
        "model": run_metrics.get("model") or fallback_model,
        "engine": run_metrics.get("engine") or fallback_model,
        "stages": stages,
        "stages_failed": run_metrics.get("stages_failed", 0),
        "items_total": run_metrics.get("items_total", 0),
        "items_completed": run_metrics.get("items_completed", 0),
        "items_failed": run_metrics.get("items_failed", 0),
    }


@router.get("/active-runs", response_class=HTMLResponse)
async def active_runs(request: Request):
    """Render active runs table (polled every 3s)."""
    templates = request.app.state.templates
    store = request.app.state.store
    config = request.app.state.config

    runs = store.list_runs(active_only=True)

    return templates.TemplateResponse(
        "partials/active_runs.html",
        {
            "request": request,
            "runs": runs,
            "max_concurrency": config.max_concurrency,
        },
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

    context: dict[str, object] = {
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
    elif tab == "metrics":
        run_metrics = cast(dict[str, Any], store.get_run_metrics(run_id) or {})
        stage_metrics = cast(list[dict[str, Any]], store.get_stage_metrics(run_id))

        context["metrics"] = _build_metrics_context(
            run_metrics=run_metrics,
            stage_metrics=stage_metrics,
            fallback_duration_ms=run.elapsed_ms or 0,
            fallback_model=run.engine,
        )

    return templates.TemplateResponse(template_name, context)


@router.get("/artifact/{run_id}", response_class=HTMLResponse)
async def artifact_preview(
    request: Request,
    run_id: str,
    path: str = Query(..., description="Relative path to artifact"),
):
    """Render artifact content preview with syntax highlighting."""
    templates = request.app.state.templates
    store = request.app.state.store

    content = store.get_artifact(run_id, path)
    if content is None:
        return HTMLResponse(
            "<div>Artifact not found or not allowed</div>", status_code=404
        )

    # Check if file is binary
    if _is_binary_file(content, path):
        return templates.TemplateResponse(
            "partials/artifact_preview.html",
            {
                "request": request,
                "path": path,
                "content": None,
                "is_binary": True,
                "size_bytes": len(content),
                "run_id": run_id,
                "line_count": None,
            },
        )

    # Try to decode as text
    try:
        text_content = content.decode("utf-8")
    except UnicodeDecodeError:
        return templates.TemplateResponse(
            "partials/artifact_preview.html",
            {
                "request": request,
                "path": path,
                "content": None,
                "is_binary": True,
                "size_bytes": len(content),
                "run_id": run_id,
                "line_count": None,
            },
        )

    # Detect language for syntax highlighting
    language = _get_prism_language(path)

    # Calculate line count
    line_count = len(text_content.splitlines())

    return templates.TemplateResponse(
        "partials/artifact_preview.html",
        {
            "request": request,
            "path": path,
            "content": text_content,
            "is_binary": False,
            "language": language,
            "run_id": run_id,
            "line_count": line_count,
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
    run = store.get_run(run_id)
    is_running = run.is_active if run else False

    return cast(
        HTMLResponse,
        templates.TemplateResponse(
            "partials/log_tail.html",
            {
                "request": request,
                "run_id": run_id,
                "log_name": name,
                "content": chunk.content if chunk else "",
                "next_cursor": chunk.cursor if chunk else cursor,
                "has_more": chunk.has_more if chunk else False,
                "is_running": is_running,
                "poll_interval": config.poll_interval_logs,
                "lines": lines,
            },
        ),
    )
