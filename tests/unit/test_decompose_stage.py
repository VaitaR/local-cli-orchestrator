"""Tests for decompose stage auto-fix behavior."""

from __future__ import annotations

from pathlib import Path

from orx.context.backlog import Backlog
from orx.context.pack import ContextPack
from orx.executors.base import ExecResult, LogPaths
from orx.paths import RunPaths
from orx.prompts.renderer import PromptRenderer
from orx.stages.base import StageContext
from orx.stages.decompose import DecomposeStage
from orx.state import StateManager


class StubWorkspace:
    """Workspace stub with a worktree path."""

    def __init__(self, worktree_path: Path) -> None:
        self.worktree_path = worktree_path


class StubExecutor:
    """Executor stub that returns predefined outputs."""

    def __init__(self, outputs: list[str]) -> None:
        self._outputs = outputs
        self.calls = 0

    @property
    def name(self) -> str:
        return "stub"

    def run_text(
        self,
        *,
        cwd: Path,
        prompt_path: Path,
        out_path: Path,
        logs: LogPaths,
        timeout: int | None = None,
        model_selector: object | None = None,
    ) -> ExecResult:
        del cwd, prompt_path, timeout, model_selector
        out_path.parent.mkdir(parents=True, exist_ok=True)
        logs.stdout.parent.mkdir(parents=True, exist_ok=True)
        logs.stderr.parent.mkdir(parents=True, exist_ok=True)
        logs.stdout.write_text("")
        logs.stderr.write_text("")
        output = self._outputs[min(self.calls, len(self._outputs) - 1)]
        out_path.write_text(output)
        self.calls += 1
        return ExecResult(returncode=0, stdout_path=logs.stdout, stderr_path=logs.stderr)

    def run_apply(
        self,
        *,
        cwd: Path,
        prompt_path: Path,
        logs: LogPaths,
        timeout: int | None = None,
        model_selector: object | None = None,
    ) -> ExecResult:
        raise NotImplementedError

    def resolve_invocation(
        self,
        *,
        prompt_path: Path,
        cwd: Path,
        logs: LogPaths,
        out_path: Path | None = None,
        model_selector: object | None = None,
    ) -> object:
        raise NotImplementedError


def _build_context(tmp_path: Path, executor: StubExecutor) -> StageContext:
    paths = RunPaths.create_new(tmp_path, "run_decompose")
    pack = ContextPack(paths)
    pack.write_spec("Spec content")
    pack.write_plan("Plan content")
    state = StateManager(paths)
    state.initialize()
    return StageContext(
        paths=paths,
        pack=pack,
        state=state,
        workspace=StubWorkspace(tmp_path),
        executor=executor,
        gates=[],
        renderer=PromptRenderer(),
        config={"run": {"max_backlog_items": 4, "coalesce_backlog_items": False}},
        timeout_seconds=None,
        model_selector=None,
        events=None,
    )


def test_decompose_retries_on_invalid_yaml(tmp_path: Path) -> None:
    invalid = "Not YAML at all"
    valid = (
        'run_id: "run_decompose"\n'
        "items:\n"
        "  - id: \"W001\"\n"
        "    title: \"Task\"\n"
        "    objective: \"Do the thing\"\n"
        "    acceptance:\n"
        "      - \"It works\"\n"
        "    files_hint:\n"
        "      - \"src/app.py\"\n"
        "    depends_on: []\n"
        "    status: \"todo\"\n"
        "    attempts: 0\n"
        "    notes: \"\"\n"
    )
    executor = StubExecutor([invalid, valid])
    ctx = _build_context(tmp_path, executor)

    stage = DecomposeStage()
    result = stage.execute(ctx)

    assert result.success is True
    assert executor.calls == 2
    backlog = Backlog.load(ctx.paths.backlog_yaml)
    assert backlog.run_id == "run_decompose"
    assert len(backlog.items) == 1


def test_decompose_fails_after_fix_invalid(tmp_path: Path) -> None:
    invalid = "Still not YAML"
    executor = StubExecutor([invalid, invalid])
    ctx = _build_context(tmp_path, executor)

    stage = DecomposeStage()
    result = stage.execute(ctx)

    assert result.success is False
    assert executor.calls == 2
