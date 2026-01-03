"""Base gate protocol and result types."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class GateResult:
    """Result of a gate execution.

    Attributes:
        ok: Whether the gate passed.
        returncode: Exit code from the gate command.
        log_path: Path to the gate log file.
        message: Optional message describing the result.
    """

    ok: bool
    returncode: int
    log_path: Path
    message: str = ""

    @property
    def failed(self) -> bool:
        """Check if the gate failed."""
        return not self.ok

    def read_log(self) -> str:
        """Read the gate log content."""
        if self.log_path.exists():
            return self.log_path.read_text()
        return ""

    def get_log_tail(self, lines: int = 50) -> str:
        """Get the tail of the log file.

        Args:
            lines: Number of lines to return.

        Returns:
            Last N lines of the log.
        """
        content = self.read_log()
        if not content:
            return ""
        log_lines = content.splitlines()
        return "\n".join(log_lines[-lines:])


@runtime_checkable
class Gate(Protocol):
    """Protocol for quality gates.

    Gates run checks on the workspace and report pass/fail.
    """

    @property
    def name(self) -> str:
        """Name of the gate (e.g., 'ruff', 'pytest')."""
        ...

    def run(self, *, cwd: Path, log_path: Path) -> GateResult:
        """Run the gate check.

        Args:
            cwd: Working directory to run the check in.
            log_path: Path to write the log to.

        Returns:
            GateResult with pass/fail status.
        """
        ...


class BaseGate:
    """Base class for gate implementations."""

    def __init__(
        self,
        *,
        command: str,
        args: list[str] | None = None,
        required: bool = True,
    ) -> None:
        """Initialize the gate.

        Args:
            command: Command to run.
            args: Arguments for the command.
            required: Whether this gate is required to pass.
        """
        self.command = command
        self.args = args or []
        self.required = required

    @property
    def name(self) -> str:
        """Name of the gate."""
        raise NotImplementedError

    def _create_result(
        self,
        *,
        ok: bool,
        returncode: int,
        log_path: Path,
        message: str = "",
    ) -> GateResult:
        """Create a GateResult with consistent structure."""
        return GateResult(
            ok=ok,
            returncode=returncode,
            log_path=log_path,
            message=message,
        )
