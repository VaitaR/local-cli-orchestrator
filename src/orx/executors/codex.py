"""Codex CLI executor implementation."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from orx.exceptions import ExecutorError
from orx.executors.base import BaseExecutor, ExecResult, LogPaths, ResolvedInvocation
from orx.infra.command import CommandRunner

if TYPE_CHECKING:
    from orx.config import ModelSelector

logger = structlog.get_logger()


class CodexExecutor(BaseExecutor):
    """Executor adapter for Codex CLI.

    Wraps the codex CLI. Apply mode uses --full-auto, while text mode
    runs in a read-only sandbox with no approvals to avoid tool usage.
    Supports model selection via --model/-m flag or --profile/-p flag.

    Model selection priority:
    1. stage.model (explicit model override)
    2. stage.profile (profile override, for Codex)
    3. executor.default.model (default model)
    4. executor.profiles[stage] (stage-specific profile)
    5. CLI default (fallback to codex config)

    Example:
        >>> executor = CodexExecutor(cmd=CommandRunner())
        >>> result = executor.run_apply(
        ...     cwd=Path("/workspace"),
        ...     prompt_path=Path("/prompts/implement.md"),
        ...     logs=LogPaths(stdout=Path("out.log"), stderr=Path("err.log")),
        ...     model_selector=ModelSelector(model="gpt-5.2"),
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
        default_model: str | None = None,
        default_profile: str | None = None,
        default_reasoning_effort: str | None = None,
    ) -> None:
        """Initialize the Codex executor.

        Args:
            cmd: CommandRunner instance.
            binary: Path to the codex binary.
            extra_args: Additional arguments to pass to codex.
            dry_run: If True, commands are logged but not executed.
            use_json_output: If True, use --json for event stream output.
            default_model: Default model to use (e.g., "gpt-5.2").
            default_profile: Default profile to use.
            default_reasoning_effort: Default reasoning effort (low/medium/high).
        """
        super().__init__(
            binary=binary,
            extra_args=extra_args,
            dry_run=dry_run,
            default_model=default_model,
            default_profile=default_profile,
            default_reasoning_effort=default_reasoning_effort,
        )
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
        model_selector: ModelSelector | None = None,
        out_path: Path | None = None,
        text_only: bool = False,
    ) -> tuple[list[str], dict[str, str | None]]:
        """Build the codex command line.

        Args:
            prompt_path: Path to the prompt file.
            cwd: Working directory.
            model_selector: Optional model selection configuration.
            out_path: Optional output path for --output-last-message.
            text_only: If True, run with a read-only sandbox and no approvals.

        Returns:
            Tuple of (command list, resolved model info).
        """
        resolved = self._resolve_model(model_selector)

        cmd = [
            self.binary,
            "exec",
            "--cd",
            str(cwd),
        ]
        if text_only:
            cmd.extend(["--sandbox", "read-only"])
        else:
            cmd.append("--full-auto")

        # Enable Codex web search tool if requested for this stage.
        if model_selector and getattr(model_selector, "web_search", False):
            cmd.append("--search")

        # Add model or profile selection
        if resolved["model"]:
            cmd.extend(["-m", resolved["model"]])
        elif resolved["profile"]:
            cmd.extend(["-p", resolved["profile"]])

        # Add reasoning effort if specified
        # Via one-off config: --config model_reasoning_effort='"high"'
        if resolved["reasoning_effort"]:
            effort = resolved["reasoning_effort"]
            cmd.extend(["--config", f'model_reasoning_effort="{effort}"'])

        # Add JSON output if configured
        if self.use_json_output:
            cmd.append("--json")

        # Add output-last-message for capturing final response
        if out_path:
            cmd.extend(["--output-last-message", str(out_path)])

        # Add extra args
        cmd.extend(self.extra_args)

        # Add the prompt content via file reference
        # Codex expects the prompt as the final argument or via stdin
        # We use @ prefix to read from file
        cmd.append(f"@{prompt_path}")

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
            text_only: If True, run with a read-only sandbox and no approvals.

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
        if self.use_json_output:
            artifacts["jsonl"] = logs.stdout.with_suffix(".jsonl")

        return ResolvedInvocation(
            cmd=cmd,
            artifacts=artifacts,
            model_info={
                "executor": self.name,
                "model": resolved["model"],
                "profile": resolved["profile"],
                "reasoning_effort": resolved["reasoning_effort"],
                "web_search": bool(model_selector and getattr(model_selector, "web_search", False)),
            },
        )

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
        """Run codex to produce text output.

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
            text_only=True,
        )

        log = logger.bind(
            mode="text",
            prompt=str(prompt_path),
            model=invocation.model_info.get("model"),
            profile=invocation.model_info.get("profile"),
        )
        log.info("Running Codex in text mode")

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

            # For text mode without --output-last-message, output goes to stdout
            # If we're using --output-last-message, output goes to out_path directly
            if (
                not any("--output-last-message" in arg for arg in invocation.cmd)
                and logs.stdout.exists()
            ):
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
                    invocation=invocation,
                )

            log.info("Codex text mode completed successfully")
            return self._create_result(
                returncode=0,
                logs=logs,
                success=True,
                invocation=invocation,
            )

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
        model_selector: ModelSelector | None = None,
    ) -> ExecResult:
        """Run codex to apply filesystem changes.

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
            profile=invocation.model_info.get("profile"),
        )
        log.info("Running Codex in apply mode")

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

            if result.returncode != 0:
                log.warning("Codex returned non-zero exit code", code=result.returncode)
                return self._create_result(
                    returncode=result.returncode,
                    logs=logs,
                    success=False,
                    error_message=f"Codex failed with exit code {result.returncode}",
                    invocation=invocation,
                )

            log.info("Codex apply mode completed successfully")
            return self._create_result(
                returncode=0,
                logs=logs,
                success=True,
                invocation=invocation,
            )

        except Exception as e:
            log.error("Codex execution failed", error=str(e))
            raise ExecutorError(
                str(e),
                executor_name=self.name,
                stdout_path=logs.stdout,
                stderr_path=logs.stderr,
            ) from e
