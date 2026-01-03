"""Base executor protocol and result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass
class LogPaths:
    """Paths for executor log files.

    Attributes:
        stdout: Path to stdout log file.
        stderr: Path to stderr log file.
    """

    stdout: Path
    stderr: Path


@dataclass
class ExecResult:
    """Result of an executor run.

    Attributes:
        returncode: Exit code from the executor.
        stdout_path: Path to captured stdout.
        stderr_path: Path to captured stderr.
        extra: Optional extra data (e.g., parsed JSON output).
        success: Whether the execution succeeded.
        error_message: Error message if failed.
    """

    returncode: int
    stdout_path: Path
    stderr_path: Path
    extra: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error_message: str = ""

    @property
    def failed(self) -> bool:
        """Check if execution failed."""
        return not self.success or self.returncode != 0

    def read_stdout(self) -> str:
        """Read the stdout content."""
        if self.stdout_path.exists():
            return self.stdout_path.read_text()
        return ""

    def read_stderr(self) -> str:
        """Read the stderr content."""
        if self.stderr_path.exists():
            return self.stderr_path.read_text()
        return ""


@runtime_checkable
class Executor(Protocol):
    """Protocol for executor adapters.

    Executors wrap CLI agents (Codex, Gemini, etc.) and provide a
    consistent interface for the orchestrator.
    """

    @property
    def name(self) -> str:
        """Name of the executor (e.g., 'codex', 'gemini')."""
        ...

    def run_text(
        self,
        *,
        cwd: Path,
        prompt_path: Path,
        out_path: Path,
        logs: LogPaths,
        timeout: int | None = None,
    ) -> ExecResult:
        """Run executor to produce text output.

        This mode is used for stages that generate artifacts like
        plan.md, spec.md, backlog.yaml, review.md.

        Args:
            cwd: Working directory for the executor.
            prompt_path: Path to the prompt file.
            out_path: Path to write the output to.
            logs: Paths for stdout/stderr logs.
            timeout: Optional timeout in seconds.

        Returns:
            ExecResult with execution details.
        """
        ...

    def run_apply(
        self,
        *,
        cwd: Path,
        prompt_path: Path,
        logs: LogPaths,
        timeout: int | None = None,
    ) -> ExecResult:
        """Run executor to apply filesystem changes.

        This mode is used for implementation stages where the executor
        modifies files in the working directory.

        Args:
            cwd: Working directory for the executor.
            prompt_path: Path to the prompt file.
            logs: Paths for stdout/stderr logs.
            timeout: Optional timeout in seconds.

        Returns:
            ExecResult with execution details.
        """
        ...


class BaseExecutor:
    """Base class for executor implementations.

    Provides common functionality shared by all executors.
    """

    def __init__(
        self,
        *,
        binary: str,
        extra_args: list[str] | None = None,
        dry_run: bool = False,
    ) -> None:
        """Initialize the executor.

        Args:
            binary: Path or name of the CLI binary.
            extra_args: Additional arguments to pass to the CLI.
            dry_run: If True, commands are logged but not executed.
        """
        self.binary = binary
        self.extra_args = extra_args or []
        self.dry_run = dry_run

    @property
    def name(self) -> str:
        """Name of the executor."""
        raise NotImplementedError

    def _create_result(
        self,
        *,
        returncode: int,
        logs: LogPaths,
        extra: dict[str, Any] | None = None,
        success: bool = True,
        error_message: str = "",
    ) -> ExecResult:
        """Create an ExecResult with consistent structure."""
        return ExecResult(
            returncode=returncode,
            stdout_path=logs.stdout,
            stderr_path=logs.stderr,
            extra=extra or {},
            success=success,
            error_message=error_message,
        )

    def _dry_run_result(self, logs: LogPaths) -> ExecResult:
        """Create a dry-run result."""
        # Touch the log files so they exist
        logs.stdout.parent.mkdir(parents=True, exist_ok=True)
        logs.stdout.write_text("[dry-run] Command not executed\n")
        logs.stderr.write_text("")
        return self._create_result(returncode=0, logs=logs)
