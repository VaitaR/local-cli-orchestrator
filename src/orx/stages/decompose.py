"""Decompose stage implementation."""

from __future__ import annotations

from typing import Any

import structlog

from orx.context.backlog import Backlog
from orx.context.sections import extract_architecture_overview, extract_file_tree
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

        run_config = ctx.config.get("run", {}) if ctx.config else {}
        max_items = run_config.get("max_backlog_items", 4)

        # Extract file tree and architecture for better files_hint suggestions
        worktree = ctx.workspace.worktree_path
        file_tree = extract_file_tree(worktree, max_depth=3)
        architecture = extract_architecture_overview(worktree)

        return {
            "spec": spec,
            "plan": plan,
            "run_id": ctx.paths.run_id,
            "max_items": max_items,
            "file_tree": file_tree,
            "architecture": architecture,
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

        raw_output = ctx.paths.backlog_yaml.read_text()

        # Validate the backlog with robust extraction, retry once on failure
        try:
            # First attempt: try with strict=False (all strategies)
            backlog = Backlog.from_yaml(raw_output, strict=False)
            log.info("Backlog parsed successfully with robust extraction")
        except Exception as e:
            log.warning(
                "Backlog YAML invalid after extraction, attempting auto-fix",
                error=str(e),
                raw_preview=raw_output[:500] if len(raw_output) > 500 else raw_output,
            )
            fix_result = self._attempt_fix(ctx, error=str(e), invalid_output=raw_output)
            if not fix_result.success:
                return fix_result
            backlog = fix_result.data["backlog"] if fix_result.data else None
            if backlog is None:
                return self._failure("Auto-fix did not return a backlog")

        return self._validate_backlog(ctx, backlog)

    def _attempt_fix(
        self, ctx: StageContext, *, error: str, invalid_output: str
    ) -> StageResult:
        """Attempt a single auto-fix pass for invalid backlog YAML."""
        log = logger.bind(stage=self.name)
        run_config = ctx.config.get("run", {}) if ctx.config else {}
        max_items = run_config.get("max_backlog_items", 4)
        prompt_path = self._render_and_save_prompt(
            ctx,
            "decompose_fix",
            error=error,
            invalid_output=invalid_output,
            run_id=ctx.paths.run_id,
            max_items=max_items,
        )

        stdout_path, stderr_path = ctx.paths.agent_log_paths(f"{self.name}_fix")
        from orx.executors.base import LogPaths

        logs = LogPaths(stdout=stdout_path, stderr=stderr_path)
        out_path = ctx.paths.context_dir / "decompose_fix_output.md"

        if ctx.events:
            ctx.events.log(
                "executor_start",
                stage=self.name,
                mode="text",
                prompt=str(prompt_path),
                attempt="fix",
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
                attempt="fix",
            )

        if result.failed:
            log.error("Auto-fix executor failed", error=result.error_message)
            return self._failure(
                f"Executor failed during auto-fix: {result.error_message}"
            )

        if not out_path.exists():
            log.error("Auto-fix produced no output")
            return self._failure("Auto-fix produced no output")

        content = out_path.read_text()

        # Check for explicit error marker
        if content.strip() == "ERROR: CANNOT_FIX":
            log.error("Auto-fix explicitly indicated it cannot fix the YAML")
            return self._failure(
                "Auto-fix could not produce valid YAML. "
                "The model explicitly indicated it cannot fix the error. "
                f"Original error: {error}"
            )

        # Write the fixed content
        ctx.paths.backlog_yaml.write_text(content)

        # Try to parse with robust extraction
        try:
            backlog = Backlog.from_yaml(content, strict=False)
            log.info("Auto-fix produced valid backlog with robust extraction")
        except Exception as e:
            log.error(
                "Auto-fix produced invalid YAML even after robust extraction",
                error=str(e),
                content_preview=content[:500] if len(content) > 500 else content,
            )
            return self._failure(f"Invalid backlog YAML after auto-fix: {e}")

        return self._success(
            "Auto-fix produced valid backlog", data={"backlog": backlog}
        )

    def _validate_backlog(self, ctx: StageContext, backlog: Backlog) -> StageResult:
        """Validate the backlog structure, dependencies, and cycles."""
        log = logger.bind(stage=self.name)

        errors = backlog.validate_dependencies()
        if errors:
            log.error("Backlog dependency errors", errors=errors)
            return self._failure(f"Invalid backlog: {'; '.join(errors)}")

        cycles = backlog.detect_cycles()
        if cycles:
            log.error("Backlog has cycles", cycles=cycles)
            return self._failure(f"Backlog has cycles: {'; '.join(cycles)}")

        run_config = ctx.config.get("run", {}) if ctx.config else {}
        max_items = run_config.get("max_backlog_items", 0)
        coalesce_enabled = run_config.get("coalesce_backlog_items", True)
        original_count = len(backlog.items)
        if coalesce_enabled and max_items:
            merged = backlog.coalesce(max_items)
            if merged is not backlog:
                backlog = merged
                errors = backlog.validate_dependencies()
                if errors:
                    log.error("Merged backlog dependency errors", errors=errors)
                    return self._failure(f"Invalid merged backlog: {'; '.join(errors)}")
                cycles = backlog.detect_cycles()
                if cycles:
                    log.error("Merged backlog has cycles", cycles=cycles)
                    return self._failure(
                        f"Merged backlog has cycles: {'; '.join(cycles)}"
                    )
                ctx.paths.backlog_yaml.write_text(backlog.to_yaml())
                log.info(
                    "Backlog coalesced",
                    original_count=original_count,
                    new_count=len(backlog.items),
                    max_items=max_items,
                )

        log.info("Backlog validated", item_count=len(backlog.items))
        return self._success(
            f"Decomposed into {len(backlog.items)} work items",
            data={"item_count": len(backlog.items)},
        )
