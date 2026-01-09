"""GitHub Copilot CLI executor implementation."""

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


class CopilotExecutor(BaseExecutor):
    """Executor adapter for GitHub Copilot CLI.

    Wraps the copilot CLI in non-interactive mode with --prompt and --allow-all-tools.
    Supports model selection via --model flag.

    Key differences from Codex:
    - Uses `copilot --prompt <text>` for non-interactive execution
    - Uses `--allow-all-tools` instead of `--full-auto`
    - Uses `--allow-all-paths` for filesystem access
    - Supports @ file references in prompts
    - No profile support (unlike Codex)

    Available models (as of Jan 2026):
    - claude-sonnet-4.5: Claude Sonnet 4.5 (Anthropic) - Most capable
    - claude-sonnet-4: Claude Sonnet 4 (Anthropic)
    - claude-haiku-4.5: Claude Haiku 4.5 (Anthropic) - Fast, efficient (default)
    - gpt-5: GPT-5 (OpenAI) - Supports reasoning effort

    Model selection priority:
    1. stage.model (explicit model override)
    2. executor.default.model (default model)
    3. engine.model (legacy global config)
    4. CLI default (fallback to copilot config)

    Example:
        >>> executor = CopilotExecutor(cmd=CommandRunner())
        >>> result = executor.run_apply(
        ...     cwd=Path("/workspace"),
        ...     prompt_path=Path("/prompts/implement.md"),
        ...     logs=LogPaths(stdout=Path("out.log"), stderr=Path("err.log")),
        ...     model_selector=ModelSelector(model="gpt-5-mini"),
        ... )
    """

    def __init__(
        self,
        *,
        cmd: CommandRunner,
        binary: str = "copilot",
        extra_args: list[str] | None = None,
        dry_run: bool = False,
        default_model: str | None = None,
        allow_all_tools: bool = True,
        allow_all_paths: bool = True,
        no_custom_instructions: bool = False,
        log_level: str | None = None,
    ) -> None:
        """Initialize the Copilot executor.

        Args:
            cmd: CommandRunner instance.
            binary: Path to the copilot binary.
            extra_args: Additional arguments to pass to copilot.
            dry_run: If True, commands are logged but not executed.
            default_model: Default model to use (e.g., "gpt-5-mini").
            allow_all_tools: If True, use --allow-all-tools for auto-approve.
            allow_all_paths: If True, use --allow-all-paths for file access.
            no_custom_instructions: If True, disable AGENTS.md loading.
            log_level: Log level for copilot CLI (none/error/warning/info/debug).
        """
        super().__init__(
            binary=binary,
            extra_args=extra_args,
            dry_run=dry_run,
            default_model=default_model,
        )
        self.cmd = cmd
        self.allow_all_tools = allow_all_tools
        self.allow_all_paths = allow_all_paths
        self.no_custom_instructions = no_custom_instructions
        self.log_level = log_level

    @property
    def name(self) -> str:
        """Name of the executor."""
        return "copilot"

    def _build_command(
        self,
        *,
        prompt_path: Path,
        cwd: Path,
        model_selector: ModelSelector | None = None,
        out_path: Path | None = None,
        text_only: bool = False,
    ) -> tuple[list[str], dict[str, Any]]:
        """Build the copilot command line.

        Args:
            prompt_path: Path to the prompt file.
            cwd: Working directory.
            model_selector: Optional model selection configuration.
            out_path: Optional output path (unused, for interface compat).
            text_only: If True, don't allow file modifications (for text stages).

        Returns:
            Tuple of (command list, resolved model info dict).
        """
        resolved = self._resolve_model(model_selector)
        # Mark out_path as used for linting compatibility (interface compatibility)
        _ = out_path

        cmd = [self.binary]

        # Add model selection if specified
        if resolved["model"]:
            cmd.extend(["--model", resolved["model"]])

        # Non-interactive mode: require prompt flag
        # Auto-approve tools unless text_only (read-only mode)
        if not text_only:
            if self.allow_all_tools:
                cmd.append("--allow-all-tools")
            if self.allow_all_paths:
                cmd.append("--allow-all-paths")
        else:
            # Text-only mode: allow reading but deny write tools
            cmd.extend(["--deny-tool", "write"])
            cmd.extend(["--deny-tool", "shell"])
            if self.allow_all_paths:
                cmd.append("--allow-all-paths")

        # Add additional working directory access
        cmd.extend(["--add-dir", str(cwd)])

        # Disable custom instructions if requested
        if self.no_custom_instructions:
            cmd.append("--no-custom-instructions")

        # Set log level if specified
        if self.log_level:
            cmd.extend(["--log-level", self.log_level])

        # Disable banner for cleaner output
        # cmd.append("--no-banner")  # If supported

        # Add extra args
        cmd.extend(self.extra_args)

        # Add prompt via --prompt with @file reference
        # Copilot supports @file syntax for including file contents
        cmd.extend(["--prompt", f"@{prompt_path}"])

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
                "allow_all_tools": self.allow_all_tools and not text_only,
                "text_only": text_only,
            },
        )

    def _parse_output(self, stdout_path: Path) -> tuple[str, dict[str, Any]]:
        """Parse output from copilot CLI.

        Copilot outputs text directly to stdout. We extract the response
        and any structured data if available.

        Args:
            stdout_path: Path to stdout file.

        Returns:
            Tuple of (text content, extra dict).
        """
        if not stdout_path.exists():
            return "", {}

        content = stdout_path.read_text().strip()
        if not content:
            return "", {}

        extra: dict[str, Any] = {}

        # Copilot may include JSON metadata at the end
        # Try to extract it
        lines = content.split("\n")

        # Check if last line is JSON metadata
        if lines and lines[-1].strip().startswith("{"):
            try:
                metadata = json.loads(lines[-1])
                extra = metadata
                # Remove metadata from content
                content = "\n".join(lines[:-1]).strip()
            except json.JSONDecodeError:
                pass

        return content, extra

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
        """Run copilot to produce text output.

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
        )
        log.info("Running Copilot in text mode")

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

            # Parse output
            text_content, extra = self._parse_output(logs.stdout)

            # Write extracted text to output file
            if text_content:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(text_content)
                log.debug("Extracted response", length=len(text_content))
            elif logs.stdout.exists():
                # Fallback: copy raw stdout
                raw_content = logs.stdout.read_text()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(raw_content)
                log.warning(
                    "No parsed content, copied raw stdout",
                    stdout_length=len(raw_content),
                )

            if result.returncode != 0:
                log.warning(
                    "Copilot returned non-zero exit code", code=result.returncode
                )
                return self._create_result(
                    returncode=result.returncode,
                    logs=logs,
                    extra=extra,
                    success=False,
                    error_message=f"Copilot failed with exit code {result.returncode}",
                    invocation=invocation,
                )

            log.info("Copilot text mode completed successfully")
            return self._create_result(
                returncode=0,
                logs=logs,
                extra=extra,
                success=True,
                invocation=invocation,
            )

        except Exception as e:
            log.error("Copilot execution failed", error=str(e))
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
        """Run copilot to apply filesystem changes.

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
            text_only=False,
        )

        log = logger.bind(
            mode="apply",
            prompt=str(prompt_path),
            cwd=str(cwd),
            model=invocation.model_info.get("model"),
        )
        log.info("Running Copilot in apply mode")

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

            _, extra = self._parse_output(logs.stdout)

            if result.returncode != 0:
                log.warning(
                    "Copilot returned non-zero exit code", code=result.returncode
                )
                return self._create_result(
                    returncode=result.returncode,
                    logs=logs,
                    extra=extra,
                    success=False,
                    error_message=f"Copilot failed with exit code {result.returncode}",
                    invocation=invocation,
                )

            log.info("Copilot apply mode completed successfully")
            return self._create_result(
                returncode=0,
                logs=logs,
                extra=extra,
                success=True,
                invocation=invocation,
            )

        except Exception as e:
            log.error("Copilot execution failed", error=str(e))
            raise ExecutorError(
                str(e),
                executor_name=self.name,
                stdout_path=logs.stdout,
                stderr_path=logs.stderr,
            ) from e
