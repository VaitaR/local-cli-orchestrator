"""Spec stage implementation."""

from __future__ import annotations

from typing import Any

from orx.stages.base import StageContext, TextOutputStage


class SpecStage(TextOutputStage):
    """Stage that generates the technical specification.

    Reads the task and plan to produce a spec.md document.
    """

    @property
    def name(self) -> str:
        """Name of the stage."""
        return "spec"

    @property
    def template_name(self) -> str:
        """Name of the prompt template."""
        return "spec"

    def get_template_context(self, ctx: StageContext) -> dict[str, Any]:
        """Get context variables for the template.

        Args:
            ctx: Stage context.

        Returns:
            Dictionary of template variables.
        """
        task = ctx.pack.read_task() or ""
        plan = ctx.pack.read_plan() or ""
        project_context = ctx.pack.read_project_map() or ""

        return {
            "task": task,
            "plan": plan,
            "project_context": project_context,
        }

    def save_output(self, ctx: StageContext, content: str) -> None:
        """Save the spec output.

        Args:
            ctx: Stage context.
            content: The spec content.
        """
        ctx.pack.write_spec(content)
