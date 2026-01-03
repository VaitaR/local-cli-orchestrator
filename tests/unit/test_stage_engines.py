"""Unit tests for stage-specific engine selection."""

from pathlib import Path

from orx.config import EngineType, OrxConfig, StageExecutorConfig
from orx.executors.base import ExecResult, LogPaths
from orx.runner import Runner


class StubExecutor:
    """Minimal executor stub for stage selection tests."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def run_text(  # pragma: no cover - not used in this test
        self,
        *,
        cwd: Path,
        prompt_path: Path,
        out_path: Path,
        logs: LogPaths,
        timeout: int | None = None,
    ) -> ExecResult:
        raise NotImplementedError

    def run_apply(  # pragma: no cover - not used in this test
        self,
        *,
        cwd: Path,
        prompt_path: Path,
        logs: LogPaths,
        timeout: int | None = None,
    ) -> ExecResult:
        raise NotImplementedError


def test_stage_engines_parse_yaml() -> None:
    """Stage engine overrides parse into EngineConfig."""
    yaml_content = """
version: "1.0"
engine:
  type: codex
stage_engines:
  plan:
    type: gemini
    extra_args: ["--model", "gemini-2.0-flash"]
  implement:
    type: codex
    extra_args: ["--model", "gpt-4.1"]
"""
    config = OrxConfig.from_yaml(yaml_content)

    assert config.stage_engines["plan"].type == EngineType.GEMINI
    assert config.stage_engines["plan"].extra_args == ["--model", "gemini-2.0-flash"]
    assert config.stage_engines["implement"].type == EngineType.CODEX
    assert config.stage_engines["implement"].extra_args == ["--model", "gpt-4.1"]


def test_stage_executor_selection(tmp_project: Path) -> None:
    """Stage contexts use stage-specific model selectors when configured."""
    # Configure stage-specific model selection
    yaml_content = """
version: "1.0"
engine:
  type: fake
stages:
  plan:
    model: "plan-model"
  implement:
    model: "implement-model"
"""
    config = OrxConfig.from_yaml(yaml_content)
    runner = Runner(config, base_dir=tmp_project, dry_run=True)

    # Get context for plan stage
    plan_ctx = runner._get_stage_context("plan")
    assert plan_ctx.model_selector.model == "plan-model"

    # Get context for implement stage
    impl_ctx = runner._get_stage_context("implement")
    assert impl_ctx.model_selector.model == "implement-model"

    # Get context for stage without override
    review_ctx = runner._get_stage_context("review")
    assert review_ctx.model_selector.model is None  # Falls back to default
