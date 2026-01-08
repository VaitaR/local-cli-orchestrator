"""Base stage protocol and common functionality."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:
    from orx.config import ModelSelector
    from orx.context.backlog import WorkItem
    from orx.context.pack import ContextPack
    from orx.executors.base import Executor
    from orx.gates.base import Gate
    from orx.metrics.events import EventLogger
    from orx.paths import RunPaths
    from orx.prompts.renderer import PromptRenderer
    from orx.state import StateManager
    from orx.workspace.git_worktree import WorkspaceGitWorktree

logger = structlog.get_logger()


@dataclass
class StageResult:
    """Result of a stage execution.

    Attributes:
        success: Whether the stage succeeded.
        message: Description of the result.
        next_stage: Suggested next stage (if any).
        data: Any additional data from the stage.
    """

    success: bool
    message: str = ""
    next_stage: str | None = None
    data: dict[str, Any] | None = None


@dataclass
class StageContext:
    """Context passed to stage execution.

    Attributes:
        paths: RunPaths for the run.
        pack: ContextPack for artifacts.
        state: StateManager for state.
        workspace: WorkspaceGitWorktree for file operations.
        executor: The executor to use.
        gates: List of gates to run.
        renderer: Prompt renderer.
        config: Run configuration.
        model_selector: Model selection configuration for this stage.
    """

    paths: "RunPaths"
    pack: "ContextPack"
    state: "StateManager"
    workspace: "WorkspaceGitWorktree"
    executor: "Executor"
    gates: list["Gate"]
    renderer: "PromptRenderer"
    config: dict[str, Any]
    timeout_seconds: int | None = None
    model_selector: "ModelSelector | None" = None
    events: "EventLogger | None" = None


@runtime_checkable
class StageProtocol(Protocol):
    """Protocol for stage implementations."""

    @property
    def name(self) -> str:
        """Name of the stage."""
        ...

    def execute(self, ctx: StageContext) -> StageResult:
        """Execute the stage.

        Args:
            ctx: Stage context with all dependencies.

        Returns:
            StageResult indicating success/failure.
        """
        ...


class BaseStage(ABC):
    """Base class for stage implementations.

    Provides common functionality for all stages.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the stage."""
        ...

    @abstractmethod
    def execute(self, ctx: StageContext) -> StageResult:
        """Execute the stage.

        Args:
            ctx: Stage context with all dependencies.

        Returns:
            StageResult indicating success/failure.
        """
        ...

    def _render_and_save_prompt(
        self,
        ctx: StageContext,
        template_name: str,
        **context: Any,
    ) -> Path:
        """Render a prompt and save it to the prompts directory.

        Args:
            ctx: Stage context.
            template_name: Name of the template.
            **context: Variables for the template.

        Returns:
            Path to the saved prompt file.
        """
        prompt_path = ctx.paths.prompt_path(template_name)
        ctx.renderer.render_to_file(template_name, prompt_path, **context)
        return prompt_path

    def _success(
        self,
        message: str = "",
        next_stage: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> StageResult:
        """Create a success result."""
        return StageResult(
            success=True,
            message=message,
            next_stage=next_stage,
            data=data,
        )

    def _failure(
        self,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> StageResult:
        """Create a failure result."""
        return StageResult(
            success=False,
            message=message,
            data=data,
        )


class TextOutputStage(BaseStage):
    """Base class for stages that produce text output.

    Handles the common pattern of:
    1. Render prompt
    2. Run executor in text mode
    3. Save output to context
    """

    @property
    @abstractmethod
    def template_name(self) -> str:
        """Name of the prompt template."""
        ...

    @abstractmethod
    def get_template_context(self, ctx: StageContext) -> dict[str, Any]:
        """Get context variables for the template.

        Args:
            ctx: Stage context.

        Returns:
            Dictionary of template variables.
        """
        ...

    @abstractmethod
    def save_output(self, ctx: StageContext, content: str) -> None:
        """Save the stage output.

        Args:
            ctx: Stage context.
            content: The output content.
        """
        ...

    def execute(self, ctx: StageContext) -> StageResult:
        """Execute the text output stage.

        Args:
            ctx: Stage context.

        Returns:
            StageResult indicating success/failure.
        """
        log = logger.bind(stage=self.name)
        log.info("Executing text output stage")

        try:
            # Render prompt
            template_context = self.get_template_context(ctx)
            prompt_path = self._render_and_save_prompt(
                ctx, self.template_name, **template_context
            )

            # Get log paths
            stdout_path, stderr_path = ctx.paths.agent_log_paths(self.name)

            # Run executor
            from orx.executors.base import LogPaths

            logs = LogPaths(stdout=stdout_path, stderr=stderr_path)
            out_path = ctx.paths.context_dir / f"{self.name}_output.md"

            if ctx.events:
                ctx.events.log(
                    "executor_start",
                    stage=self.name,
                    mode="text",
                    prompt=str(prompt_path),
                )

            result = ctx.executor.run_text(
                cwd=ctx.workspace.worktree_path,
                prompt_path=prompt_path,
                out_path=out_path,
                logs=logs,
                timeout=ctx.timeout_seconds,
                model_selector=ctx.model_selector,
            )
            if ctx.events:
                ctx.events.log(
                    "executor_end",
                    stage=self.name,
                    mode="text",
                    returncode=result.returncode,
                    success=not result.failed,
                )

            if result.failed:
                log.error("Executor failed", error=result.error_message)
                return self._failure(f"Executor failed: {result.error_message}")

            # Read and save output
            if out_path.exists():
                content = out_path.read_text()
                self.save_output(ctx, content)
                log.info("Stage completed successfully")
                return self._success(f"{self.name} completed")
            else:
                log.error("No output produced")
                return self._failure("Executor produced no output")

        except Exception as e:
            log.error("Stage failed", error=str(e))
            return self._failure(str(e))


class ApplyStage(BaseStage):
    """Base class for stages that apply filesystem changes.

    Handles the common pattern of:
    1. Render prompt
    2. Run executor in apply mode
    3. Verify changes were made
    """

    @property
    @abstractmethod
    def template_name(self) -> str:
        """Name of the prompt template."""
        ...

    @abstractmethod
    def get_template_context(self, ctx: StageContext, item: WorkItem) -> dict[str, Any]:
        """Get context variables for the template.

        Args:
            ctx: Stage context.
            item: Current work item.

        Returns:
            Dictionary of template variables.
        """
        ...

    def execute_for_item(
        self, ctx: StageContext, item: WorkItem, iteration: int = 1
    ) -> StageResult:
        """Execute the apply stage for a specific work item.

        Args:
            ctx: Stage context.
            item: The work item to implement.
            iteration: Current iteration (for fix loop).

        Returns:
            StageResult indicating success/failure.
        """
        log = logger.bind(stage=self.name, item_id=item.id, iteration=iteration)
        log.info("Executing apply stage for item")

        try:
            # Render prompt
            template_context = self.get_template_context(ctx, item)
            prompt_path = self._render_and_save_prompt(
                ctx, self.template_name, **template_context
            )

            # Get log paths
            stdout_path, stderr_path = ctx.paths.agent_log_paths(
                self.name, item_id=item.id, iteration=iteration
            )

            # Run executor
            from orx.executors.base import LogPaths

            logs = LogPaths(stdout=stdout_path, stderr=stderr_path)

            if ctx.events:
                ctx.events.log(
                    "executor_start",
                    stage=self.name,
                    mode="apply",
                    item_id=item.id,
                    iteration=iteration,
                    prompt=str(prompt_path),
                )

            result = ctx.executor.run_apply(
                cwd=ctx.workspace.worktree_path,
                prompt_path=prompt_path,
                logs=logs,
                timeout=ctx.timeout_seconds,
                model_selector=ctx.model_selector,
            )
            if ctx.events:
                ctx.events.log(
                    "executor_end",
                    stage=self.name,
                    mode="apply",
                    item_id=item.id,
                    iteration=iteration,
                    returncode=result.returncode,
                    success=not result.failed,
                )

            if result.failed:
                log.error("Executor failed", error=result.error_message)
                return self._failure(f"Executor failed: {result.error_message}")

            log.info("Apply stage completed")
            return self._success(f"{self.name} completed for {item.id}")

        except Exception as e:
            log.error("Stage failed", error=str(e))
            return self._failure(str(e))

    def execute(self, ctx: StageContext) -> StageResult:  # noqa: ARG002
        """Execute is not directly called for apply stages.

        Use execute_for_item instead.
        """
        return self._failure("ApplyStage.execute should not be called directly")
