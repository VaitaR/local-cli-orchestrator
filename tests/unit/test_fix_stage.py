"""Unit tests for FixStage behavior."""

from __future__ import annotations

from pathlib import Path

from orx.context.backlog import WorkItem
from orx.context.pack import ContextPack
from orx.executors.base import ExecResult, LogPaths
from orx.paths import RunPaths
from orx.prompts.renderer import PromptRenderer
from orx.stages.base import StageContext
from orx.stages.implement import FixStage
from orx.state import StateManager


class StubWorkspace:
    def __init__(self, worktree_path: Path) -> None:
        self.worktree_path = worktree_path


class CapturingExecutor:
    def __init__(self) -> None:
        self.last_kwargs: dict | None = None

    @property
    def name(self) -> str:
        return "stub"

    def run_text(self, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def run_apply(  # type: ignore[no-untyped-def]
        self,
        *,
        cwd: Path,
        prompt_path: Path,
        logs: LogPaths,
        timeout: int | None = None,
        model_selector=None,
    ) -> ExecResult:
        self.last_kwargs = {
            "cwd": cwd,
            "prompt_path": prompt_path,
            "logs": logs,
            "timeout": timeout,
            "model_selector": model_selector,
        }
        logs.stdout.parent.mkdir(parents=True, exist_ok=True)
        logs.stderr.parent.mkdir(parents=True, exist_ok=True)
        logs.stdout.write_text("")
        logs.stderr.write_text("")
        return ExecResult(
            returncode=0, stdout_path=logs.stdout, stderr_path=logs.stderr
        )

    def resolve_invocation(self, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError


def test_fix_stage_passes_timeout_and_model_selector(tmp_path: Path) -> None:
    paths = RunPaths.create_new(tmp_path, "run_fix")
    pack = ContextPack(paths)
    pack.write_task("Task")
    pack.write_spec("Spec")
    pack.write_tooling_snapshot("")
    pack.write_verify_commands("")
    state = StateManager(paths)
    state.initialize()

    executor = CapturingExecutor()
    ctx = StageContext(
        paths=paths,
        pack=pack,
        state=state,
        workspace=StubWorkspace(tmp_path),
        executor=executor,
        gates=[],
        renderer=PromptRenderer(),
        config={},
        timeout_seconds=123,
        model_selector=None,  # will be passed through as-is
        events=None,
    )

    item = WorkItem(
        id="W001",
        title="Fix",
        objective="Fix it",
        acceptance=["ok"],
        files_hint=["src/x.py"],
    )

    stage = FixStage()
    result = stage.execute_fix(ctx, item, 2, {"diff_empty": True})
    assert result.success is True
    assert executor.last_kwargs is not None
    assert executor.last_kwargs["timeout"] == 123
    assert executor.last_kwargs["model_selector"] is None
