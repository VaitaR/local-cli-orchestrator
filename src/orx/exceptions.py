"""Custom exceptions for orx orchestrator."""

from pathlib import Path


class OrxError(Exception):
    """Base exception for all orx errors."""

    pass


class ExecutorError(OrxError):
    """Raised when an executor fails to run a command."""

    def __init__(
        self,
        message: str,
        *,
        executor_name: str = "",
        returncode: int | None = None,
        stdout_path: Path | None = None,
        stderr_path: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.executor_name = executor_name
        self.returncode = returncode
        self.stdout_path = stdout_path
        self.stderr_path = stderr_path


class GateFailed(OrxError):
    """Raised when a quality gate fails."""

    def __init__(
        self,
        message: str,
        *,
        gate_name: str = "",
        returncode: int | None = None,
        log_path: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.gate_name = gate_name
        self.returncode = returncode
        self.log_path = log_path


class WorkspaceError(OrxError):
    """Raised when workspace operations fail."""

    def __init__(
        self,
        message: str,
        *,
        operation: str = "",
        path: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.path = path


class StateError(OrxError):
    """Raised when state management fails."""

    def __init__(
        self,
        message: str,
        *,
        current_stage: str = "",
        run_id: str = "",
    ) -> None:
        super().__init__(message)
        self.current_stage = current_stage
        self.run_id = run_id


class GuardrailError(OrxError):
    """Raised when a guardrail violation is detected."""

    def __init__(
        self,
        message: str,
        *,
        violated_files: list[str] | None = None,
        rule: str = "",
    ) -> None:
        super().__init__(message)
        self.violated_files = violated_files or []
        self.rule = rule


class ConfigError(OrxError):
    """Raised when configuration is invalid."""

    def __init__(
        self,
        message: str,
        *,
        config_path: Path | None = None,
        field: str = "",
    ) -> None:
        super().__init__(message)
        self.config_path = config_path
        self.field = field


class CommandError(OrxError):
    """Raised when a subprocess command fails."""

    def __init__(
        self,
        message: str,
        *,
        command: list[str] | None = None,
        returncode: int | None = None,
        cwd: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.command = command or []
        self.returncode = returncode
        self.cwd = cwd
