"""Unit tests for create_runner override semantics."""

from __future__ import annotations

from pathlib import Path

from orx.config import EngineConfig, EngineType, OrxConfig, StageExecutorConfig
from orx.runner import create_runner


def test_create_runner_engine_override_clears_stage_overrides(tmp_path: Path) -> None:
    """--engine should enforce a single engine across stages."""
    base_dir = tmp_path / "repo"
    base_dir.mkdir(parents=True)

    cfg = OrxConfig.default(EngineType.CODEX)
    cfg.stage_engines["spec"] = EngineConfig(type=EngineType.GEMINI)
    cfg.stages.plan = StageExecutorConfig(executor=EngineType.GEMINI, model="gemini-x")

    runner = create_runner(base_dir, config=cfg, engine=EngineType.CODEX)

    assert runner.config.engine.type == EngineType.CODEX
    assert runner.config.stage_engines == {}
    assert runner.config.stages.plan.executor is None
    assert runner.config.stages.plan.model is None


def test_create_runner_model_override_updates_stage_models(tmp_path: Path) -> None:
    """--model should update per-stage defaults for the selected engine."""
    base_dir = tmp_path / "repo"
    base_dir.mkdir(parents=True)

    cfg = OrxConfig.default(EngineType.CODEX)
    cfg.executors.codex.stage_models["plan"] = "codex-plan"
    cfg.stages.plan = StageExecutorConfig(model="explicit-plan")

    runner = create_runner(base_dir, config=cfg, model="global-model")

    assert runner.config.engine.model == "global-model"
    assert runner.config.executors.codex.default.model == "global-model"
    assert runner.config.executors.codex.stage_models["plan"] == "global-model"

    # Explicit stage overrides are still respected by ModelRouter.
    assert runner.config.stages.plan.model == "explicit-plan"

