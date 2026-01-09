"""API route handlers for run control."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from orx.dashboard.store.models import StartRunRequest, StartRunResponse

router = APIRouter(tags=["api"])


@router.post("/runs/start", response_model=StartRunResponse)
async def start_run(request: Request, payload: StartRunRequest):
    """Start a new orx run.

    Returns:
        StartRunResponse with run_id and status.
    """
    worker = request.app.state.worker

    try:
        run_id = worker.start_run(
            task=payload.task,
            repo_path=payload.repo_path,
            base_branch=payload.base_branch,
            config_overrides=payload.config_overrides or {},
        )
        return StartRunResponse(
            run_id=run_id,
            status="queued",
            message="Run queued successfully",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        # Unexpected error while creating a run — log and return 500
        logger.error("Failed to start run (unexpected)", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to create run: {e}") from e


@router.post("/runs/{run_id}/cancel")
async def cancel_run(request: Request, run_id: str):
    """Cancel a running orx run.

    Returns:
        JSON with cancellation status.
    """
    worker = request.app.state.worker

    success = worker.cancel_run(run_id)

    if success:
        return JSONResponse(
            {
                "status": "cancelled",
                "run_id": run_id,
                "message": "Cancellation initiated",
            }
        )

    # If the worker cannot cancel, fall back to the store to distinguish:
    # - run truly not found
    # - run exists but already finished
    # - run appears running but cannot be cancelled (e.g., missing pid)
    store = request.app.state.store
    run = store.get_run(run_id)
    if run is None:
        return JSONResponse(
            {"status": "not_found", "run_id": run_id, "message": "Run not found"},
            status_code=404,
        )

    if not run.is_active:
        return JSONResponse(
            {
                "status": "not_running",
                "run_id": run_id,
                "message": "Run is not running (it may have already finished)",
            }
        )

    if not run.can_cancel:
        return JSONResponse(
            {
                "status": "cannot_cancel",
                "run_id": run_id,
                "message": "Run appears active but cannot be cancelled (missing pid)",
            },
            status_code=409,
        )

    return JSONResponse(
        {
            "status": "cancel_failed",
            "run_id": run_id,
            "message": "Failed to cancel run",
        },
        status_code=500,
    )


@router.get("/runs/{run_id}/status")
async def run_status(request: Request, run_id: str):
    """Get run status (JSON).

    Returns:
        JSON with run summary.
    """
    store = request.app.state.store

    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return {
        "run_id": run.run_id,
        "status": run.status.value,
        "current_stage": run.current_stage,
        "elapsed_ms": run.elapsed_ms,
        "has_diff": run.has_diff,
        "has_metrics": run.has_metrics,
    }


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@router.get("/config/engines")
async def get_available_engines(request: Request):
    """Get available engine types, stages, and model configurations.

    Returns configuration options for the start run form, including
    available models with capabilities, and stage-specific model defaults.
    """
    from orx.config import EngineType, OrxConfig, StageName
    from orx.executors.models import (
        ReasoningLevel,
        serialize_models_for_api,
    )

    # Load project config (orx.yaml) if available.
    dashboard_config = request.app.state.config
    project_root = dashboard_config.get_runs_dir().parent
    config_path = project_root / "orx.yaml"

    try:
        if config_path.exists():
            orx_config = OrxConfig.load(config_path)
        else:
            orx_config = OrxConfig.default()
    except Exception:
        orx_config = OrxConfig.default()

    default_config = OrxConfig.default(engine_type=orx_config.engine.type)

    def _effective_stage_models(exec_cfg: Any, default_exec_cfg: Any) -> dict[str, str]:
        merged: dict[str, str] = dict(default_exec_cfg.stage_models)
        if "stage_models" in getattr(exec_cfg, "model_fields_set", set()):
            merged.update(exec_cfg.stage_models)

        fallback_model = (
            exec_cfg.default.model
            or default_exec_cfg.default.model
            or orx_config.engine.model
            or ""
        )
        for stage in StageName:
            merged.setdefault(stage.value, fallback_model)
        return merged

    # Get available engines (exclude FAKE for production UI unless in debug)
    engines = []
    for e in EngineType:
        if e == EngineType.FAKE and not dashboard_config.debug:
            continue

        # Get models with full capabilities from models.py
        models_data = serialize_models_for_api(e.value)

        engine_data = {
            "value": e.value,
            "label": e.value.capitalize(),
            "is_test": e == EngineType.FAKE,
            "models": models_data,  # Full model info with capabilities
            "available_models": [m["id"] for m in models_data],  # Backward compat
            "stage_models": {},
        }

        # Add stage-specific model defaults
        if e == EngineType.CODEX:
            engine_data["stage_models"] = _effective_stage_models(
                orx_config.executors.codex, default_config.executors.codex
            )
        elif e == EngineType.GEMINI:
            engine_data["stage_models"] = _effective_stage_models(
                orx_config.executors.gemini, default_config.executors.gemini
            )
        elif e == EngineType.COPILOT:
            engine_data["stage_models"] = _effective_stage_models(
                orx_config.executors.copilot, default_config.executors.copilot
            )
        elif e == EngineType.CLAUDE_CODE:
            engine_data["stage_models"] = _effective_stage_models(
                orx_config.executors.claude_code, default_config.executors.claude_code
            )
        elif e == EngineType.CURSOR:
            engine_data["stage_models"] = _effective_stage_models(
                orx_config.executors.cursor, default_config.executors.cursor
            )

        engines.append(engine_data)

    # Get available stages
    stages = [
        {"value": s.value, "label": s.value.replace("_", " ").title()}
        for s in StageName
    ]

    # Reasoning levels for UI
    reasoning_levels = [
        {"value": level.value, "label": level.name.title()}
        for level in ReasoningLevel
    ]

    default_engine = orx_config.engine.type.value
    engine_values = {e["value"] for e in engines}
    if default_engine not in engine_values and engines:
        default_engine = engines[0]["value"]

    return {
        "engines": engines,
        "stages": stages,
        "reasoning_levels": reasoning_levels,
        "default_engine": default_engine,
    }
