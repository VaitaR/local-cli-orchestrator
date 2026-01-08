"""API route handlers for run control."""

from __future__ import annotations

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
            {"status": "cancelled", "run_id": run_id, "message": "Cancellation initiated"}
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
