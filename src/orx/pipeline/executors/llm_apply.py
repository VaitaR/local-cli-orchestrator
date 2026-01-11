"""LLM apply (filesystem changes) node executor."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from orx.context.snippets import (
    build_file_snippets,
    compact_text,
    extract_spec_highlights,
)
from orx.executors.base import LogPaths
from orx.pipeline.definition import NodeDefinition
from orx.pipeline.executors.base import ExecutionContext, NodeResult

if TYPE_CHECKING:
    from orx.context.backlog import WorkItem

logger = structlog.get_logger()


class LLMApplyNodeExecutor:
    """Executor for LLM filesystem apply nodes.

    Renders a prompt and calls the LLM to apply changes to the
    filesystem (e.g., implement code changes).
    """

    def execute(
        self,
        node: NodeDefinition,
        context: dict[str, Any],
        exec_ctx: ExecutionContext,
    ) -> NodeResult:
        """Execute apply node.

        Args:
            node: Node definition.
            context: Input context dictionary.
            exec_ctx: Execution context.

        Returns:
            NodeResult with patch diff.
        """
        log = logger.bind(node_id=node.id, node_type=node.type.value)
        log.info("Executing LLM apply node")

        if not node.template:
            return NodeResult(success=False, error=f"Node {node.id} has no template")

        try:
            # Get current item for item-specific execution
            current_item: WorkItem | None = context.get("current_item")
            iteration = context.get("iteration", 1)

            # Render prompt
            prompt_path = self._render_prompt(node, context, exec_ctx, current_item)

            # Get log paths
            item_id = current_item.id if current_item else None
            stdout_path, stderr_path = exec_ctx.paths.agent_log_paths(
                node.id, item_id=item_id, iteration=iteration
            )
            logs = LogPaths(stdout=stdout_path, stderr=stderr_path)

            # Get timeout
            timeout = node.config.timeout_seconds or exec_ctx.timeout_seconds

            # Call LLM
            result = exec_ctx.executor.run_apply(
                cwd=exec_ctx.workspace.worktree_path,
                prompt_path=prompt_path,
                logs=logs,
                timeout=timeout,
            )

            if result.failed:
                log.error("LLM apply failed", error=result.error_message)
                return NodeResult(success=False, error=f"LLM apply failed: {result.error_message}")

            # Capture diff
            exec_ctx.workspace.diff_to(exec_ctx.paths.patch_diff)

            # Check for empty diff
            if exec_ctx.workspace.diff_empty():
                log.warning("No changes produced")
                return NodeResult(success=False, error="No changes produced")

            # Read diff for output
            patch_diff = ""
            if exec_ctx.paths.patch_diff.exists():
                patch_diff = exec_ctx.paths.patch_diff.read_text()

            # Build outputs
            outputs: dict[str, Any] = {}
            if node.outputs:
                output_key = node.outputs[0]
                outputs[output_key] = patch_diff

            log.info("LLM apply node completed")
            return NodeResult(success=True, outputs=outputs)

        except Exception as e:
            log.error("Node execution failed", error=str(e))
            return NodeResult(success=False, error=str(e))

    def _render_prompt(
        self,
        node: NodeDefinition,
        context: dict[str, Any],
        exec_ctx: ExecutionContext,
        item: WorkItem | None = None,
    ) -> Path:
        """Render the prompt template.

        Args:
            node: Node definition.
            context: Input context.
            exec_ctx: Execution context.
            item: Current work item.

        Returns:
            Path to rendered prompt file.
        """
        # Build template context
        template_context = self._build_template_context(context, exec_ctx, item)

        # Determine template name
        template_name = node.template.replace(".md", "") if node.template else node.id

        # Render to prompts directory
        prompt_path = exec_ctx.paths.prompt_path(template_name)
        exec_ctx.renderer.render_to_file(template_name, prompt_path, **template_context)

        # Copy to worktree
        worktree_prompt = exec_ctx.paths.copy_prompt_to_worktree(template_name)

        return worktree_prompt

    def _build_template_context(
        self,
        context: dict[str, Any],
        exec_ctx: ExecutionContext,
        item: WorkItem | None = None,
    ) -> dict[str, Any]:
        """Build template context for implement prompt.

        Args:
            context: Input context.
            exec_ctx: Execution context.
            item: Current work item.

        Returns:
            Template variable dictionary.
        """
        template_ctx: dict[str, Any] = {}

        # Task summary
        task = context.get("task", "")
        template_ctx["task_summary"] = compact_text(task, max_lines=40)

        # Spec highlights
        spec = context.get("spec", "")
        if hasattr(spec, "model_dump"):
            spec = str(spec)
        template_ctx["spec_highlights"] = extract_spec_highlights(spec, max_lines=120)

        # Work item context
        if item:
            template_ctx["item_id"] = item.id
            template_ctx["item_title"] = item.title
            template_ctx["item_objective"] = item.objective
            template_ctx["acceptance"] = item.acceptance
            template_ctx["files_hint"] = item.files_hint

            # Build file snippets
            snippets = build_file_snippets(
                worktree=exec_ctx.workspace.worktree_path,
                files=item.files_hint,
                max_lines=120,
                max_files=8,
            )
            template_ctx["file_snippets"] = snippets

        # Pass through context items
        if "repo_context" in context or "tooling_snapshot" in context:
            template_ctx["repo_context"] = context.get("tooling_snapshot", context.get("repo_context", ""))

        if "verify_commands" in context:
            template_ctx["verify_commands"] = context["verify_commands"]

        if "agents_context" in context:
            template_ctx["agents_context"] = context["agents_context"]

        return template_ctx
