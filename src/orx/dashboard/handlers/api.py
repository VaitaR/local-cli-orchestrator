"""API route handlers for run control."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from orx.dashboard.store.models import StartRunRequest, StartRunResponse

router = APIRouter(tags=["api"])

logger = structlog.get_logger()


class PipelineCreateRequest(BaseModel):
    """Request to create a new pipeline."""

    name: str
    base_on: str = "standard"


class PipelineUpdateRequest(BaseModel):
    """Request to update a pipeline."""

    pipeline_data: dict[str, Any]


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
            pipeline=payload.pipeline,
            pipeline_override=payload.pipeline_override,
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


@router.post("/runs/{run_id}/restart")
async def restart_run(request: Request, run_id: str):
    """Restart a failed or completed orx run.

    Returns:
        JSON with restart status and new run_id if applicable.
    """
    store = request.app.state.store
    worker = request.app.state.worker

    # Get the original run
    original_run = store.get_run(run_id)
    if original_run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if original_run.is_active:
        return JSONResponse(
            {
                "status": "already_running",
                "run_id": run_id,
                "message": "Run is still active, cannot restart",
            },
            status_code=409,
        )

    try:
        # Start a new run with the same configuration
        new_run_id = worker.start_run(
            task=original_run.task,
            repo_path=original_run.repo_path,
            base_branch=original_run.base_branch,
            pipeline=original_run.pipeline,
            config_overrides=original_run.config_overrides or {},
        )
        return JSONResponse(
            {
                "status": "restarted",
                "original_run_id": run_id,
                "new_run_id": new_run_id,
                "message": "Run restarted successfully",
            }
        )
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error("Failed to restart run", run_id=run_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to restart run: {e}") from e


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
        {"value": level.value, "label": level.name.title()} for level in ReasoningLevel
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


# ============================================================================
# Pipeline Management Endpoints
# ============================================================================


@router.get("/pipelines")
async def list_pipelines():
    """List all available pipelines.

    Returns:
        JSON with pipeline list.
    """
    from orx.pipeline.registry import PipelineRegistry

    registry = PipelineRegistry.load()

    pipelines = []
    for p in registry.pipelines:
        pipelines.append({
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "builtin": p.builtin,
            "node_count": len(p.nodes),
            "default_context": p.default_context,
            "nodes": [
                {
                    "id": n.id,
                    "type": n.type.value,
                    "template": n.template,
                    "inputs": n.inputs,
                    "outputs": n.outputs,
                    "description": n.description,
                    "config": {
                        "gates": n.config.gates if n.config else [],
                        "concurrency": n.config.concurrency if n.config else 1,
                        "timeout_seconds": n.config.timeout_seconds if n.config else 600,
                    },
                }
                for n in p.nodes
            ],
        })

    return {"pipelines": pipelines}


@router.get("/pipelines/{pipeline_id}")
async def get_pipeline(pipeline_id: str):
    """Get a specific pipeline.

    Returns:
        JSON with pipeline details.
    """
    from orx.pipeline.registry import PipelineNotFoundError, PipelineRegistry

    registry = PipelineRegistry.load()

    try:
        pipeline = registry.get(pipeline_id)
    except PipelineNotFoundError:
        raise HTTPException(status_code=404, detail=f"Pipeline not found: {pipeline_id}") from None

    return pipeline.model_dump(mode="json")


@router.post("/pipelines")
async def create_pipeline(payload: PipelineCreateRequest):
    """Create a new custom pipeline.

    Returns:
        JSON with created pipeline.
    """
    from orx.pipeline.definition import PipelineDefinition
    from orx.pipeline.registry import PipelineNotFoundError, PipelineRegistry

    registry = PipelineRegistry.load()

    # Check if exists
    if registry.exists(payload.name):
        raise HTTPException(status_code=409, detail=f"Pipeline already exists: {payload.name}")

    # Get base pipeline
    try:
        base_pipeline = registry.get(payload.base_on)
    except PipelineNotFoundError:
        raise HTTPException(status_code=404, detail=f"Base pipeline not found: {payload.base_on}") from None

    # Create new pipeline
    new_pipeline = PipelineDefinition(
        id=payload.name,
        name=payload.name.replace("_", " ").title(),
        description=f"Custom pipeline based on {payload.base_on}",
        nodes=base_pipeline.nodes.copy(),
    )

    registry.add(new_pipeline)
    registry.save()

    return {"status": "created", "pipeline": new_pipeline.model_dump(mode="json")}


@router.put("/pipelines/{pipeline_id}")
async def update_pipeline(pipeline_id: str, payload: PipelineUpdateRequest):
    """Update a pipeline.

    Returns:
        JSON with updated pipeline.
    """
    from orx.pipeline.constants import BUILTIN_PIPELINE_IDS
    from orx.pipeline.definition import PipelineDefinition
    from orx.pipeline.registry import PipelineRegistry

    registry = PipelineRegistry.load()

    # Check if builtin
    if pipeline_id in BUILTIN_PIPELINE_IDS:
        raise HTTPException(status_code=403, detail="Cannot modify builtin pipeline")

    # Check if exists
    if not registry.exists(pipeline_id):
        raise HTTPException(status_code=404, detail=f"Pipeline not found: {pipeline_id}")

    # Validate and update
    try:
        updated = PipelineDefinition.model_validate(payload.pipeline_data)
        if updated.id != pipeline_id:
            raise HTTPException(status_code=400, detail="Pipeline ID cannot be changed")

        registry.add(updated)
        registry.save()

        return {"status": "updated", "pipeline": updated.model_dump(mode="json")}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/pipelines/{pipeline_id}")
async def delete_pipeline(pipeline_id: str):
    """Delete a custom pipeline.

    Returns:
        JSON confirmation.
    """
    from orx.pipeline.constants import BUILTIN_PIPELINE_IDS
    from orx.pipeline.registry import PipelineNotFoundError, PipelineRegistry

    registry = PipelineRegistry.load()

    # Check if builtin
    if pipeline_id in BUILTIN_PIPELINE_IDS:
        raise HTTPException(status_code=403, detail="Cannot delete builtin pipeline")

    # Check if exists
    if not registry.exists(pipeline_id):
        raise HTTPException(status_code=404, detail=f"Pipeline not found: {pipeline_id}")

    try:
        registry.delete(pipeline_id)
        registry.save()
    except (ValueError, PipelineNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    return {"status": "deleted", "pipeline_id": pipeline_id}


@router.get("/context-blocks")
async def list_context_blocks():
    """List available context blocks.

    Returns:
        JSON with context block definitions.
    """
    from orx.pipeline.constants import AUTO_EXTRACT_CONTEXTS

    blocks = [
        {
            "id": "task",
            "description": "Task description (user input)",
            "auto_extract": False,
            "required": True,
        },
        {
            "id": "plan",
            "description": "High-level plan document",
            "auto_extract": False,
            "required": False,
        },
        {
            "id": "spec",
            "description": "Technical specification",
            "auto_extract": False,
            "required": False,
        },
        {
            "id": "backlog",
            "description": "Work items backlog",
            "auto_extract": False,
            "required": False,
        },
        {
            "id": "repo_map",
            "description": "File/directory structure snapshot",
            "auto_extract": "repo_map" in AUTO_EXTRACT_CONTEXTS,
            "required": False,
        },
        {
            "id": "tooling_snapshot",
            "description": "Stack and tooling config snapshot",
            "auto_extract": "tooling_snapshot" in AUTO_EXTRACT_CONTEXTS,
            "required": False,
        },
        {
            "id": "verify_commands",
            "description": "Gate command descriptions",
            "auto_extract": "verify_commands" in AUTO_EXTRACT_CONTEXTS,
            "required": False,
        },
        {
            "id": "agents_context",
            "description": "AGENTS.md content",
            "auto_extract": "agents_context" in AUTO_EXTRACT_CONTEXTS,
            "required": False,
        },
        {
            "id": "architecture",
            "description": "ARCHITECTURE.md overview",
            "auto_extract": "architecture" in AUTO_EXTRACT_CONTEXTS,
            "required": False,
        },
        {
            "id": "error_logs",
            "description": "Previous error logs",
            "auto_extract": False,
            "required": False,
        },
        {
            "id": "patch_diff",
            "description": "Current patch diff",
            "auto_extract": False,
            "required": False,
        },
        {
            "id": "current_item",
            "description": "Current work item (for map nodes)",
            "auto_extract": False,
            "required": False,
        },
        {
            "id": "file_snippets",
            "description": "Relevant file snippets",
            "auto_extract": False,
            "required": False,
        },
    ]

    return {"blocks": blocks}


@router.get("/node-types")
async def list_node_types():
    """List available node types for pipeline editor.

    Returns:
        JSON with node type definitions.
    """
    node_types = [
        {
            "value": "llm_text",
            "label": "LLM Text Generation",
            "icon": "📝",
            "description": "Generate text output via LLM (plan, spec, review)",
            "requires_template": True,
            "has_model_config": True,
        },
        {
            "value": "llm_apply",
            "label": "LLM Apply (Filesystem)",
            "icon": "⚙️",
            "description": "Apply filesystem changes via LLM",
            "requires_template": True,
            "has_model_config": True,
        },
        {
            "value": "map",
            "label": "Map (Parallel)",
            "icon": "🔀",
            "description": "Process work items in parallel",
            "requires_template": False,
            "has_model_config": False,
            "has_concurrency": True,
        },
        {
            "value": "gate",
            "label": "Gate (Verification)",
            "icon": "✓",
            "description": "Run quality gates (ruff, pytest, etc.)",
            "requires_template": False,
            "has_model_config": False,
            "has_gates": True,
        },
        {
            "value": "custom",
            "label": "Custom Function",
            "icon": "🔧",
            "description": "Execute custom Python function",
            "requires_template": False,
            "has_model_config": False,
            "has_callable_path": True,
        },
    ]

    return {"node_types": node_types}


@router.get("/available-gates")
async def list_available_gates():
    """List available gate types for pipeline editor.

    Returns:
        JSON with gate definitions.
    """
    gates = [
        {
            "id": "ruff",
            "label": "Ruff (Linting)",
            "description": "Python linter and formatter",
            "default_enabled": True,
        },
        {
            "id": "pytest",
            "label": "Pytest (Testing)",
            "description": "Python test runner",
            "default_enabled": True,
        },
        {
            "id": "mypy",
            "label": "Mypy (Type Checking)",
            "description": "Static type checker for Python",
            "default_enabled": False,
        },
    ]

    return {"gates": gates}


@router.get("/templates")
async def list_templates():
    """List available prompt templates.

    Returns:
        JSON with template names.
    """
    from pathlib import Path

    templates_dir = Path(__file__).parent.parent.parent / "prompts" / "templates"
    templates = []

    if templates_dir.exists():
        for f in sorted(templates_dir.glob("*.md")):
            templates.append({
                "name": f.name,
                "id": f.stem,
            })

    return {"templates": templates}
