"""Integration tests for stage-specific engine selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from orx.config import ModelSelector, OrxConfig
from orx.executors.base import ExecResult, LogPaths
from orx.runner import Runner
from orx.state import Stage


class RecordingExecutor:
    """Executor that records stage usage and emits fixed text output."""

    def __init__(self, name: str, text_output: str) -> None:
        self._name = name
        self.text_output = text_output
        self.calls: list[tuple[str, str, str | None]] = []

    @property
    def name(self) -> str:
        return self._name

    def run_text(
        self,
        *,
        cwd: Path,  # noqa: ARG002
        prompt_path: Path,
        out_path: Path,
        logs: LogPaths,
        timeout: int | None = None,  # noqa: ARG002
        model_selector: ModelSelector | None = None,
    ) -> ExecResult:
        stage = prompt_path.stem
        model = model_selector.model if model_selector else None
        self.calls.append(("text", stage, model))

        logs.stdout.parent.mkdir(parents=True, exist_ok=True)
        logs.stdout.write_text(f"[test] {self._name} text {stage}\n")
        logs.stderr.write_text("")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(self.text_output)

        return ExecResult(
            returncode=0,
            stdout_path=logs.stdout,
            stderr_path=logs.stderr,
            success=True,
        )

    def run_apply(
        self,
        *,
        cwd: Path,  # noqa: ARG002
        prompt_path: Path,
        logs: LogPaths,
        timeout: int | None = None,  # noqa: ARG002
        model_selector: ModelSelector | None = None,
    ) -> ExecResult:
        stage = prompt_path.stem
        model = model_selector.model if model_selector else None
        self.calls.append(("apply", stage, model))

        logs.stdout.parent.mkdir(parents=True, exist_ok=True)
        logs.stdout.write_text(f"[test] {self._name} apply {stage}\n")
        logs.stderr.write_text("")

        return ExecResult(
            returncode=0,
            stdout_path=logs.stdout,
            stderr_path=logs.stderr,
            success=True,
        )


@pytest.mark.integration
def test_resume_uses_stage_model_selector(
    tmp_git_repo: Path,
) -> None:
    """Resume uses stage-specific model selector for the resumed stage."""
    yaml_content = """
version: "1.0"
engine:
  type: fake
stages:
  review:
    model: "review-model"
git:
  base_branch: main
  auto_commit: false
knowledge:
  enabled: false
"""
    config = OrxConfig.from_yaml(yaml_content)

    runner1 = Runner(config, base_dir=tmp_git_repo, dry_run=False)
    runner1.state.initialize()
    runner1.pack.write_task("Resume review stage")
    runner1.pack.write_spec("# Spec\n\nDetails")
    runner1.pack.write_patch_diff("diff --git a/foo b/foo\n")

    runner1.state.transition_to(Stage.REVIEW)
    run_id = runner1.paths.run_id

    runner2 = Runner(config, base_dir=tmp_git_repo, run_id=run_id, dry_run=False)

    # Get context to verify model selector
    ctx = runner2._get_stage_context("review")
    assert ctx.model_selector.model == "review-model"

    success = runner2.resume()
    assert success
    assert runner2.paths.review_md.exists()
