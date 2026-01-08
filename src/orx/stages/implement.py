"""Implement stage implementation."""

from __future__ import annotations

from typing import Any

import structlog

from orx.context.backlog import WorkItem
from orx.context.snippets import (
    build_file_snippets,
    compact_text,
    extract_spec_highlights,
)
from orx.stages.base import ApplyStage, StageContext

logger = structlog.get_logger()


class ImplementStage(ApplyStage):
    """Stage that implements a work item.

    Applies changes to the workspace for a specific work item.
    """

    @property
    def name(self) -> str:
        """Name of the stage."""
        return "implement"

    @property
    def template_name(self) -> str:
        """Name of the prompt template."""
        return "implement"

    def get_template_context(self, ctx: StageContext, item: WorkItem) -> dict[str, Any]:
        """Get context variables for the template.

        Args:
            ctx: Stage context.
            item: Current work item.

        Returns:
            Dictionary of template variables.
        """
        task = ctx.pack.read_task() or ""
        spec = ctx.pack.read_spec() or ""
        task_summary = compact_text(task, max_lines=40)
        spec_highlights = extract_spec_highlights(spec, max_lines=120)
        snippets = build_file_snippets(
            worktree=ctx.workspace.worktree_path,
            files=item.files_hint,
            max_lines=120,
            max_files=8,
        )

        # Get repo context for implement stage
        repo_context = ctx.pack.read_tooling_snapshot() or ""
        verify_commands = ctx.pack.read_verify_commands() or ""

        return {
            "task_summary": task_summary,
            "spec_highlights": spec_highlights,
            "item_id": item.id,
            "item_title": item.title,
            "item_objective": item.objective,
            "acceptance": item.acceptance,
            "files_hint": item.files_hint,
            "file_snippets": snippets,
            "repo_context": repo_context,
            "verify_commands": verify_commands,
        }


class FixStage(ApplyStage):
    """Stage that fixes issues from a previous implementation attempt.

    Uses failure evidence to guide the fix.
    """

    @property
    def name(self) -> str:
        """Name of the stage."""
        return "fix"

    @property
    def template_name(self) -> str:
        """Name of the prompt template."""
        return "fix"

    def get_template_context(
        self,
        ctx: StageContext,
        item: WorkItem,
        *,
        ruff_failed: bool = False,
        ruff_log: str = "",
        pytest_failed: bool = False,
        pytest_log: str = "",
        diff_empty: bool = False,
        patch_diff: str = "",
        attempt: int = 1,
    ) -> dict[str, Any]:
        """Get context variables for the fix template.

        Args:
            ctx: Stage context.
            item: Current work item.
            ruff_failed: Whether ruff check failed.
            ruff_log: Ruff log content.
            pytest_failed: Whether pytest failed.
            pytest_log: Pytest log content.
            diff_empty: Whether no changes were made.
            patch_diff: Current diff content.
            attempt: Current attempt number.

        Returns:
            Dictionary of template variables.
        """
        task = ctx.pack.read_task() or ""
        spec = ctx.pack.read_spec() or ""
        task_summary = compact_text(task, max_lines=40)
        spec_highlights = extract_spec_highlights(spec, max_lines=120)
        snippets = build_file_snippets(
            worktree=ctx.workspace.worktree_path,
            files=item.files_hint,
            max_lines=120,
            max_files=8,
        )

        # Get repo context for fix stage
        repo_context = ctx.pack.read_tooling_snapshot() or ""
        verify_commands = ctx.pack.read_verify_commands() or ""

        return {
            "task_summary": task_summary,
            "spec_highlights": spec_highlights,
            "item_id": item.id,
            "item_title": item.title,
            "item_objective": item.objective,
            "acceptance": item.acceptance,
            "attempt": attempt,
            "ruff_failed": ruff_failed,
            "ruff_log": ruff_log,
            "pytest_failed": pytest_failed,
            "pytest_log": pytest_log,
            "diff_empty": diff_empty,
            "patch_diff": patch_diff,
            "files_hint": item.files_hint,
            "file_snippets": snippets,
            "repo_context": repo_context,
            "verify_commands": verify_commands,
        }

    def execute_fix(
        self,
        ctx: StageContext,
        item: WorkItem,
        iteration: int,
        evidence: dict[str, Any],
    ) -> Any:
        """Execute the fix stage with evidence.

        Args:
            ctx: Stage context.
            item: The work item being fixed.
            iteration: Current iteration number.
            evidence: Evidence from the failure.

        Returns:
            StageResult indicating success/failure.
        """
        log = logger.bind(stage=self.name, item_id=item.id, iteration=iteration)
        log.info("Executing fix stage")

        try:
            # Build template context with evidence
            template_context = self.get_template_context(
                ctx,
                item,
                ruff_failed=evidence.get("ruff_failed", False),
                ruff_log=evidence.get("ruff_log", ""),
                pytest_failed=evidence.get("pytest_failed", False),
                pytest_log=evidence.get("pytest_log", ""),
                diff_empty=evidence.get("diff_empty", False),
                patch_diff=evidence.get("patch_diff", ""),
                attempt=iteration,
            )

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

            result = ctx.executor.run_apply(
                cwd=ctx.workspace.worktree_path,
                prompt_path=prompt_path,
                logs=logs,
            )

            if result.failed:
                log.error("Fix executor failed", error=result.error_message)
                return self._failure(f"Fix failed: {result.error_message}")

            log.info("Fix stage completed")
            return self._success(f"Fix completed for {item.id}")

        except Exception as e:
            log.error("Fix stage failed", error=str(e))
            return self._failure(str(e))
