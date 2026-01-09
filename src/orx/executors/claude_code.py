"""Claude Code CLI executor implementation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from orx.exceptions import ExecutorError
from orx.executors.base import BaseExecutor, ExecResult, LogPaths, ResolvedInvocation
from orx.infra.command import CommandRunner

if TYPE_CHECKING:
    from orx.config import ModelSelector

logger = structlog.get_logger()


class ClaudeCodeExecutor(BaseExecutor):
    """Executor adapter for Claude Code CLI.

    Wraps the Claude Code CLI (`claude`) in non-interactive print mode.
    Supports model selection via --model flag with aliases (sonnet, opus, haiku)
    or full model names.

    Key features:
    - Uses `claude -p` for non-interactive execution
    - Uses `--output-format json` for structured parsing
    - Apply mode: `--dangerously-skip-permissions` for full tool access
    - Text mode: `--tools "Read,Grep,Glob,LS"` for read-only access
    - Supports `--fallback-model` for resilience
    - Supports `--max-turns` for cost control

    Available models (aliases):
    - sonnet: Claude Sonnet 4.5 (default, balanced)
    - opus: Claude Opus 4 (most capable)
    - haiku: Claude Haiku 4.5 (fast, cost-effective)

    External providers (via MCP):
    - GLM and other providers can be configured in ~/.claude/mcp-config.json
    - Pass model name directly to use external providers

    Model selection priority:
    1. stage.model (explicit model override)
    2. executor.default.model (default model)
    3. engine.model (legacy global config)
    4. CLI default (sonnet)

    Example:
        >>> executor = ClaudeCodeExecutor(cmd=CommandRunner())
        >>> result = executor.run_apply(
        ...     cwd=Path("/workspace"),
        ...     prompt_path=Path("/prompts/implement.md"),
        ...     logs=LogPaths(stdout=Path("out.log"), stderr=Path("err.log")),
        ...     model_selector=ModelSelector(model="sonnet"),
        ... )
    """

    # Read-only tools for text mode (planning, spec, review)
    TEXT_MODE_TOOLS = (
        "Read,Grep,Glob,LS,Bash(cat:*),Bash(head:*),Bash(tail:*),Bash(wc:*)"
    )

    def __init__(
        self,
        *,
        cmd: CommandRunner,
        binary: str = "claude",
        extra_args: list[str] | None = None,
        dry_run: bool = False,
        default_model: str | None = None,
        output_format: str = "json",
        max_turns: int | None = None,
        fallback_model: str | None = None,
        verbose: bool = False,
    ) -> None:
        """Initialize the Claude Code executor.

        Args:
            cmd: CommandRunner instance.
            binary: Path to the claude binary.
            extra_args: Additional arguments to pass to claude.
            dry_run: If True, commands are logged but not executed.
            default_model: Default model to use (e.g., "sonnet", "opus").
            output_format: Output format (text, json, stream-json).
            max_turns: Maximum agentic turns (safety limit).
            fallback_model: Fallback model on overload.
            verbose: Enable verbose logging.
        """
        super().__init__(
            binary=binary,
            extra_args=extra_args,
            dry_run=dry_run,
            default_model=default_model,
        )
        self.cmd = cmd
        self.output_format = output_format
        self.max_turns = max_turns
        self.fallback_model = fallback_model
        self.verbose = verbose

    @property
    def name(self) -> str:
        """Name of the executor."""
        return "claude_code"

    def _build_command(
        self,
        *,
        prompt_path: Path,
        cwd: Path,
        model_selector: ModelSelector | None = None,
        out_path: Path | None = None,
        text_only: bool = False,
    ) -> tuple[list[str], dict[str, Any]]:
        """Build the claude command line.

        Args:
            prompt_path: Path to the prompt file.
            cwd: Working directory.
            model_selector: Optional model selection configuration.
            out_path: Optional output path (unused, for interface compat).
            text_only: If True, restrict to read-only tools.

        Returns:
            Tuple of (command list, resolved model info dict).
        """
        resolved = self._resolve_model(model_selector)
        # Keep out_path referenced to satisfy linters (interface compatibility)
        _ = out_path

        cmd = [self.binary]

        # Non-interactive print mode (required for automation)
        cmd.append("-p")

        # Output format for structured parsing
        cmd.extend(["--output-format", self.output_format])

        # Model selection
        if resolved["model"]:
            cmd.extend(["--model", resolved["model"]])

        # Prompt from file (read content and pass as argument)
        # Claude Code expects prompt as positional argument BEFORE other options
        # NOTE: Must come before --add-dir to avoid parsing issues
        prompt_content = prompt_path.read_text() if prompt_path.exists() else ""
        cmd.append(prompt_content)

        # Tool permissions based on mode
        if text_only:
            # Read-only mode: restrict to safe tools
            cmd.extend(["--tools", self.TEXT_MODE_TOOLS])
        else:
            # Apply mode: full permissions (use with caution!)
            cmd.append("--dangerously-skip-permissions")

        # Add working directory for tool access
        cmd.extend(["--add-dir", str(cwd)])

        # Safety limit on agentic turns
        if self.max_turns:
            cmd.extend(["--max-turns", str(self.max_turns)])

        # Fallback model for resilience
        if self.fallback_model:
            cmd.extend(["--fallback-model", self.fallback_model])

        # Verbose logging for debugging
        if self.verbose:
            cmd.append("--verbose")

        # Additional args from config
        cmd.extend(self.extra_args)

        return cmd, resolved

    def resolve_invocation(
        self,
        *,
        prompt_path: Path,
        cwd: Path,
        logs: LogPaths,
        out_path: Path | None = None,
        model_selector: ModelSelector | None = None,
        text_only: bool = False,
    ) -> ResolvedInvocation:
        """Resolve the command invocation without executing.

        Args:
            prompt_path: Path to the prompt file.
            cwd: Working directory.
            logs: Paths for stdout/stderr logs.
            out_path: Optional output path (for text mode).
            model_selector: Optional model selection configuration.
            text_only: If True, run in read-only mode.

        Returns:
            ResolvedInvocation with command and artifacts.
        """
        cmd, resolved = self._build_command(
            prompt_path=prompt_path,
            cwd=cwd,
            model_selector=model_selector,
            out_path=out_path,
            text_only=text_only,
        )

        artifacts = {
            "stdout": logs.stdout,
            "stderr": logs.stderr,
        }
        if out_path:
            artifacts["output"] = out_path

        return ResolvedInvocation(
            cmd=cmd,
            artifacts=artifacts,
            model_info={
                "executor": self.name,
                "model": resolved["model"],
                "output_format": self.output_format,
                "text_only": text_only,
                "max_turns": self.max_turns,
            },
        )

    def _parse_output(self, stdout_path: Path) -> tuple[str, dict[str, Any]]:
        """Parse output from Claude Code CLI.

        Claude Code with --output-format json returns structured data:
        {
            "type": "result",
            "subtype": "success" | "error_*",
            "result": "response text",
            "cost_usd": 0.0123,
            "duration_ms": 1234,
            "num_turns": 3,
            "session_id": "uuid",
            "is_error": false
        }

        Args:
            stdout_path: Path to stdout file.

        Returns:
            Tuple of (text content, extra metadata dict).
        """
        if not stdout_path.exists():
            return "", {}

        content = stdout_path.read_text().strip()
        if not content:
            return "", {}

        extra: dict[str, Any] = {}

        # Try to parse as JSON (expected with --output-format json)
        if self.output_format == "json":
            try:
                data = json.loads(content)
                text = data.get("result", "")
                extra = {
                    "cost_usd": data.get("cost_usd"),
                    "total_cost_usd": data.get("total_cost_usd"),
                    "duration_ms": data.get("duration_ms"),
                    "duration_api_ms": data.get("duration_api_ms"),
                    "num_turns": data.get("num_turns"),
                    "session_id": data.get("session_id"),
                    "is_error": data.get("is_error", False),
                    "subtype": data.get("subtype"),
                    "type": data.get("type"),
                }
                return text, extra
            except json.JSONDecodeError:
                logger.warning(
                    "Failed to parse Claude Code JSON output, using raw text",
                    content_preview=content[:200],
                )

        # Fallback: return raw content
        return content, {}

    def _check_result_errors(self, _result: ExecResult, extra: dict[str, Any]) -> None:
        """Check for Claude Code specific errors in the result.

        Args:
            result: Execution result.
            extra: Parsed extra metadata.

        Raises:
            ExecutorError: If a fatal error is detected.
        """
        if not extra.get("is_error"):
            return

        subtype = extra.get("subtype", "unknown")
        error_msg = f"Claude Code error: {subtype}"

        # Classify error types
        if subtype in ("error_rate_limit", "error_overloaded"):
            # Transient errors - can be retried
            logger.warning("Claude Code transient error", subtype=subtype)
            # Don't raise - let caller handle retry
        elif subtype == "error_max_turns":
            raise ExecutorError(f"{error_msg} - max turns exceeded")
        elif subtype == "error_api":
            raise ExecutorError(f"{error_msg} - API error")
        else:
            logger.error("Claude Code error", subtype=subtype, extra=extra)

    def run_text(
        self,
        *,
        cwd: Path,
        prompt_path: Path,
        logs: LogPaths,
        out_path: Path,
        timeout: int | None = None,
        model_selector: ModelSelector | None = None,
    ) -> ExecResult:
        """Run Claude Code in text-only mode (read-only tools).

        Used for PLAN, SPEC, DECOMPOSE, REVIEW stages where no file
        modifications should occur.

        Args:
            cwd: Working directory.
            prompt_path: Path to the prompt file.
            logs: Paths for stdout/stderr logs.
            out_path: Path to write the text output.
            model_selector: Optional model selection configuration.

        Returns:
            ExecResult with execution status.
        """
        # Resolve invocation (includes command, artifacts, model_info)
        invocation = self.resolve_invocation(
            prompt_path=prompt_path,
            cwd=cwd,
            logs=logs,
            out_path=out_path,
            model_selector=model_selector,
            text_only=True,
        )
        cmd = invocation.cmd
        resolved = invocation.model_info

        logger.info(
            "Running Claude Code (text mode)",
            model=resolved.get("model"),
            cwd=str(cwd),
            tools=self.TEXT_MODE_TOOLS,
        )

        # Use provided timeout if set, otherwise default to 10 minutes
        text_timeout = timeout or 600

        # Execute command (CommandRunner handles dry_run internally)
        cmd_result = self.cmd.run(
            cmd,
            cwd=cwd,
            stdout_path=logs.stdout,
            stderr_path=logs.stderr,
            timeout=text_timeout,
        )

        # Parse JSON output and extract text
        text, extra = self._parse_output(logs.stdout)
        # Convert cmd_result to ExecResult-like check by passing to checker
        self._check_result_errors(
            self._create_result(
                returncode=cmd_result.returncode,
                logs=logs,
                extra=extra,
                success=(cmd_result.returncode == 0),
                invocation=invocation,
            ),
            extra,
        )

        # Write extracted text to output file
        out_path.write_text(text)

        # Build ExecResult from CommandResult
        exec_result = self._create_result(
            returncode=cmd_result.returncode,
            logs=logs,
            extra=extra,
            success=(cmd_result.returncode == 0),
            invocation=invocation,
        )

        logger.info(
            "Claude Code text mode completed",
            success=exec_result.success,
            returncode=exec_result.returncode,
            cost_usd=extra.get("cost_usd"),
            num_turns=extra.get("num_turns"),
        )

        return exec_result

    def run_apply(
        self,
        *,
        cwd: Path,
        prompt_path: Path,
        logs: LogPaths,
        timeout: int | None = None,
        model_selector: ModelSelector | None = None,
    ) -> ExecResult:
        """Run Claude Code in apply mode (full tool access).

        Used for IMPLEMENT and FIX stages where file modifications
        are expected. Uses --dangerously-skip-permissions.

        WARNING: This mode has full filesystem access. Only use in
        sandboxed/trusted environments.

        Args:
            cwd: Working directory.
            prompt_path: Path to the prompt file.
            logs: Paths for stdout/stderr logs.
            model_selector: Optional model selection configuration.

        Returns:
            ExecResult with execution status.
        """
        # Resolve invocation (includes command, artifacts, model_info)
        invocation = self.resolve_invocation(
            prompt_path=prompt_path,
            cwd=cwd,
            logs=logs,
            model_selector=model_selector,
            text_only=False,
        )
        cmd = invocation.cmd
        resolved = invocation.model_info

        logger.info(
            "Running Claude Code (apply mode)",
            model=resolved.get("model"),
            cwd=str(cwd),
            permissions="dangerously-skip-permissions",
        )

        # Use provided timeout if set, otherwise default to 30 minutes
        apply_timeout = timeout or 1800

        # Execute command (CommandRunner handles dry_run internally)
        cmd_result = self.cmd.run(
            cmd,
            cwd=cwd,
            stdout_path=logs.stdout,
            stderr_path=logs.stderr,
            timeout=apply_timeout,
        )

        # Parse output for metadata
        text, extra = self._parse_output(logs.stdout)
        # Check for Claude-specific errors
        self._check_result_errors(
            self._create_result(
                returncode=cmd_result.returncode,
                logs=logs,
                extra=extra,
                success=(cmd_result.returncode == 0),
                invocation=invocation,
            ),
            extra,
        )

        # Build ExecResult from CommandResult
        exec_result = self._create_result(
            returncode=cmd_result.returncode,
            logs=logs,
            extra=extra,
            success=(cmd_result.returncode == 0),
            invocation=invocation,
        )

        logger.info(
            "Claude Code apply mode completed",
            success=exec_result.success,
            returncode=exec_result.returncode,
            cost_usd=extra.get("cost_usd"),
            num_turns=extra.get("num_turns"),
        )

        return exec_result
