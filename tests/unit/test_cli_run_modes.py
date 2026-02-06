"""Unit tests for CLI run mode selection."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pytest import MonkeyPatch
from typer.testing import CliRunner

from orx.cli import app
from orx.pipeline.constants import DEFAULT_PIPELINE_ID


class _FakeRunner:
    """Minimal runner stub for CLI tests."""

    def __init__(self, run_success: bool = True) -> None:
        self._run_success = run_success
        self.calls: list[tuple[str | Path, str | None]] = []
        self.paths = SimpleNamespace(run_id="test-run-id", run_dir=Path("/tmp/test-run"))
        self.config = SimpleNamespace(
            engine=SimpleNamespace(type=SimpleNamespace(value="fake")),
            git=SimpleNamespace(base_branch="main"),
        )

    def run(
        self,
        task: str | Path,
        pipeline_id: str | None = None,
        *,
        use_default_pipeline: bool = True,  # noqa: ARG002
    ) -> bool:
        self.calls.append((task, pipeline_id))
        return self._run_success


def _install_runner_stub(monkeypatch: MonkeyPatch, fake_runner: _FakeRunner) -> None:
    """Patch CLI factory to return the provided fake runner."""
    def _factory(*_args: object, **_kwargs: object) -> _FakeRunner:
        return fake_runner

    monkeypatch.setattr("orx.cli.create_runner", _factory)


def test_run_uses_standard_pipeline_by_default(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """CLI run should use standard pipeline when no mode is provided."""
    fake_runner = _FakeRunner()
    _install_runner_stub(monkeypatch, fake_runner)
    cli = CliRunner()

    result = cli.invoke(app, ["run", "implement feature", "--dir", str(tmp_path)])

    assert result.exit_code == 0
    assert fake_runner.calls == [("implement feature", DEFAULT_PIPELINE_ID)]


def test_run_legacy_fsm_disables_pipeline(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """CLI run should pass no pipeline when legacy FSM mode is requested."""
    fake_runner = _FakeRunner()
    _install_runner_stub(monkeypatch, fake_runner)
    cli = CliRunner()

    result = cli.invoke(
        app,
        ["run", "implement feature", "--legacy-fsm", "--dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert fake_runner.calls == [("implement feature", None)]


def test_run_rejects_legacy_with_custom_pipeline(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """CLI should reject combining --legacy-fsm with a custom pipeline."""
    fake_runner = _FakeRunner()
    _install_runner_stub(monkeypatch, fake_runner)
    cli = CliRunner()

    result = cli.invoke(
        app,
        [
            "run",
            "implement feature",
            "--legacy-fsm",
            "--pipeline",
            "fast_fix",
            "--dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    combined_output = f"{result.stdout}\n{result.stderr}"
    assert "--legacy-fsm cannot be used with a custom --pipeline value" in combined_output
    assert fake_runner.calls == []
