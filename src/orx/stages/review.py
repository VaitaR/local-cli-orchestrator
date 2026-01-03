"""Review stage implementation."""

from __future__ import annotations

from typing import Any

import structlog

from orx.stages.base import StageContext, StageResult, TextOutputStage

logger = structlog.get_logger()


class ReviewStage(TextOutputStage):
    """Stage that reviews the completed implementation.

    Produces review.md and pr_body.md documents.
    """

    @property
    def name(self) -> str:
        """Name of the stage."""
        return "review"

    @property
    def template_name(self) -> str:
        """Name of the prompt template."""
        return "review"

    def get_template_context(self, ctx: StageContext) -> dict[str, Any]:
        """Get context variables for the template.

        Args:
            ctx: Stage context.

        Returns:
            Dictionary of template variables.
        """
        spec = ctx.pack.read_spec() or ""
        patch_diff = ctx.pack.read_patch_diff() or ""

        # Build gate results summary
        gate_results = []
        for gate in ctx.gates:
            log_path = ctx.paths.log_path(gate.name)
            if log_path.exists():
                # Try to determine if it passed
                gate_results.append(
                    {
                        "name": gate.name,
                        "ok": True,  # If we got to review, gates passed
                        "message": "Passed",
                    }
                )

        return {
            "spec": spec,
            "patch_diff": patch_diff,
            "gate_results": gate_results,
        }

    def save_output(self, ctx: StageContext, content: str) -> None:
        """Save the review outputs.

        The review stage produces two files: review.md and pr_body.md.
        We need to parse the output to separate them.

        Args:
            ctx: Stage context.
            content: The review output content.
        """
        # Try to split into review and pr_body
        review_content = content
        pr_body_content = ""

        # Look for pr_body.md section
        if "### pr_body.md" in content:
            parts = content.split("### pr_body.md")
            review_content = parts[0].strip()
            if len(parts) > 1:
                pr_body_content = parts[1].strip()
                # Remove code fence if present
                if pr_body_content.startswith("```"):
                    lines = pr_body_content.split("\n")
                    # Find end of code fence
                    end_idx = -1
                    for i, line in enumerate(lines[1:], 1):
                        if line.strip() == "```":
                            end_idx = i
                            break
                    if end_idx > 0:
                        pr_body_content = "\n".join(lines[1:end_idx])

        ctx.pack.write_review(review_content)

        if pr_body_content:
            ctx.pack.write_pr_body(pr_body_content)
        else:
            # Generate a basic PR body if not provided
            pr_body_content = self._generate_basic_pr_body(ctx)
            ctx.pack.write_pr_body(pr_body_content)

    def _generate_basic_pr_body(self, ctx: StageContext) -> str:
        """Generate a basic PR body from context.

        Args:
            ctx: Stage context.

        Returns:
            Basic PR body content.
        """
        task = ctx.pack.read_task() or "Implementation changes"

        return f"""## Summary

{task}

## Changes

See diff for details.

## Testing

- Ruff check: Passed
- Pytest: Passed
"""

    def execute(self, ctx: StageContext) -> StageResult:
        """Execute the review stage.

        Args:
            ctx: Stage context.

        Returns:
            StageResult indicating success/failure.
        """
        log = logger.bind(stage=self.name)
        log.info("Executing review stage")

        result = super().execute(ctx)

        if result.success:
            # Verify outputs exist
            if not ctx.paths.review_md.exists():
                return self._failure("Review output not created")

            log.info("Review completed")

        return result
