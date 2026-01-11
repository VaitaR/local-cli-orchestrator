"""Pipeline runner - main execution engine."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from orx.executors.base import Executor
from orx.executors.router import ModelRouter
from orx.gates.base import Gate
from orx.metrics.schema import GateMetrics, StageMetrics, StageStatus, TokenUsage
from orx.metrics.writer import MetricsWriter
from orx.paths import RunPaths
from orx.pipeline.artifacts import ArtifactStore
from orx.pipeline.constants import DEFAULT_NODE_TIMEOUT
from orx.pipeline.context_builder import ContextBuilder
from orx.pipeline.definition import NodeDefinition, NodeType, PipelineDefinition
from orx.pipeline.executors.base import ExecutionContext, NodeResult
from orx.pipeline.executors.custom import CustomNodeExecutor
from orx.pipeline.executors.gate import GateNodeExecutor
from orx.pipeline.executors.llm_apply import LLMApplyNodeExecutor
from orx.pipeline.executors.llm_text import LLMTextNodeExecutor
from orx.pipeline.executors.map import MapNodeExecutor
from orx.pipeline.registry import PipelineRegistry
from orx.prompts.renderer import PromptRenderer
from orx.state import RunState, Stage
from orx.workspace.git_worktree import WorkspaceGitWorktree

if TYPE_CHECKING:
    from orx.config import OrxConfig

logger = structlog.get_logger()


@dataclass
class NodeMetrics:
    """Metrics for a single node execution."""

    node_id: str
    node_type: str
    duration_ms: int
    success: bool
    error: str | None = None
    outputs: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Result of pipeline execution."""

    success: bool
    completed_nodes: list[str] = field(default_factory=list)
    failed_node: str | None = None
    error: str | None = None
    node_metrics: list[NodeMetrics] = field(default_factory=list)
    total_duration_ms: int = 0
    review_changes_requested: bool = False  # True if review asked for changes

    def __bool__(self) -> bool:
        """Return success status."""
        return self.success


