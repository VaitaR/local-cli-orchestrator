"""Map node executor for parallel iteration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import structlog

from orx.context.backlog import Backlog, WorkItem, WorkItemStatus
from orx.pipeline.definition import NodeDefinition, NodeType
from orx.pipeline.executors.base import ExecutionContext, NodeResult

logger = structlog.get_logger()


@dataclass
class ItemResult:
    """Result of executing item pipeline."""

    item_id: str
    success: bool
    attempts: int
    error: str | None = None


class MapNodeExecutor:
    """Executor for map nodes that iterate over collections.

    Executes a sub-pipeline for each item in a collection (e.g., backlog).
    Supports configurable concurrency.
    """

    def __init__(self):
        """Initialize the executor."""
        self._llm_apply_executor: Any = None
        self._gate_executor: Any = None

    def execute(
        self,
        node: NodeDefinition,
        context: dict[str, Any],
        exec_ctx: ExecutionContext,
    ) -> NodeResult:
        """Execute map node.

        Args:
            node: Node definition.
            context: Input context dictionary.
            exec_ctx: Execution context.

        Returns:
            NodeResult with implementation report.
        """
        log = logger.bind(node_id=node.id, node_type=node.type.value)
        log.info("Executing map node")

        # Get backlog
        backlog = context.get("backlog")
        if not backlog:
            return NodeResult(success=False, error="No backlog provided")

        if isinstance(backlog, str):
            backlog = Backlog.from_yaml(backlog)

        # Get concurrency
        concurrency = min(node.config.concurrency, len(backlog.items))
        log.info("Starting map execution", items=len(backlog.items), concurrency=concurrency)

        # Get item pipeline
        item_pipeline = node.config.item_pipeline
        if not item_pipeline:
            return NodeResult(success=False, error="No item_pipeline defined for map node")

        # Get max fix attempts from config
        max_attempts = exec_ctx.config.run.max_fix_attempts

        # Execute items
        results: list[ItemResult] = []

        if concurrency == 1:
            # Sequential execution
            results = self._execute_sequential(
                backlog, item_pipeline, context, exec_ctx, max_attempts
            )
        else:
            # Parallel execution
            results = self._execute_parallel(
                backlog, item_pipeline, context, exec_ctx, max_attempts, concurrency
            )

        # Save updated backlog
        exec_ctx.store.set("backlog", backlog, source_node=node.id)

        # Build report
        report = self._build_report(results, backlog)

        # Check for failures
        failed_count = sum(1 for r in results if not r.success)
        if failed_count > 0:
            return NodeResult(
                success=False,
                outputs={"implementation_report": report},
                error=f"{failed_count} items failed",
            )

        return NodeResult(
            success=True,
            outputs={"implementation_report": report},
        )

    def _execute_sequential(
        self,
        backlog: Backlog,
        item_pipeline: list[NodeDefinition],
        context: dict[str, Any],
        exec_ctx: ExecutionContext,
        max_attempts: int,
    ) -> list[ItemResult]:
        """Execute items sequentially.

        Args:
            backlog: Backlog with items.
            item_pipeline: Pipeline to run for each item.
            context: Base context.
            exec_ctx: Execution context.
            max_attempts: Maximum attempts per item.

        Returns:
            List of ItemResults.
        """
        results: list[ItemResult] = []

        while not backlog.all_done():
            item = backlog.get_next_todo()
            if not item:
                break

            result = self._process_item(
                item, item_pipeline, context, exec_ctx, max_attempts, backlog
            )
            results.append(result)

        return results

    def _execute_parallel(
        self,
        backlog: Backlog,
        item_pipeline: list[NodeDefinition],
        context: dict[str, Any],
        exec_ctx: ExecutionContext,
        max_attempts: int,
        concurrency: int,
    ) -> list[ItemResult]:
        """Execute items in parallel.

        Args:
            backlog: Backlog with items.
            item_pipeline: Pipeline to run for each item.
            context: Base context.
            exec_ctx: Execution context.
            max_attempts: Maximum attempts per item.
            concurrency: Number of parallel workers.

        Returns:
            List of ItemResults.
        """
        results: list[ItemResult] = []

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {}

            # Submit initial batch
            for item in backlog.items:
                if item.status == WorkItemStatus.TODO:
                    future = pool.submit(
                        self._process_item,
                        item,
                        item_pipeline,
                        context,
                        exec_ctx,
                        max_attempts,
                        backlog,
                    )
                    futures[future] = item.id

            # Collect results
            for future in as_completed(futures):
                item_id = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    logger.error("Item execution failed", item_id=item_id, error=str(e))
                    results.append(ItemResult(item_id=item_id, success=False, attempts=0, error=str(e)))

        return results

    def _process_item(
        self,
        item: WorkItem,
        item_pipeline: list[NodeDefinition],
        context: dict[str, Any],
        exec_ctx: ExecutionContext,
        max_attempts: int,
        backlog: Backlog,  # noqa: ARG002
    ) -> ItemResult:
        """Process a single work item.

        Args:
            item: Work item to process.
            item_pipeline: Pipeline to execute.
            context: Base context.
            exec_ctx: Execution context.
            max_attempts: Maximum attempts.
            backlog: Backlog for status updates.

        Returns:
            ItemResult.
        """
        log = logger.bind(item_id=item.id, title=item.title)
        log.info("Processing work item")

        item.mark_in_progress()

        for attempt in range(1, max_attempts + 1):
            item.increment_attempts()
            log.info("Attempt", attempt=attempt)

            # Build item context
            item_context = {
                **context,
                "current_item": item,
                "iteration": attempt,
            }

            # Execute item pipeline
            success = True
            error = None

            for node in item_pipeline:
                result = self._execute_item_node(node, item_context, exec_ctx, item, attempt)

                if not result.success:
                    success = False
                    error = result.error
                    break

                # Update context with outputs
                item_context.update(result.outputs)

            if success:
                item.mark_done()
                log.info("Item completed successfully")
                return ItemResult(item_id=item.id, success=True, attempts=attempt)

            log.warning("Attempt failed", error=error)

        # All attempts failed
        item.mark_failed(f"Failed after {max_attempts} attempts")
        return ItemResult(item_id=item.id, success=False, attempts=max_attempts, error=error)

    def _execute_item_node(
        self,
        node: NodeDefinition,
        context: dict[str, Any],
        exec_ctx: ExecutionContext,
        item: WorkItem,  # noqa: ARG002
        attempt: int,  # noqa: ARG002
    ) -> NodeResult:
        """Execute a single node in the item pipeline.

        Args:
            node: Node to execute.
            context: Context dictionary.
            exec_ctx: Execution context.
            item: Current work item.
            attempt: Current attempt number.

        Returns:
            NodeResult.
        """
        from orx.pipeline.executors.gate import GateNodeExecutor
        from orx.pipeline.executors.llm_apply import LLMApplyNodeExecutor

        if node.type == NodeType.LLM_APPLY:
            if self._llm_apply_executor is None:
                self._llm_apply_executor = LLMApplyNodeExecutor()
            return self._llm_apply_executor.execute(node, context, exec_ctx)

        elif node.type == NodeType.GATE:
            if self._gate_executor is None:
                self._gate_executor = GateNodeExecutor()
            return self._gate_executor.execute(node, context, exec_ctx)

        else:
            return NodeResult(success=False, error=f"Unsupported node type in item pipeline: {node.type}")

    def _build_report(self, results: list[ItemResult], backlog: Backlog) -> str:
        """Build implementation report.

        Args:
            results: List of item results.
            backlog: Backlog with item details.

        Returns:
            Markdown report string.
        """
        lines = ["# Implementation Report", ""]

        total = len(results)
        success = sum(1 for r in results if r.success)
        failed = total - success

        lines.append(f"**Total Items**: {total}")
        lines.append(f"**Successful**: {success}")
        lines.append(f"**Failed**: {failed}")
        lines.append("")

        if results:
            lines.append("## Item Results")
            lines.append("")

            for result in results:
                item = backlog.get_item(result.item_id)
                status = "✅" if result.success else "❌"
                title = item.title if item else result.item_id
                lines.append(f"- {status} **{result.item_id}**: {title}")
                lines.append(f"  - Attempts: {result.attempts}")
                if result.error:
                    lines.append(f"  - Error: {result.error}")
                lines.append("")

        return "\n".join(lines)
