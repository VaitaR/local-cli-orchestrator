"""Unit tests for GenericGate."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orx.gates.generic import GenericGate
from orx.infra.command import CommandResult, CommandRunner


@pytest.fixture
def mock_cmd_runner() -> MagicMock:
    """Create a mock command runner."""
    mock = MagicMock(spec=CommandRunner)
    return mock


def test_generic_gate_success(mock_cmd_runner: MagicMock, tmp_path: Path) -> None:
    """Test GenericGate with successful command."""
    log_path = tmp_path / "helm-lint.log"

    # Mock successful command
    mock_cmd_runner.run.return_value = CommandResult(
        returncode=0,
        stdout_path=log_path,
        stderr_path=log_path.with_suffix(".stderr.log"),
        command=["make", "helm-lint"],
        cwd=tmp_path,
    )

    gate = GenericGate(
        name="helm-lint",
        cmd=mock_cmd_runner,
        command="make",
        args=["helm-lint"],
    )

    result = gate.run(cwd=tmp_path, log_path=log_path)

    assert result.ok is True
    assert gate.name == "helm-lint"
    assert "helm-lint check passed" in result.message
    mock_cmd_runner.run.assert_called_once()


def test_generic_gate_failure(mock_cmd_runner: MagicMock, tmp_path: Path) -> None:
    """Test GenericGate with failing command."""
    log_path = tmp_path / "e2e-test.log"

    # Mock failing command
    mock_cmd_runner.run.return_value = CommandResult(
        returncode=1,
        stdout_path=log_path,
        stderr_path=log_path.with_suffix(".stderr.log"),
        command=["npm", "run", "e2e"],
        cwd=tmp_path,
    )

    gate = GenericGate(
        name="e2e-test",
        cmd=mock_cmd_runner,
        command="npm",
        args=["run", "e2e"],
    )

    result = gate.run(cwd=tmp_path, log_path=log_path)

    assert result.ok is False
    assert gate.name == "e2e-test"
    assert "e2e-test check failed" in result.message
    assert result.returncode == 1


def test_generic_gate_custom_name(mock_cmd_runner: MagicMock, tmp_path: Path) -> None:
    """Test GenericGate uses custom name correctly."""
    log_path = tmp_path / "my-custom-check.log"

    mock_cmd_runner.run.return_value = CommandResult(
        returncode=0,
        stdout_path=log_path,
        stderr_path=log_path.with_suffix(".stderr.log"),
        command=["./my-script.sh"],
        cwd=tmp_path,
    )

    gate = GenericGate(
        name="my-custom-check",
        cmd=mock_cmd_runner,
        command="./my-script.sh",
    )

    assert gate.name == "my-custom-check"

    gate.run(cwd=tmp_path, log_path=log_path)
    assert gate.name == "my-custom-check"


def test_generic_gate_required_false(mock_cmd_runner: MagicMock, tmp_path: Path) -> None:
    """Test GenericGate with required=False."""
    log_path = tmp_path / "optional-check.log"

    mock_cmd_runner.run.return_value = CommandResult(
        returncode=1,
        stdout_path=log_path,
        stderr_path=log_path.with_suffix(".stderr.log"),
        command=["optional-check"],
        cwd=tmp_path,
    )

    gate = GenericGate(
        name="optional-check",
        cmd=mock_cmd_runner,
        command="optional-check",
        required=False,
    )

    result = gate.run(cwd=tmp_path, log_path=log_path)

    assert result.ok is False
    assert gate.required is False
