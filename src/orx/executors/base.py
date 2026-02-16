"""Base executor protocol and result types."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:
    from orx.config import ModelSelector

logger = structlog.get_logger()


class ToolEfficacy(str, Enum):
    """How helpful tools were during the stage."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class AgentMeta:
    """Structured self-reflection metadata from the agent.

    Parsed from <orx_meta>...</orx_meta> tags in LLM output.

    Attributes:
        confidence: Agent's confidence in its solution (0.0-1.0).
        context_gap: Whether agent felt context was missing.
        missing_info: Specific context gaps if context_gap is True.
        tool_efficacy: How helpful the tools were.
        reasoning_summary: Brief reasoning for the approach taken.
    """

    confidence: float = 0.0
    context_gap: bool = False
    missing_info: list[str] = field(default_factory=list)
    tool_efficacy: str = "high"
    reasoning_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict."""
        data: dict[str, Any] = {
            "confidence": self.confidence,
            "context_gap": self.context_gap,
            "tool_efficacy": self.tool_efficacy,
        }
        if self.missing_info:
            data["missing_info"] = self.missing_info
        if self.reasoning_summary:
            data["reasoning_summary"] = self.reasoning_summary
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentMeta:
        """Create from a parsed dictionary."""
        confidence = data.get("confidence", 0.0)
        if isinstance(confidence, int | float):
            confidence = max(0.0, min(1.0, float(confidence)))
        else:
            confidence = 0.0

        missing_info_raw = data.get("missing_info", [])
        missing_info = (
            [str(x) for x in missing_info_raw]
            if isinstance(missing_info_raw, list)
            else []
        )

        tool_efficacy = str(data.get("tool_efficacy", "high"))
        if tool_efficacy not in {"high", "medium", "low"}:
            tool_efficacy = "high"

        return cls(
            confidence=confidence,
            context_gap=bool(data.get("context_gap", False)),
            missing_info=missing_info,
            tool_efficacy=tool_efficacy,
            reasoning_summary=str(data.get("reasoning_summary", "")),
        )


# Regex for extracting <orx_meta>...</orx_meta> block from LLM output
_ORX_META_RE = re.compile(
    r"<orx_meta>\s*(\{.*?\})\s*</orx_meta>",
    re.DOTALL,
)

# Regex for extracting <thinking>...</thinking> or <scratchpad>...</scratchpad>
_THINKING_RE = re.compile(
    r"<(?:thinking|scratchpad)>(.*?)</(?:thinking|scratchpad)>",
    re.DOTALL,
)


def parse_orx_meta(text: str) -> tuple[str, AgentMeta | None]:
    """Extract and remove <orx_meta> block from LLM output.

    Args:
        text: Raw LLM output.

    Returns:
        Tuple of (cleaned_text, AgentMeta or None).
    """
    match = _ORX_META_RE.search(text)
    if not match:
        return text, None

    try:
        data = json.loads(match.group(1))
        meta = AgentMeta.from_dict(data)
        # Remove the full <orx_meta>...</orx_meta> block from output
        cleaned = text[: match.start()] + text[match.end() :]
        return cleaned.strip(), meta
    except (json.JSONDecodeError, TypeError, KeyError):
        logger.warning("Failed to parse <orx_meta> block", raw=match.group(0)[:200])
        return text, None


def extract_reasoning_trace(text: str) -> tuple[str, str]:
    """Extract <thinking>/<scratchpad> blocks from LLM output.

    Args:
        text: Raw LLM output.

    Returns:
        Tuple of (cleaned_text, reasoning_trace).
        reasoning_trace is empty string if no thinking blocks found.
    """
    traces: list[str] = []
    cleaned = text
    for match in reversed(list(_THINKING_RE.finditer(text))):
        traces.insert(0, match.group(1).strip())
        cleaned = cleaned[: match.start()] + cleaned[match.end() :]
    return cleaned.strip(), "\n\n".join(traces)


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
        agent_metadata: Structured self-reflection from the agent.
        reasoning_trace: Chain-of-thought content extracted from response.
    """

    returncode: int
    stdout_path: Path
    stderr_path: Path
    extra: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error_message: str = ""
    invocation: ResolvedInvocation | None = None
    agent_metadata: AgentMeta | None = None
    reasoning_trace: str = ""

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

    def is_transient_error(self) -> bool:
        """Check if this is a transient error that should be retried with backoff.

        Transient errors include:
        - Rate limits (429, "too many requests")
        - Capacity exhausted (MODEL_CAPACITY_EXHAUSTED)
        - Temporary server errors (5xx)
        - Timeout errors

        Returns:
            True if error is likely transient and retry may succeed.
        """
        if not self.failed:
            return False

        transient_markers = [
            # Rate limiting
            "429",
            "too many requests",
            "rate limit",
            "ratelimitexceeded",
            # Capacity
            "capacity",
            "model_capacity_exhausted",
            "resource_exhausted",
            "no capacity available",
            # Server errors
            "500",
            "502",
            "503",
            "504",
            "internal server error",
            "service unavailable",
            "bad gateway",
            # Timeout
            "timeout",
            "timed out",
            "deadline exceeded",
            # Connection
            "connection reset",
            "connection refused",
            "network error",
        ]
        stderr = self.read_stderr().lower()
        error_msg = self.error_message.lower()
        combined = stderr + " " + error_msg

        return any(marker in combined for marker in transient_markers)

    def get_retry_after_seconds(self) -> int | None:
        """Extract retry-after hint from error response if present.

        Returns:
            Suggested wait time in seconds, or None if not found.
        """
        import re

        stderr = self.read_stderr()
        # Look for patterns like "retry after 60s", "wait 30 seconds", "4h23m31s"
        patterns = [
            r"retry[\s-]*after[:\s]*(\d+)\s*s",
            r"wait[:\s]*(\d+)\s*second",
            r"reset after (\d+)h?(\d+)?m?(\d+)?s?",
            r"quota will reset after (\d+)h",
        ]
        for pattern in patterns:
            match = re.search(pattern, stderr, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) >= 3 and groups[0] and groups[1]:
                    # Hours + minutes format
                    hours = int(groups[0]) if groups[0] else 0
                    minutes = int(groups[1]) if groups[1] else 0
                    seconds = int(groups[2]) if len(groups) > 2 and groups[2] else 0
                    return hours * 3600 + minutes * 60 + seconds
                elif groups[0]:
                    return int(groups[0])
        return None

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
                input_tokens = usage.get("input_tokens", 0) or usage.get(
                    "prompt_tokens", 0
                )
                output_tokens = usage.get("output_tokens", 0) or usage.get(
                    "completion_tokens", 0
                )
                if input_tokens or output_tokens:
                    return {
                        "input": input_tokens,
                        "output": output_tokens,
                        "total": input_tokens + output_tokens,
                    }

            # Cursor format: direct tokens_in/tokens_out in extra
            tokens_in = self.extra.get("tokens_in", 0)
            tokens_out = self.extra.get("tokens_out", 0)
            if tokens_in or tokens_out:
                return {
                    "input": tokens_in,
                    "output": tokens_out,
                    "total": tokens_in + tokens_out,
                }

            # Alternative format in extra
            if "tokens" in self.extra:
                token_stats = self.extra["tokens"]
                if isinstance(token_stats, dict):
                    return {
                        "input": int(token_stats.get("input", 0)),
                        "output": int(token_stats.get("output", 0)),
                        "total": int(token_stats.get("total", 0)),
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
                        input_tokens = usage.get("input_tokens", 0) or usage.get(
                            "prompt_tokens", 0
                        )
                        output_tokens = usage.get("output_tokens", 0) or usage.get(
                            "completion_tokens", 0
                        )
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
                return str(model)

        # Check extra dict
        if self.extra:
            model = self.extra.get("model") or self.extra.get("model_id")
            if model:
                return str(model)

        return None

    def get_tool_calls(self) -> int:
        """Extract the number of tool calls from execution result.

        Returns:
            Number of tool-call *batches* made during execution, 0 if not found.

        Notes:
            If the model returns multiple tool calls in a single response, we count
            that as 1 (one agent request/turn), not N tools.
        """
        # Check extra dict for tool_calls
        if self.extra:
            tool_calls = self.extra.get("tool_calls", 0)
            if isinstance(tool_calls, int) and tool_calls > 0:
                return 1
            if isinstance(tool_calls, list) and len(tool_calls) > 0:
                return 1

            # Check usage dict for tool_calls
            usage = self.extra.get("usage", {})
            if usage:
                tool_calls = usage.get("tool_calls", 0)
                if isinstance(tool_calls, int) and tool_calls > 0:
                    return 1
                if isinstance(tool_calls, list) and len(tool_calls) > 0:
                    return 1

        return 0


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
        agent_metadata: AgentMeta | None = None,
        reasoning_trace: str = "",
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
            agent_metadata=agent_metadata,
            reasoning_trace=reasoning_trace,
        )

    def _strip_meta_from_output(self, out_path: Path) -> tuple[AgentMeta | None, str]:
        """Parse and strip <orx_meta> and <thinking> blocks from output file.

        Reads the output file, extracts agent metadata and reasoning trace,
        then rewrites the file without those blocks.

        Args:
            out_path: Path to the output file.

        Returns:
            Tuple of (AgentMeta or None, reasoning_trace string).
        """
        if not out_path.exists():
            return None, ""

        raw = out_path.read_text(encoding="utf-8")
        cleaned, meta = parse_orx_meta(raw)
        cleaned, trace = extract_reasoning_trace(cleaned)

        # Rewrite output file without meta/thinking blocks
        if meta is not None or trace:
            out_path.write_text(cleaned, encoding="utf-8")

        if meta and meta.context_gap:
            logger.warning(
                "Agent reported context gap",
                missing_info=meta.missing_info,
                confidence=meta.confidence,
            )

        return meta, trace

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
