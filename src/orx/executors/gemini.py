"""Gemini CLI executor implementation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

from orx.exceptions import ExecutorError
from orx.executors.base import BaseExecutor, ExecResult, LogPaths
from orx.infra.command import CommandRunner

logger = structlog.get_logger()


class GeminiExecutor(BaseExecutor):
    """Executor adapter for Gemini CLI.

    Wraps the gemini CLI with headless and auto-approve modes.

    Example:
        >>> executor = GeminiExecutor(cmd=CommandRunner())
        >>> result = executor.run_apply(
        ...     cwd=Path("/workspace"),
        ...     prompt_path=Path("/prompts/implement.md"),
        ...     logs=LogPaths(stdout=Path("out.log"), stderr=Path("err.log")),
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
    ) -> None:
        """Initialize the Gemini executor.

        Args:
            cmd: CommandRunner instance.
            binary: Path to the gemini binary.
            extra_args: Additional arguments to pass to gemini.
            dry_run: If True, commands are logged but not executed.
            use_yolo: If True, use --yolo flag for auto-approve.
            approval_mode: Approval mode (e.g., "auto_edit").
        """
        super().__init__(binary=binary, extra_args=extra_args, dry_run=dry_run)
        self.cmd = cmd
        self.use_yolo = use_yolo
        self.approval_mode = approval_mode

    @property
    def name(self) -> str:
        """Name of the executor."""
        return "gemini"

    def _build_command(
        self,
        *,
        prompt_path: Path,
    ) -> list[str]:
        """Build the gemini command line.

        Args:
            prompt_path: Path to the prompt file.
            cwd: Working directory.
            text_mode: If True, expect text output rather than file changes.

        Returns:
            Command as list of strings.
        """
        cmd = [self.binary]

        # Add yolo mode for auto-approve
        if self.use_yolo:
            cmd.append("--yolo")

        # Add approval mode
        if self.approval_mode:
            cmd.extend(["--approval-mode", self.approval_mode])

        # Always use JSON output for machine parsing
        cmd.extend(["--output-format", "json"])

        # Add extra args
        cmd.extend(self.extra_args)

        # Add prompt file
        # Gemini uses -p or --prompt flag
        cmd.extend(["--prompt", f"@{prompt_path}"])

        return cmd

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

        try:
            # Gemini may output multiple JSON objects (one per line)
            # We want the last complete object
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
    ) -> ExecResult:
        """Run gemini to produce text output.

        Args:
            cwd: Working directory.
            prompt_path: Path to the prompt file.
            out_path: Path to write the output to.
            logs: Paths for stdout/stderr logs.
            timeout: Optional timeout in seconds.

        Returns:
            ExecResult with execution details.
        """
        log = logger.bind(mode="text", prompt=str(prompt_path))
        log.info("Running Gemini in text mode")

        if self.dry_run:
            log.info("Dry run - skipping execution")
            return self._dry_run_result(logs)

        command = self._build_command(
            prompt_path=prompt_path,
        )

        try:
            result = self.cmd.run(
                command,
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
            elif logs.stdout.exists():
                # Fallback: copy raw stdout
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(logs.stdout.read_text())

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
                )

            log.info("Gemini text mode completed successfully")
            return self._create_result(
                returncode=0, logs=logs, extra=extra, success=True
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
    ) -> ExecResult:
        """Run gemini to apply filesystem changes.

        Args:
            cwd: Working directory for file modifications.
            prompt_path: Path to the prompt file.
            logs: Paths for stdout/stderr logs.
            timeout: Optional timeout in seconds.

        Returns:
            ExecResult with execution details.
        """
        log = logger.bind(mode="apply", prompt=str(prompt_path), cwd=str(cwd))
        log.info("Running Gemini in apply mode")

        if self.dry_run:
            log.info("Dry run - skipping execution")
            return self._dry_run_result(logs)

        command = self._build_command(
            prompt_path=prompt_path,
        )

        try:
            result = self.cmd.run(
                command,
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
                )

            log.info("Gemini apply mode completed successfully")
            return self._create_result(
                returncode=0, logs=logs, extra=extra, success=True
            )

        except Exception as e:
            log.error("Gemini execution failed", error=str(e))
            raise ExecutorError(
                str(e),
                executor_name=self.name,
                stdout_path=logs.stdout,
                stderr_path=logs.stderr,
            ) from e
