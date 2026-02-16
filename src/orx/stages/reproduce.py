"""Reproduce stage implementation."""

from __future__ import annotations

from typing import Any

from orx.context.backlog import WorkItem
from orx.stages.base import ApplyStage, StageContext


class ReproduceStage(ApplyStage):
    """Stage that creates a reproduction case (failing test).

    Produces a test file that is expected to fail, demonstrating the issue
    or verifying the lack of a feature.
    """

    @property
    def name(self) -> str:
        """Name of the stage."""
        return "reproduce"

    @property
    def template_name(self) -> str:
        """Name of the prompt template."""
        return "reproduce"

    def get_template_context(self, ctx: StageContext, _item: WorkItem) -> dict[str, Any]:
        """Get context variables for the template.

        Args:
            ctx: Stage context.
            _item: Current work item (unused; reproduce runs once per task).

        Returns:
            Dictionary of template variables.
        """
        task = ctx.pack.read_task() or ""

        # Get repo context
        repo_context = ctx.pack.read_tooling_snapshot() or ""

        # We can also include existing tests to help match style
        # But for now, minimal context is better to avoid confusion

        return {
            "task": task,
            "repo_context": repo_context,
        }
