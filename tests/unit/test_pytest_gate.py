"""Unit tests for PytestGate."""

from __future__ import annotations

import os
from pathlib import Path

from orx.gates.pytest import PytestGate
from orx.infra.command import CommandResult


class StubCommandRunner:
    def __init__(self) -> None:
        self.last_env: dict[str, str] | None = None

    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        stdout_path: Path | None = None,
        stderr_path: Path | None = None,
        timeout: int | None = None,  # noqa: ARG002
        check: bool = False,  # noqa: ARG002
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        self.last_env = env
        return CommandResult(
            returncode=0,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=command,
            cwd=cwd,
        )


def test_pytest_gate_sets_pythonpath(tmp_path: Path) -> None:
    workdir = tmp_path / "repo"
    tests_dir = workdir / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_sample.py").write_text("def test_ok():\n    assert True\n")

    runner = StubCommandRunner()
    gate = PytestGate(cmd=runner)
    log_path = tmp_path / "logs" / "pytest.log"

    prev_pythonpath = os.environ.get("PYTHONPATH")
    try:
        os.environ["PYTHONPATH"] = "existing"
        gate.run(cwd=workdir, log_path=log_path)
    finally:
        if prev_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = prev_pythonpath

    assert runner.last_env is not None
    assert "PYTHONPATH" in runner.last_env
    expected_prefix = f"{workdir}{os.pathsep}existing"
    assert runner.last_env["PYTHONPATH"] == expected_prefix
