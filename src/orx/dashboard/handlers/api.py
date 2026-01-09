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
    available models and stage-specific model defaults for each engine.
    """
    from orx.config import EngineType, OrxConfig, StageName

    # Load project config (orx.yaml) if available.
    #
    # Backward compatibility: older configs may omit newer keys like
    # executors.<engine>.available_models and executors.<engine>.stage_models.
    # In that case we want to fall back to OrxConfig.default() for UI options.
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

    def _effective_available_models(
        exec_cfg: Any, default_exec_cfg: Any
    ) -> list[str]:
        if "available_models" in getattr(exec_cfg, "model_fields_set", set()):
            return list(exec_cfg.available_models)
        return list(default_exec_cfg.available_models)

    def _effective_stage_models(exec_cfg: Any, default_exec_cfg: Any) -> dict[str, str]:
        merged: dict[str, str] = dict(default_exec_cfg.stage_models)
        if "stage_models" in getattr(exec_cfg, "model_fields_set", set()):
            merged.update(exec_cfg.stage_models)

        # Always return a value for every known stage so the UI can build
        # a complete per-stage grid even with partial configs.
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

        engine_data = {
            "value": e.value,
            "label": e.value.capitalize(),
            "is_test": e == EngineType.FAKE,
            "available_models": [],
            "stage_models": {},
        }

        # Add model info from config (with defaults for backward compatibility)
        if e == EngineType.CODEX:
            engine_data["available_models"] = _effective_available_models(
                orx_config.executors.codex, default_config.executors.codex
            )
            engine_data["stage_models"] = _effective_stage_models(
                orx_config.executors.codex, default_config.executors.codex
            )
        elif e == EngineType.GEMINI:
            engine_data["available_models"] = _effective_available_models(
                orx_config.executors.gemini, default_config.executors.gemini
            )
            engine_data["stage_models"] = _effective_stage_models(
                orx_config.executors.gemini, default_config.executors.gemini
            )

        engines.append(engine_data)

    # Get available stages
    stages = [
        {"value": s.value, "label": s.value.replace("_", " ").title()}
        for s in StageName
    ]

    default_engine = orx_config.engine.type.value
    engine_values = {e["value"] for e in engines}
    if default_engine not in engine_values and engines:
        default_engine = engines[0]["value"]

    return {
        "engines": engines,
        "stages": stages,
        "default_engine": default_engine,
    }
