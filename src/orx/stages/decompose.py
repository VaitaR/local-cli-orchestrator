"""Decompose stage implementation."""

from __future__ import annotations

from typing import Any

import structlog

from orx.context.backlog import Backlog
from orx.stages.base import StageContext, StageResult, TextOutputStage

logger = structlog.get_logger()


class DecomposeStage(TextOutputStage):
    """Stage that decomposes the spec into work items.

    Reads the spec and produces a backlog.yaml file.
    """

    @property
    def name(self) -> str:
        """Name of the stage."""
        return "decompose"

    @property
    def template_name(self) -> str:
        """Name of the prompt template."""
        return "decompose"

    def get_template_context(self, ctx: StageContext) -> dict[str, Any]:
        """Get context variables for the template.

        Args:
            ctx: Stage context.

        Returns:
            Dictionary of template variables.
        """
        spec = ctx.pack.read_spec() or ""
        plan = ctx.pack.read_plan() or ""

        return {
            "spec": spec,
            "plan": plan,
            "run_id": ctx.paths.run_id,
        }

    def save_output(self, ctx: StageContext, content: str) -> None:
        """Save the backlog output.

        Args:
            ctx: Stage context.
            content: The backlog YAML content.
        """
        # Write raw content first
        ctx.paths.backlog_yaml.write_text(content)

    def execute(self, ctx: StageContext) -> StageResult:
        """Execute the decompose stage.

        Overrides base to add backlog validation.

        Args:
            ctx: Stage context.

        Returns:
            StageResult indicating success/failure.
        """
        log = logger.bind(stage=self.name)

        # Run the base text output stage
        result = super().execute(ctx)

        if not result.success:
            return result

        # Validate the backlog
        try:
            backlog = Backlog.load(ctx.paths.backlog_yaml)

            # Validate dependencies
            errors = backlog.validate_dependencies()
            if errors:
                log.error("Backlog dependency errors", errors=errors)
                return self._failure(f"Invalid backlog: {'; '.join(errors)}")

            # Check for cycles
            cycles = backlog.detect_cycles()
            if cycles:
                log.error("Backlog has cycles", cycles=cycles)
                return self._failure(f"Backlog has cycles: {'; '.join(cycles)}")

            log.info(
                "Backlog validated",
                item_count=len(backlog.items),
            )
            return self._success(
                f"Decomposed into {len(backlog.items)} work items",
                data={"item_count": len(backlog.items)},
            )

        except Exception as e:
            log.error("Failed to parse backlog", error=str(e))
            return self._failure(f"Invalid backlog YAML: {e}")
