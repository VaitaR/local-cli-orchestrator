"""Plan stage implementation."""

from __future__ import annotations

from typing import Any

from orx.stages.base import StageContext, TextOutputStage


class PlanStage(TextOutputStage):
    """Stage that generates the implementation plan.

    Reads the task and produces a plan.md document.
    """

    @property
    def name(self) -> str:
        """Name of the stage."""
        return "plan"

    @property
    def template_name(self) -> str:
        """Name of the prompt template."""
        return "plan"

    def get_template_context(self, ctx: StageContext) -> dict[str, Any]:
        """Get context variables for the template.

        Args:
            ctx: Stage context.

        Returns:
            Dictionary of template variables.
        """
        task = ctx.pack.read_task() or ""
        project_context = ctx.pack.read_project_map() or ""

        return {
            "task": task,
            "project_context": project_context,
        }

    def save_output(self, ctx: StageContext, content: str) -> None:
        """Save the plan output.

        Args:
            ctx: Stage context.
            content: The plan content.
        """
        ctx.pack.write_plan(content)
