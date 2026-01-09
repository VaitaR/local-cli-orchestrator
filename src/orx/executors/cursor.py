"""Cursor CLI executor implementation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from orx.exceptions import ExecutorError
from orx.executors.base import BaseExecutor, ExecResult, LogPaths, ResolvedInvocation
from orx.infra.command import CommandResult, CommandRunner

if TYPE_CHECKING:
    from orx.config import ModelSelector

logger = structlog.get_logger()


class CursorExecutor(BaseExecutor):
    """Executor adapter for Cursor CLI (agent).

    Wraps the Cursor CLI (`agent`) in non-interactive print mode.
    Supports model selection via --model flag.

    Key features:
    - Uses `agent -p` for non-interactive execution
    - Uses `--output-format json` for structured parsing
    - Apply mode: `--force` to allow file modifications
    - Text mode: omits --force (read-only analysis)
    - Supports CURSOR_API_KEY environment variable for auth

    Available models (via Cursor service):
    - sonnet-4.5: Claude Sonnet 4.5 (default, balanced)
    - opus-4.5: Claude Opus 4.5 (most capable)
    - gpt-5.2: GPT-5.2 (OpenAI)
    - gemini-3-pro: Gemini 3 Pro (Google)
    - grok: Grok (xAI)
    - auto: Cursor auto-selects best model

    Model selection priority:
    1. stage.model (explicit model override)
    2. executor.default.model (default model)
    3. engine.model (legacy global config)
    4. CLI default (auto)

    Example:
        >>> executor = CursorExecutor(cmd=CommandRunner())
        >>> result = executor.run_apply(
        ...     cwd=Path("/workspace"),
        ...     prompt_path=Path("/prompts/implement.md"),
        ...     logs=LogPaths(stdout=Path("out.log"), stderr=Path("err.log")),
        ...     model_selector=ModelSelector(model="sonnet-4.5"),
        ... )
    """

    def __init__(
        self,
        *,
        cmd: CommandRunner,
        binary: str = "agent",
        extra_args: list[str] | None = None,
        dry_run: bool = False,
        default_model: str | None = None,
        output_format: str = "json",
        api_key: str | None = None,
    ) -> None:
        """Initialize the Cursor executor.

        Args:
            cmd: CommandRunner instance.
            binary: Path to the agent binary.
            extra_args: Additional arguments to pass to agent.
            dry_run: If True, commands are logged but not executed.
            default_model: Default model to use (e.g., "sonnet-4.5", "auto").
            output_format: Output format (text, json, stream-json).
            api_key: Optional API key (otherwise uses CURSOR_API_KEY env).
        """
        super().__init__(
            binary=binary,
            extra_args=extra_args,
            dry_run=dry_run,
            default_model=default_model,
        )
        self.cmd = cmd
        self.output_format = output_format
        self.api_key = api_key

    @property
    def name(self) -> str:
        """Name of the executor."""
        return "cursor"

    def _build_command(
        self,
        *,
        prompt_path: Path,
        cwd: Path,
        model_selector: ModelSelector | None = None,
        out_path: Path | None = None,
        text_only: bool = False,
    ) -> tuple[list[str], dict[str, Any]]:
        """Build the agent command line.

        Args:
            prompt_path: Path to the prompt file.
            cwd: Working directory.
            model_selector: Optional model selection configuration.
            out_path: Optional output path (unused, for interface compat).
            text_only: If True, run in read-only mode (no --force).

        Returns:
            Tuple of (command list, resolved model info dict).
        """
        resolved = self._resolve_model(model_selector)
        # Mark out_path as used for linting compatibility
        _ = out_path

        cmd = [self.binary, "agent"]

        # Non-interactive print mode (required for automation)
        cmd.append("-p")

        # Output format for structured parsing
        cmd.extend(["--output-format", self.output_format])

        # Model selection
        if resolved["model"]:
            cmd.extend(["--model", resolved["model"]])

        # File modification permissions
        if not text_only:
            # Apply mode: allow file modifications
            cmd.append("--force")
        # Text mode: no --force flag, agent won't modify files

        # API key via flag (if provided, otherwise env var is used)
        if self.api_key:
            cmd.extend(["--api-key", self.api_key])

        # Add working directory for tool access
        cmd.extend(["--add-dir", str(cwd)])

        # Additional args from config
        cmd.extend(self.extra_args)

        # Prompt via --prompt flag with file reference
        # Cursor agent expects prompt with @file syntax or direct text
        prompt_content = prompt_path.read_text() if prompt_path.exists() else ""
        cmd.extend(["--prompt", prompt_content])

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
            },
        )

    def _parse_output(self, stdout_path: Path) -> tuple[str, dict[str, Any]]:
        """Parse output from Cursor CLI.

        Cursor CLI with --output-format json returns structured data:
        {
            "type": "result",
            "subtype": "success",
            "result": "response text",
            "duration_ms": 1234,
            "duration_api_ms": 1234,
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
                    "duration_ms": data.get("duration_ms"),
                    "duration_api_ms": data.get("duration_api_ms"),
                    "session_id": data.get("session_id"),
                    "request_id": data.get("request_id"),
                    "is_error": data.get("is_error", False),
                    "subtype": data.get("subtype"),
                    "type": data.get("type"),
                }
                return text, extra
            except json.JSONDecodeError:
                logger.warning(
                    "Failed to parse Cursor CLI JSON output, using raw text",
                    content_preview=content[:200],
                )

        # Fallback: return raw content
        return content, {}

    def _check_result_errors(self, _result: CommandResult | ExecResult, extra: dict[str, Any]) -> None:
        """Check for Cursor-specific errors in the result.

        Args:
            result: Execution result.
            extra: Parsed extra metadata.

        Raises:
            ExecutorError: If a fatal error is detected.
        """
        if not extra.get("is_error"):
            return

        subtype = extra.get("subtype", "unknown")
        error_msg = f"Cursor CLI error: {subtype}"

        # Log the error
        logger.error("Cursor CLI error", subtype=subtype, extra=extra)

        if "error" in subtype:
            raise ExecutorError(error_msg)

    def _get_env(self) -> dict[str, str] | None:
        """Get environment variables for the subprocess.

        Returns:
            Dict of env vars or None if none needed.
        """
        # API key can be passed via env var if not using --api-key flag
        if self.api_key and "--api-key" not in self.extra_args:
            return {"CURSOR_API_KEY": self.api_key}
        return None

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
        """Run Cursor CLI in text-only mode (read-only).

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
        cmd, resolved = self._build_command(
            prompt_path=prompt_path,
            cwd=cwd,
            model_selector=model_selector,
            out_path=out_path,
            text_only=True,
        )

        logger.info(
            "Running Cursor CLI (text mode)",
            model=resolved["model"],
            cwd=str(cwd),
        )

        if self.dry_run:
            logger.info("Dry run - skipping execution", cmd=cmd[:5])
            out_path.write_text("(dry run output)")
            return ExecResult(
                returncode=0,
                stdout_path=logs.stdout,
                stderr_path=logs.stderr,
                success=True,
            )

        # Use provided timeout if set, otherwise default to 10 minutes
        text_timeout = timeout or 600
        cmd_result = self.cmd.run(
            cmd,
            cwd=cwd,
            stdout_path=logs.stdout,
            stderr_path=logs.stderr,
            timeout=text_timeout,
            env=self._get_env(),
        )

        # Parse JSON output and extract text
        text, extra = self._parse_output(logs.stdout)
        self._check_result_errors(cmd_result, extra)

        # Write extracted text to output file
        out_path.write_text(text)

        # Create ExecResult from CommandResult
        success = cmd_result.returncode == 0
        result = ExecResult(
            returncode=cmd_result.returncode,
            stdout_path=logs.stdout,
            stderr_path=logs.stderr,
            extra=extra,
            success=success,
        )

        logger.info(
            "Cursor CLI text mode completed",
            success=result.success,
            returncode=result.returncode,
            duration_ms=extra.get("duration_ms"),
        )

        return result

    def run_apply(
        self,
        *,
        cwd: Path,
        prompt_path: Path,
        logs: LogPaths,
        timeout: int | None = None,
        model_selector: ModelSelector | None = None,
    ) -> ExecResult:
        """Run Cursor CLI in apply mode (with --force for file modifications).

        Used for IMPLEMENT and FIX stages where file modifications
        are expected.

        Args:
            cwd: Working directory.
            prompt_path: Path to the prompt file.
            logs: Paths for stdout/stderr logs.
            model_selector: Optional model selection configuration.

        Returns:
            ExecResult with execution status.
        """
        cmd, resolved = self._build_command(
            prompt_path=prompt_path,
            cwd=cwd,
            model_selector=model_selector,
            out_path=None,
            text_only=False,
        )

        logger.info(
            "Running Cursor CLI (apply mode)",
            model=resolved["model"],
            cwd=str(cwd),
            force=True,
        )

        if self.dry_run:
            logger.info("Dry run - skipping execution", cmd=cmd[:5])
            return ExecResult(
                returncode=0,
                stdout_path=logs.stdout,
                stderr_path=logs.stderr,
                success=True,
            )

        # Use provided timeout if set, otherwise default to 30 minutes
        apply_timeout = timeout or 1800
        cmd_result = self.cmd.run(
            cmd,
            cwd=cwd,
            stdout_path=logs.stdout,
            stderr_path=logs.stderr,
            timeout=apply_timeout,
            env=self._get_env(),
        )

        # Parse output for metadata
        text, extra = self._parse_output(logs.stdout)
        self._check_result_errors(cmd_result, extra)

        # Create ExecResult from CommandResult
        success = cmd_result.returncode == 0
        result = ExecResult(
            returncode=cmd_result.returncode,
            stdout_path=logs.stdout,
            stderr_path=logs.stderr,
            extra=extra,
            success=success,
        )

        logger.info(
            "Cursor CLI apply mode completed",
            success=result.success,
            returncode=result.returncode,
            duration_ms=extra.get("duration_ms"),
        )

        return result