class PipelineRunner:
    """Main pipeline execution engine.

    Executes a pipeline definition by running each node in sequence,
    managing context flow between nodes.
    """

    def __init__(
        self,
        config: OrxConfig,
        paths: RunPaths,
        workspace: WorkspaceGitWorktree,
        executor: Executor,
        gates: list[Gate],
        renderer: PromptRenderer,
        state: RunState | None = None,
        router: ModelRouter | None = None,
        metrics_writer: MetricsWriter | None = None,
    ):
        """Initialize pipeline runner.

        Args:
            config: ORX configuration.
            paths: Run paths.
            workspace: Git worktree.
            executor: Default LLM executor.
            gates: Quality gates.
            renderer: Prompt renderer.
            state: Run state for persistence.
            router: Model router for stage-specific models.
            metrics_writer: Optional metrics writer for stage metrics.
        """
        self.config = config
        self.paths = paths
        self.workspace = workspace
        self.executor = executor
        self.gates = gates
        self.renderer = renderer
        self.state = state
        self.router = router
        self.metrics_writer = metrics_writer

        # Initialize artifact store
        self.store = ArtifactStore(paths)

        # Initialize context builder
        self.context_builder = ContextBuilder(self.store, workspace.worktree_path)

        # Node executors
        self._executors = {
            NodeType.LLM_TEXT: LLMTextNodeExecutor(),
            NodeType.LLM_APPLY: LLMApplyNodeExecutor(),
            NodeType.MAP: MapNodeExecutor(),
            NodeType.GATE: GateNodeExecutor(),
            NodeType.CUSTOM: CustomNodeExecutor(),
        }

    def run(
        self,
        pipeline: PipelineDefinition,
        task: str,
        resume_from: str | None = None,
    ) -> PipelineResult:
        """Run a pipeline.

        Args:
            pipeline: Pipeline definition to execute.
            task: Task description.
            resume_from: Node ID to resume from (for resumable runs).

        Returns:
            PipelineResult with execution status.
        """
        log = logger.bind(pipeline_id=pipeline.id, node_count=len(pipeline.nodes))
        log.info("Starting pipeline execution")

        start_time = time.perf_counter()

        # Store task
        self.store.set("task", task, source_node="input")

        # Extract default context
        self.context_builder.extract_default_context(pipeline.default_context)

        # Get nodes to execute
        nodes = pipeline.nodes
        if resume_from:
            # Find resume point
            resume_idx = next(
                (i for i, n in enumerate(nodes) if n.id == resume_from),
                None,
            )
            if resume_idx is not None:
                nodes = nodes[resume_idx:]
                log.info("Resuming from node", node_id=resume_from)

        # Execute nodes
        result = PipelineResult(success=True)

        for node in nodes:
            node_log = log.bind(node_id=node.id, node_type=node.type.value)
            node_log.info("Executing node")

            node_start = time.perf_counter()

            # Build context for this node
            context = self.context_builder.build_for_node(node)

            # Get executor for this node's stage
            executor = self._get_executor_for_node(node)

            # Build execution context
            exec_ctx = ExecutionContext(
                config=self.config,
                paths=self.paths,
                store=self.store,
                workspace=self.workspace,
                executor=executor,
                gates=self.gates,
                renderer=self.renderer,
                timeout_seconds=node.config.timeout_seconds or DEFAULT_NODE_TIMEOUT,
            )

            # Execute node
            try:
                node_result = self._execute_node(node, context, exec_ctx)
            except Exception as e:
                node_log.error("Node execution error", error=str(e))
                node_result = NodeResult(success=False, error=str(e))

            node_duration_ms = int((time.perf_counter() - node_start) * 1000)

            # Record metrics
            metrics = NodeMetrics(
                node_id=node.id,
                node_type=node.type.value,
                duration_ms=node_duration_ms,
                success=node_result.success,
                error=node_result.error,
                outputs=list(node_result.outputs.keys()),
                extra=node_result.metrics,
            )
            result.node_metrics.append(metrics)

            # Write stage metrics if writer available
            if self.metrics_writer:
                try:
                    node_start_ts = datetime.fromtimestamp(node_start, tz=UTC)
                    stage_metrics = self._convert_node_metrics(metrics, node_start_ts)
                    self.metrics_writer.write_stage(stage_metrics)
                except Exception as e:
                    node_log.warning("Failed to write stage metrics", error=str(e))

            if node_result.success:
                result.completed_nodes.append(node.id)

                # Store outputs
                for key, value in node_result.outputs.items():
                    self.store.set(key, value, source_node=node.id)

                # Update state
                if self.state:
                    stage_name = self._map_node_to_stage(node.id)
                    if stage_name:
                        self.state.mark_stage_completed(stage_name)

                # Handle review loop: if review requests changes, skip ship and rewind to implement
                if node.id == "review" and node_result.metadata.get("verdict") == "changes_requested":
                    node_log.info("Review requested changes - skipping ship stage")
                    # Don't execute ship node
                    # In fast_fix pipeline, this means we stop here (no loop implemented yet)
                    # TODO: implement proper review loop with backlog item creation
                    result.success = True
                    result.review_changes_requested = True
                    break

                node_log.info("Node completed", duration_ms=node_duration_ms)

            else:
                result.success = False
                result.failed_node = node.id
                result.error = node_result.error
                node_log.error(
                    "Node failed",
                    error=node_result.error,
                    duration_ms=node_duration_ms,
                )
                break

        result.total_duration_ms = int((time.perf_counter() - start_time) * 1000)

        log.info(
            "Pipeline execution completed",
            success=result.success,
            completed=len(result.completed_nodes),
            duration_ms=result.total_duration_ms,
        )

        return result

    def _execute_node(
        self,
        node: NodeDefinition,
        context: dict[str, Any],
        exec_ctx: ExecutionContext,
    ) -> NodeResult:
        """Execute a single node.

        Args:
            node: Node definition.
            context: Input context.
            exec_ctx: Execution context.

        Returns:
            NodeResult.
        """
        executor = self._executors.get(node.type)
        if not executor:
            return NodeResult(
                success=False, error=f"No executor for node type: {node.type}"
            )

        return executor.execute(node, context, exec_ctx)

    def _get_executor_for_node(self, node: NodeDefinition) -> Executor:
        """Get the appropriate LLM executor for a node.

        Uses model router if available and node has stage mapping.

        Args:
            node: Node definition.

        Returns:
            LLM executor.
        """
        if not self.router:
            return self.executor

        # Map node to stage name for routing
        stage = self._map_node_to_stage(node.id)
        if not stage:
            return self.executor

        executor, _selector = self.router.get_executor_for_stage(stage.value)
        return executor

    def _map_node_to_stage(self, node_id: str) -> Stage | None:
        """Map node ID to stage name.

        Args:
            node_id: Node identifier.

        Returns:
            Stage or None.
        """
        mapping = {
            "plan": Stage.PLAN,
            "spec": Stage.SPEC,
            "decompose": Stage.DECOMPOSE,
            "implement": Stage.IMPLEMENT_ITEM,
            "implement_direct": Stage.IMPLEMENT_ITEM,
            "verify": Stage.VERIFY,
            "review": Stage.REVIEW,
            "ship": Stage.SHIP,
            "knowledge_update": Stage.KNOWLEDGE_UPDATE,
        }
        return mapping.get(node_id)

    def _convert_node_metrics(
        self,
        node_metrics: NodeMetrics,
        start_ts: datetime,
    ) -> StageMetrics:
        """Convert NodeMetrics to StageMetrics schema.

        Handles missing or malformed optional fields gracefully:
        - Missing token data: logged as warning, defaults to None
        - Malformed token data: logged as error, defaults to None
        - Missing gate data: logged as warning, defaults to empty list
        - Malformed gate data: logged as error, skipped (doesn't crash)

        Args:
            node_metrics: Node execution metrics.
            start_ts: Start timestamp for the node.

        Returns:
            StageMetrics instance.
        """
        log = logger.bind(node_id=node_metrics.node_id)
        log.debug("Converting node metrics", duration_ms=node_metrics.duration_ms)

        # Map node_id to stage name
        stage = node_metrics.node_id

        # Map success to status
        status = StageStatus.SUCCESS if node_metrics.success else StageStatus.FAIL

        # Extract gates from extra with error handling
        gates: list[GateMetrics] = []
        if "gates" in node_metrics.extra:
            gates_data = node_metrics.extra.get("gates", [])
            if not isinstance(gates_data, list):
                log.warning(
                    "Gates field is not a list", gates_type=type(gates_data).__name__
                )
            else:
                for gate_data in gates_data:
                    if isinstance(gate_data, dict):
                        try:
                            gates.append(GateMetrics(**gate_data))
                        except Exception as e:
                            log.error(
                                "Failed to parse gate metrics",
                                gate_data=gate_data,
                                error=str(e),
                            )
                    else:
                        log.warning(
                            "Gate item is not a dict",
                            gate_type=type(gate_data).__name__,
                        )

        # Extract tokens from extra with error handling
        tokens: TokenUsage | None = None
        if "tokens" in node_metrics.extra:
            token_data = node_metrics.extra["tokens"]
            if token_data is None:
                log.debug("Tokens field is None")
            elif not isinstance(token_data, dict):
                log.warning(
                    "Tokens field is not a dict", tokens_type=type(token_data).__name__
                )
            else:
                try:
                    tokens = TokenUsage(**token_data)
                    log.debug("Parsed token usage", tokens_total=tokens.total)
                except Exception as e:
                    log.error(
                        "Failed to parse token usage",
                        token_data=token_data,
                        error=str(e),
                    )

        log.debug(
            "Metrics conversion complete",
            status=status.value,
            gate_count=len(gates),
            has_tokens=tokens is not None,
        )

        return StageMetrics(
            run_id=self.paths.run_id,
            stage=stage,
            start_ts=start_ts.isoformat(),
            end_ts=(start_ts.replace(microsecond=0)).isoformat(),
            duration_ms=node_metrics.duration_ms,
            status=status,
            failure_message=node_metrics.error,
            tokens=tokens,
            gates=gates,
        )

    @classmethod
    def from_config(
        cls,
        config: OrxConfig,
        paths: RunPaths,
        workspace: WorkspaceGitWorktree,
        gates: list[Gate],
        state: RunState | None = None,
        metrics_writer: MetricsWriter | None = None,
    ) -> PipelineRunner:
        """Create a pipeline runner from configuration.

        Args:
            config: ORX configuration.
            paths: Run paths.
            workspace: Git worktree.
            gates: Quality gates.
            state: Run state.
            metrics_writer: Optional metrics writer for stage metrics.

        Returns:
            Configured PipelineRunner.
        """
        from orx.executors.router import ModelRouter
        from orx.prompts.renderer import PromptRenderer

        # Create router and get default executor
        router = ModelRouter.from_config(config, paths)
        executor = router.get_primary_executor()

        # Create renderer
        renderer = PromptRenderer()

        return cls(
            config=config,
            paths=paths,
            workspace=workspace,
            executor=executor,
            gates=gates,
            renderer=renderer,
            state=state,
            router=router,
            metrics_writer=metrics_writer,
        )


def run_pipeline(
    pipeline_id: str,
    task: str,
    config: OrxConfig,
    paths: RunPaths,
    workspace: WorkspaceGitWorktree,
    gates: list[Gate],
    state: RunState | None = None,
    registry: PipelineRegistry | None = None,
) -> PipelineResult:
    """Convenience function to run a pipeline by ID.

    Args:
        pipeline_id: Pipeline identifier.
        task: Task description.
        config: ORX configuration.
        paths: Run paths.
        workspace: Git worktree.
        gates: Quality gates.
        state: Run state.
        registry: Pipeline registry.

    Returns:
        PipelineResult.

    Raises:
        ValueError: If pipeline not found.
    """
    if registry is None:
        registry = PipelineRegistry.load(paths)

    pipeline = registry.get(pipeline_id)
    if not pipeline:
        raise ValueError(f"Pipeline not found: {pipeline_id}")

    runner = PipelineRunner.from_config(
        config=config,
        paths=paths,
        workspace=workspace,
        gates=gates,
        state=state,
    )

    return runner.run(pipeline, task)
