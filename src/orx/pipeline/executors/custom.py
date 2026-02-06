"""Custom node executor for Python callables."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any, cast

import structlog

from orx.pipeline.definition import NodeDefinition
from orx.pipeline.executors.base import ExecutionContext, NodeResult

logger = structlog.get_logger()


class CustomNodeExecutor:
    """Executor for custom Python callable nodes.

    Allows executing arbitrary Python functions as pipeline nodes.
    """

    def execute(
        self,
        node: NodeDefinition,
        context: dict[str, Any],
        exec_ctx: ExecutionContext,
    ) -> NodeResult:
        """Execute custom node.

        Args:
            node: Node definition.
            context: Input context dictionary.
            exec_ctx: Execution context.

        Returns:
            NodeResult from the callable.
        """
        log = logger.bind(node_id=node.id, node_type=node.type.value)
        log.info("Executing custom node")

        # Get callable path or use built-in
        callable_path = node.config.callable_path

        if not callable_path:
            # Check for built-in handlers
            handler = self._get_builtin_handler(node.id)
            if handler:
                return handler(node, context, exec_ctx)
            return NodeResult(
                success=False, error=f"No callable_path for custom node: {node.id}"
            )

        try:
            # Import and call the function
            func = self._import_callable(callable_path)
            result = func(node, context, exec_ctx)

            if isinstance(result, NodeResult):
                return result

            # Wrap simple return values
            if isinstance(result, dict):
                return NodeResult(success=True, outputs=result)
            elif isinstance(result, bool):
                return NodeResult(success=result)
            else:
                return NodeResult(success=True, outputs={"result": result})

        except Exception as e:
            log.error("Custom node failed", error=str(e))
            return NodeResult(success=False, error=str(e))

    def _import_callable(
        self, path: str
    ) -> Callable[[NodeDefinition, dict[str, Any], ExecutionContext], NodeResult]:
        """Import a callable from a dotted path.

        Args:
            path: Dotted path like 'module.submodule:function'.

        Returns:
            The imported callable.

        Raises:
            ImportError: If import fails.
            AttributeError: If function not found.
        """
        if ":" in path:
            module_path, func_name = path.rsplit(":", 1)
        else:
            module_path, func_name = path.rsplit(".", 1)

        module = importlib.import_module(module_path)
        func = getattr(module, func_name)
        if not callable(func):
            msg = f"Imported object is not callable: {path}"
            raise TypeError(msg)
        return cast(
            Callable[[NodeDefinition, dict[str, Any], ExecutionContext], NodeResult],
            func,
        )

    def _get_builtin_handler(
        self, node_id: str
    ) -> (
        Callable[[NodeDefinition, dict[str, Any], ExecutionContext], NodeResult] | None
    ):
        """Get a built-in handler for known node IDs.

        Args:
            node_id: Node identifier.

        Returns:
            Handler function or None.
        """
        handlers = {
            "ship": ship_node,
            "knowledge_update": knowledge_update_node,
        }
        return handlers.get(node_id)


# Built-in custom node handlers


def ship_node(
    node: NodeDefinition,
    context: dict[str, Any],
    exec_ctx: ExecutionContext,
) -> NodeResult:
    """Ship node: commit changes and optionally create PR.

    Args:
        node: Node definition.
        context: Input context (review, patch_diff).
        exec_ctx: Execution context.

    Returns:
        NodeResult with pr_body.
    """
    log = logger.bind(node_id=node.id)
    log.info("Executing ship node")

    try:
        # Check if there are changes to commit
        if exec_ctx.workspace.diff_empty():
            log.info("No changes to ship")
            return NodeResult(
                success=True, outputs={"pr_body": "No changes to commit."}
            )

        # Get review for PR body
        review = context.get("review", "")

        # Build PR body
        pr_body = _build_pr_body(review, exec_ctx)

        # Commit changes
        run_id = exec_ctx.paths.run_id
        commit_msg = f"feat: orx implementation [{run_id}]"

        if exec_ctx.config.git.auto_commit:
            exec_ctx.workspace.commit_all(commit_msg)
            log.info("Changes committed")

            # Push if configured
            if exec_ctx.config.git.auto_push:
                branch_name = f"orx/{exec_ctx.paths.run_id}"
                exec_ctx.workspace.push(exec_ctx.config.git.remote, branch_name)
                log.info("Changes pushed")

        # Save PR body
        exec_ctx.store.set("pr_body", pr_body, source_node=node.id)

        return NodeResult(success=True, outputs={"pr_body": pr_body})

    except Exception as e:
        log.error("Ship failed", error=str(e))
        return NodeResult(success=False, error=str(e))


def _build_pr_body(review: str, exec_ctx: ExecutionContext) -> str:
    """Build PR body from review and run info.

    Args:
        review: Review content.
        exec_ctx: Execution context.

    Returns:
        Formatted PR body.
    """
    lines = [
        "## Summary",
        "",
        f"Automated implementation by orx (run: `{exec_ctx.paths.run_id}`)",
        "",
    ]

    if review:
        lines.extend(
            [
                "## Review",
                "",
                review,
                "",
            ]
        )

    # Add diff stats if available
    if exec_ctx.paths.patch_diff.exists():
        diff = exec_ctx.paths.patch_diff.read_text()
        added = diff.count("\n+") - diff.count("\n+++")
        removed = diff.count("\n-") - diff.count("\n---")
        lines.extend(
            [
                "## Changes",
                "",
                f"- Lines added: {added}",
                f"- Lines removed: {removed}",
                "",
            ]
        )

    return "\n".join(lines)


def knowledge_update_node(
    node: NodeDefinition,
    context: dict[str, Any],  # noqa: ARG001
    exec_ctx: ExecutionContext,
) -> NodeResult:
    """Knowledge update node: update AGENTS.md and ARCHITECTURE.md.

    Args:
        node: Node definition.
        context: Input context.
        exec_ctx: Execution context.

    Returns:
        NodeResult.
    """
    log = logger.bind(node_id=node.id)
    log.info("Executing knowledge update node")

    # Knowledge update is non-fatal
    try:
        from orx.config import KnowledgeConfig
        from orx.context.pack import ContextPack
        from orx.knowledge.evidence import EvidenceCollector
        from orx.knowledge.updater import KnowledgeUpdater

        knowledge_cfg_raw = exec_ctx.config.model_dump().get("knowledge", {})
        knowledge_cfg = KnowledgeConfig.model_validate(knowledge_cfg_raw)
        if not knowledge_cfg.enabled or knowledge_cfg.mode == "off":
            return NodeResult(success=True, outputs={"knowledge_update": "skipped"})

        repo_root = exec_ctx.workspace.worktree_path.parent.parent
        pack = ContextPack(exec_ctx.paths)
        collector = EvidenceCollector(
            paths=exec_ctx.paths,
            pack=pack,
            repo_root=repo_root,
        )
        evidence = collector.collect()

        updater = KnowledgeUpdater(
            config=knowledge_cfg,
            paths=exec_ctx.paths,
            executor=exec_ctx.executor,
            repo_root=repo_root,
        )
        result = updater.run(evidence)

        status = "updated" if (result.agents_updated or result.arch_updated) else "noop"
        return NodeResult(success=True, outputs={"knowledge_update": status})

    except Exception as e:
        log.warning("Knowledge update failed (non-fatal)", error=str(e))
        return NodeResult(success=True)  # Non-fatal
