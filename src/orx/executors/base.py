"""Base executor protocol and result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from orx.config import ModelSelector


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
class ResolvedInvocation:
    """Resolved command invocation details.

    Attributes:
        cmd: Full command as list of strings.
        env: Environment variables to set.
        artifacts: Paths to artifacts that will be created.
        model_info: Information about model selection for logging.
    """

    cmd: list[str]
    env: dict[str, str] = field(default_factory=dict)
    artifacts: dict[str, Path] = field(default_factory=dict)
    model_info: dict[str, Any] = field(default_factory=dict)


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
        invocation: The resolved invocation used (for logging/meta).
    """

    returncode: int
    stdout_path: Path
    stderr_path: Path
    extra: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error_message: str = ""
    invocation: ResolvedInvocation | None = None

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

    def is_quota_error(self) -> bool:
        """Check if this is a quota/limit error.

        Returns:
            True if error appears to be quota/capacity related.
        """
        if not self.failed:
            return False

        error_markers = [
            "quota",
            "limit",
            "capacity",
            "rate limit",
            "too many requests",
            "resource exhausted",
        ]
        stderr = self.read_stderr().lower()
        error_msg = self.error_message.lower()

        return any(marker in stderr or marker in error_msg for marker in error_markers)

    def is_model_unavailable_error(self) -> bool:
        """Check if this is a model unavailable error.

        Returns:
            True if error indicates model is not available.
        """
        if not self.failed:
            return False

        error_markers = [
            "model not found",
            "not available",
            "model does not exist",
            "invalid model",
            "unknown model",
        ]
        stderr = self.read_stderr().lower()
        error_msg = self.error_message.lower()

        return any(marker in stderr or marker in error_msg for marker in error_markers)

    def get_token_usage(self) -> dict[str, int] | None:
        """Extract token usage from execution result.

        Parses stdout/extra for token usage information.
        Supports both Codex and Gemini output formats.

        Returns:
            Dict with input, output, total tokens or None if not found.
        """
        # First check extra dict (Gemini JSON output)
        if self.extra:
            # Gemini format: usage.input_tokens, usage.output_tokens
            usage = self.extra.get("usage", {})
            if usage:
                input_tokens = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
                output_tokens = usage.get("output_tokens", 0) or usage.get("completion_tokens", 0)
                if input_tokens or output_tokens:
                    return {
                        "input": input_tokens,
                        "output": output_tokens,
                        "total": input_tokens + output_tokens,
                    }

            # Alternative format in extra
            if "tokens" in self.extra:
                tokens = self.extra["tokens"]
                if isinstance(tokens, dict):
                    return {
                        "input": tokens.get("input", 0),
                        "output": tokens.get("output", 0),
                        "total": tokens.get("total", 0),
                    }

        # Try parsing stdout for token info (Codex JSON format)
        import json
        import re

        try:
            stdout = self.read_stdout()
            if not stdout:
                return None

            # Look for JSON with usage info
            for line in stdout.splitlines():
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    data = json.loads(line)
                    usage = data.get("usage", {})
                    if usage:
                        input_tokens = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
                        output_tokens = usage.get("output_tokens", 0) or usage.get("completion_tokens", 0)
                        if input_tokens or output_tokens:
                            return {
                                "input": input_tokens,
                                "output": output_tokens,
                                "total": input_tokens + output_tokens,
                            }
                except json.JSONDecodeError:
                    continue

            # Fallback: regex patterns for token counts in logs
            patterns = [
                r"input[_\s]?tokens?[:\s]+([\d,]+)",
                r"prompt[_\s]?tokens?[:\s]+([\d,]+)",
                r"output[_\s]?tokens?[:\s]+([\d,]+)",
                r"completion[_\s]?tokens?[:\s]+([\d,]+)",
                r"total[_\s]?tokens?[:\s]+([\d,]+)",
            ]

            tokens: dict[str, int] = {"input": 0, "output": 0, "total": 0}
            for pattern in patterns:
                match = re.search(pattern, stdout, re.IGNORECASE)
                if match:
                    value = int(match.group(1).replace(",", ""))
                    if "input" in pattern or "prompt" in pattern:
                        tokens["input"] = value
                    elif "output" in pattern or "completion" in pattern:
                        tokens["output"] = value
                    elif "total" in pattern:
                        tokens["total"] = value

            if tokens["input"] or tokens["output"] or tokens["total"]:
                if tokens["total"] == 0:
                    tokens["total"] = tokens["input"] + tokens["output"]
                return tokens

        except Exception:
            pass

        return None

    def get_model_used(self) -> str | None:
        """Extract the model name actually used from execution result.

        Returns:
            Model name string or None if not found.
        """
        # Check invocation first
        if self.invocation and self.invocation.model_info:
            model = self.invocation.model_info.get("model")
            if model:
                return model

        # Check extra dict
        if self.extra:
            model = self.extra.get("model") or self.extra.get("model_id")
            if model:
                return model

        return None


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
        model_selector: ModelSelector | None = None,
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
            model_selector: Optional model selection configuration.

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
        model_selector: ModelSelector | None = None,
    ) -> ExecResult:
        """Run executor to apply filesystem changes.

        This mode is used for implementation stages where the executor
        modifies files in the working directory.

        Args:
            cwd: Working directory for the executor.
            prompt_path: Path to the prompt file.
            logs: Paths for stdout/stderr logs.
            timeout: Optional timeout in seconds.
            model_selector: Optional model selection configuration.

        Returns:
            ExecResult with execution details.
        """
        ...

    def resolve_invocation(
        self,
        *,
        prompt_path: Path,
        cwd: Path,
        logs: LogPaths,
        out_path: Path | None = None,
        model_selector: ModelSelector | None = None,
    ) -> ResolvedInvocation:
        """Resolve the command invocation without executing.

        This is useful for logging/meta recording before execution.

        Args:
            prompt_path: Path to the prompt file.
            cwd: Working directory.
            logs: Paths for stdout/stderr logs.
            out_path: Optional output path (for text mode).
            model_selector: Optional model selection configuration.

        Returns:
            ResolvedInvocation with command and artifacts.
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
        default_model: str | None = None,
        default_profile: str | None = None,
        default_reasoning_effort: str | None = None,
    ) -> None:
        """Initialize the executor.

        Args:
            binary: Path or name of the CLI binary.
            extra_args: Additional arguments to pass to the CLI.
            dry_run: If True, commands are logged but not executed.
            default_model: Default model to use if not specified.
            default_profile: Default profile to use if not specified.
            default_reasoning_effort: Default reasoning effort level.
        """
        self.binary = binary
        self.extra_args = extra_args or []
        self.dry_run = dry_run
        self.default_model = default_model
        self.default_profile = default_profile
        self.default_reasoning_effort = default_reasoning_effort

    @property
    def name(self) -> str:
        """Name of the executor."""
        raise NotImplementedError

    def _resolve_model(self, model_selector: ModelSelector | None) -> dict[str, Any]:
        """Resolve final model settings from selector and defaults.

        Args:
            model_selector: Optional model selector from stage config.

        Returns:
            Dict with resolved model, profile, reasoning_effort.
        """
        result: dict[str, Any] = {
            "model": None,
            "profile": None,
            "reasoning_effort": None,
        }

        # Apply defaults first
        result["model"] = self.default_model
        result["profile"] = self.default_profile
        result["reasoning_effort"] = self.default_reasoning_effort

        # Override with selector if provided
        if model_selector:
            if model_selector.model:
                result["model"] = model_selector.model
                result["profile"] = None  # Model overrides profile
            elif model_selector.profile:
                result["profile"] = model_selector.profile
                result["model"] = None  # Profile overrides model

            if model_selector.reasoning_effort:
                result["reasoning_effort"] = model_selector.reasoning_effort

        return result

    def _create_result(
        self,
        *,
        returncode: int,
        logs: LogPaths,
        extra: dict[str, Any] | None = None,
        success: bool = True,
        error_message: str = "",
        invocation: ResolvedInvocation | None = None,
    ) -> ExecResult:
        """Create an ExecResult with consistent structure."""
        return ExecResult(
            returncode=returncode,
            stdout_path=logs.stdout,
            stderr_path=logs.stderr,
            extra=extra or {},
            success=success,
            error_message=error_message,
            invocation=invocation,
        )

    def _dry_run_result(self, logs: LogPaths) -> ExecResult:
        """Create a dry-run result."""
        # Touch the log files so they exist
        logs.stdout.parent.mkdir(parents=True, exist_ok=True)
        logs.stdout.write_text("[dry-run] Command not executed\n")
        logs.stderr.write_text("")
        return self._create_result(returncode=0, logs=logs)

    def resolve_invocation(
        self,
        *,
        prompt_path: Path,
        cwd: Path,
        logs: LogPaths,
        out_path: Path | None = None,
        model_selector: ModelSelector | None = None,
    ) -> ResolvedInvocation:
        """Default implementation - subclasses should override."""
        raise NotImplementedError
