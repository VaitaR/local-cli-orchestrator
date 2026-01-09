"""Gemini CLI executor implementation."""

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


class GeminiExecutor(BaseExecutor):
    """Executor adapter for Gemini CLI.

    Wraps the gemini CLI with headless and auto-approve modes.
    Supports model selection via --model/-m flag.

    IMPORTANT: Gemini CLI has sandbox restrictions and can only read files
    within its working directory. Prompt files must be placed inside the
    worktree (cwd) for Gemini to access them. The caller is responsible
    for copying prompts to the worktree using RunPaths.copy_prompt_to_worktree().

    Note: The --model flag only controls the main model in the session.
    Sub-agents may use different models, which will appear in usage reports.
    This is a known limitation of the Gemini CLI.

    Model selection priority:
    1. stage.model (explicit model override)
    2. executor.default.model (default model)
    3. CLI default (fallback to gemini settings)

    Example:
        >>> executor = GeminiExecutor(cmd=CommandRunner())
        >>> result = executor.run_apply(
        ...     cwd=Path("/workspace"),
        ...     prompt_path=Path("/workspace/.orx-prompts/implement.md"),  # Must be in cwd!
        ...     logs=LogPaths(stdout=Path("out.log"), stderr=Path("err.log")),
        ...     model_selector=ModelSelector(model="gemini-2.5-pro"),
        ... )
    """

    def __init__(
        self,
        *,
        cmd: CommandRunner,
        binary: str = "gemini",
        extra_args: list[str] | None = None,
        dry_run: bool = False,
        use_yolo: bool = True,
        approval_mode: str = "auto_edit",
        output_format: str = "json",
        default_model: str | None = None,
    ) -> None:
        """Initialize the Gemini executor.

        Args:
            cmd: CommandRunner instance.
            binary: Path to the gemini binary.
            extra_args: Additional arguments to pass to gemini.
            dry_run: If True, commands are logged but not executed.
            use_yolo: If True, use --yolo flag for auto-approve.
            approval_mode: Approval mode (e.g., "auto_edit").
            output_format: Output format (e.g., "json", "stream-json").
            default_model: Default model to use (e.g., "gemini-2.5-pro").
        """
        super().__init__(
            binary=binary,
            extra_args=extra_args,
            dry_run=dry_run,
            default_model=default_model,
        )
        self.cmd = cmd
        self.use_yolo = use_yolo
        self.approval_mode = approval_mode
        self.output_format = output_format

    @property
    def name(self) -> str:
        """Name of the executor."""
        return "gemini"

    def _build_command(
        self,
        *,
        prompt_path: Path,
        model_selector: ModelSelector | None = None,
    ) -> tuple[list[str], dict[str, str | None]]:
        """Build the gemini command line.

        Args:
            prompt_path: Path to the prompt file.
            model_selector: Optional model selection configuration.

        Returns:
            Tuple of (command list, resolved model info).
        """
        resolved = self._resolve_model(model_selector)

        cmd = [self.binary]

        # Add model selection if specified
        # Using --model/-m for headless/scripted execution
        if resolved["model"]:
            cmd.extend(["--model", resolved["model"]])

        # Add approval mode (replaces --yolo flag)
        # Gemini 0.17+ requires using --approval-mode instead of --yolo
        if self.use_yolo:
            cmd.extend(["--approval-mode", "yolo"])
        elif self.approval_mode:
            cmd.extend(["--approval-mode", self.approval_mode])

        # Add output format for machine parsing
        if self.output_format:
            cmd.extend(["--output-format", self.output_format])

        # Add extra args
        cmd.extend(self.extra_args)

        # Add prompt file
        # Gemini uses -p or --prompt flag
        cmd.extend(["--prompt", f"@{prompt_path}"])

        return cmd, resolved

    def resolve_invocation(
        self,
        *,
        prompt_path: Path,
        cwd: Path,  # noqa: ARG002
        logs: LogPaths,
        out_path: Path | None = None,
        model_selector: ModelSelector | None = None,
    ) -> ResolvedInvocation:
        """Resolve the command invocation without executing.

        Args:
            prompt_path: Path to the prompt file.
            cwd: Working directory.
            logs: Paths for stdout/stderr logs.
            out_path: Optional output path (for text mode).
            model_selector: Optional model selection configuration.

        Returns:
            ResolvedInvocation with command and artifacts.
        """
        cmd, resolved = self._build_command(
            prompt_path=prompt_path,
            model_selector=model_selector,
        )

        artifacts = {
            "stdout": logs.stdout,
            "stderr": logs.stderr,
        }
        if out_path:
            artifacts["output"] = out_path

        # Note about Gemini sub-agents limitation
        model_note = None
        if resolved["model"]:
            model_note = (
                "Note: --model only controls main model; "
                "sub-agents may use different models"
            )

        return ResolvedInvocation(
            cmd=cmd,
            artifacts=artifacts,
            model_info={
                "executor": self.name,
                "model": resolved["model"],
                "output_format": self.output_format,
                "note": model_note,
            },
        )

    def _parse_json_output(self, stdout_path: Path) -> dict[str, Any]:
        """Parse JSON output from gemini.

        Args:
            stdout_path: Path to stdout file.

        Returns:
            Parsed JSON as dict.
        """
        if not stdout_path.exists():
            return {}

        content = stdout_path.read_text().strip()
        if not content:
            return {}

        # First try to parse the entire content as JSON (handles multi-line JSON)
        try:
            return json.loads(content)  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            pass

        # Fallback: Gemini may output multiple JSON objects (one per line)
        # We want the last complete object
        try:
            lines = content.split("\n")
            for line in reversed(lines):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    return json.loads(line)  # type: ignore[no-any-return]
            return {}
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON output from gemini")
            return {}

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
        """Run gemini to produce text output.

        Args:
            cwd: Working directory.
            prompt_path: Path to the prompt file.
            out_path: Path to write the output to.
            logs: Paths for stdout/stderr logs.
            timeout: Optional timeout in seconds.
            model_selector: Optional model selection configuration.

        Returns:
            ExecResult with execution details.
        """
        invocation = self.resolve_invocation(
            prompt_path=prompt_path,
            cwd=cwd,
            logs=logs,
            out_path=out_path,
            model_selector=model_selector,
        )

        log = logger.bind(
            mode="text",
            prompt=str(prompt_path),
            model=invocation.model_info.get("model"),
        )
        log.info("Running Gemini in text mode")

        if self.dry_run:
            log.info("Dry run - skipping execution")
            return self._dry_run_result(logs)

        try:
            result = self.cmd.run(
                invocation.cmd,
                cwd=cwd,
                stdout_path=logs.stdout,
                stderr_path=logs.stderr,
                timeout=timeout,
            )

            # Parse JSON output and extract the response
            extra = self._parse_json_output(logs.stdout)

            # Extract text content from JSON if present
            text_content = extra.get("response", "") or extra.get("text", "")
            if text_content:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(text_content)
                log.debug("Extracted response from JSON output", length=len(text_content))
            elif logs.stdout.exists():
                # Fallback: copy raw stdout
                raw_content = logs.stdout.read_text()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(raw_content)
                log.warning(
                    "No response field in JSON, copied raw stdout",
                    has_extra=bool(extra),
                    stdout_length=len(raw_content),
                )

            if result.returncode != 0:
                log.warning(
                    "Gemini returned non-zero exit code", code=result.returncode
                )
                return self._create_result(
                    returncode=result.returncode,
                    logs=logs,
                    extra=extra,
                    success=False,
                    error_message=f"Gemini failed with exit code {result.returncode}",
                    invocation=invocation,
                )

            log.info("Gemini text mode completed successfully")
            return self._create_result(
                returncode=0,
                logs=logs,
                extra=extra,
                success=True,
                invocation=invocation,
            )

        except Exception as e:
            log.error("Gemini execution failed", error=str(e))
            raise ExecutorError(
                str(e),
                executor_name=self.name,
                stdout_path=logs.stdout,
                stderr_path=logs.stderr,
            ) from e

    def run_apply(
        self,
        *,
        cwd: Path,
        prompt_path: Path,
        logs: LogPaths,
        timeout: int | None = None,
        model_selector: ModelSelector | None = None,
    ) -> ExecResult:
        """Run gemini to apply filesystem changes.

        Args:
            cwd: Working directory for file modifications.
            prompt_path: Path to the prompt file.
            logs: Paths for stdout/stderr logs.
            timeout: Optional timeout in seconds.
            model_selector: Optional model selection configuration.

        Returns:
            ExecResult with execution details.
        """
        invocation = self.resolve_invocation(
            prompt_path=prompt_path,
            cwd=cwd,
            logs=logs,
            model_selector=model_selector,
        )

        log = logger.bind(
            mode="apply",
            prompt=str(prompt_path),
            cwd=str(cwd),
            model=invocation.model_info.get("model"),
        )
        log.info("Running Gemini in apply mode")

        if self.dry_run:
            log.info("Dry run - skipping execution")
            return self._dry_run_result(logs)

        try:
            result = self.cmd.run(
                invocation.cmd,
                cwd=cwd,
                stdout_path=logs.stdout,
                stderr_path=logs.stderr,
                timeout=timeout,
            )

            extra = self._parse_json_output(logs.stdout)

            if result.returncode != 0:
                log.warning(
                    "Gemini returned non-zero exit code", code=result.returncode
                )
                return self._create_result(
                    returncode=result.returncode,
                    logs=logs,
                    extra=extra,
                    success=False,
                    error_message=f"Gemini failed with exit code {result.returncode}",
                    invocation=invocation,
                )

            log.info("Gemini apply mode completed successfully")
            return self._create_result(
                returncode=0,
                logs=logs,
                extra=extra,
                success=True,
                invocation=invocation,
            )

        except Exception as e:
            log.error("Gemini execution failed", error=str(e))
            raise ExecutorError(
                str(e),
                executor_name=self.name,
                stdout_path=logs.stdout,
                stderr_path=logs.stderr,
            ) from e
