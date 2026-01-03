"""Codex CLI executor implementation."""

from __future__ import annotations

from pathlib import Path

import structlog

from orx.exceptions import ExecutorError
from orx.executors.base import BaseExecutor, ExecResult, LogPaths
from orx.infra.command import CommandRunner

logger = structlog.get_logger()


class CodexExecutor(BaseExecutor):
    """Executor adapter for Codex CLI.

    Wraps the codex CLI to run with --full-auto mode.

    Example:
        >>> executor = CodexExecutor(cmd=CommandRunner())
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
        binary: str = "codex",
        extra_args: list[str] | None = None,
        dry_run: bool = False,
        use_json_output: bool = False,
    ) -> None:
        """Initialize the Codex executor.

        Args:
            cmd: CommandRunner instance.
            binary: Path to the codex binary.
            extra_args: Additional arguments to pass to codex.
            dry_run: If True, commands are logged but not executed.
            use_json_output: If True, use --json for event stream output.
        """
        super().__init__(binary=binary, extra_args=extra_args, dry_run=dry_run)
        self.cmd = cmd
        self.use_json_output = use_json_output

    @property
    def name(self) -> str:
        """Name of the executor."""
        return "codex"

    def _build_command(
        self,
        *,
        prompt_path: Path,
        cwd: Path,
    ) -> list[str]:
        """Build the codex command line.

        Args:
            prompt_path: Path to the prompt file.
            cwd: Working directory.
            text_mode: If True, expect text output rather than file changes.

        Returns:
            Command as list of strings.
        """
        cmd = [
            self.binary,
            "exec",
            "--full-auto",
            "--cd",
            str(cwd),
        ]

        # Add JSON output if configured
        if self.use_json_output:
            cmd.append("--json")

        # Add extra args
        cmd.extend(self.extra_args)

        # Add the prompt content via file reference
        # Codex expects the prompt as the final argument or via stdin
        # We use @ prefix to read from file
        cmd.append(f"@{prompt_path}")

        return cmd

    def run_text(
        self,
        *,
        cwd: Path,
        prompt_path: Path,
        out_path: Path,
        logs: LogPaths,
        timeout: int | None = None,
    ) -> ExecResult:
        """Run codex to produce text output.

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
        log.info("Running Codex in text mode")

        if self.dry_run:
            log.info("Dry run - skipping execution")
            return self._dry_run_result(logs)

        command = self._build_command(
            prompt_path=prompt_path,
            cwd=cwd,
        )

        try:
            result = self.cmd.run(
                command,
                cwd=cwd,
                stdout_path=logs.stdout,
                stderr_path=logs.stderr,
                timeout=timeout,
            )

            # For text mode, we expect the output to go to stdout
            # Copy stdout to the output file
            if logs.stdout.exists():
                content = logs.stdout.read_text()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(content)

            if result.returncode != 0:
                log.warning("Codex returned non-zero exit code", code=result.returncode)
                return self._create_result(
                    returncode=result.returncode,
                    logs=logs,
                    success=False,
                    error_message=f"Codex failed with exit code {result.returncode}",
                )

            log.info("Codex text mode completed successfully")
            return self._create_result(returncode=0, logs=logs, success=True)

        except Exception as e:
            log.error("Codex execution failed", error=str(e))
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
        """Run codex to apply filesystem changes.

        Args:
            cwd: Working directory for file modifications.
            prompt_path: Path to the prompt file.
            logs: Paths for stdout/stderr logs.
            timeout: Optional timeout in seconds.

        Returns:
            ExecResult with execution details.
        """
        log = logger.bind(mode="apply", prompt=str(prompt_path), cwd=str(cwd))
        log.info("Running Codex in apply mode")

        if self.dry_run:
            log.info("Dry run - skipping execution")
            return self._dry_run_result(logs)

        command = self._build_command(
            prompt_path=prompt_path,
            cwd=cwd,
        )

        try:
            result = self.cmd.run(
                command,
                cwd=cwd,
                stdout_path=logs.stdout,
                stderr_path=logs.stderr,
                timeout=timeout,
            )

            if result.returncode != 0:
                log.warning("Codex returned non-zero exit code", code=result.returncode)
                return self._create_result(
                    returncode=result.returncode,
                    logs=logs,
                    success=False,
                    error_message=f"Codex failed with exit code {result.returncode}",
                )

            log.info("Codex apply mode completed successfully")
            return self._create_result(returncode=0, logs=logs, success=True)

        except Exception as e:
            log.error("Codex execution failed", error=str(e))
            raise ExecutorError(
                str(e),
                executor_name=self.name,
                stdout_path=logs.stdout,
                stderr_path=logs.stderr,
            ) from e
