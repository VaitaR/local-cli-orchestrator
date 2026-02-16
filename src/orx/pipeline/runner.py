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
from orx.infra.command import CommandRunner
from orx.metrics.schema import GateMetrics, StageMetrics, StageStatus, TokenUsage
from orx.metrics.writer import MetricsWriter
from orx.observability.runtime import RunObservability
from orx.paths import RunPaths
from orx.pipeline.artifacts import ArtifactStore
from orx.pipeline.constants import DEFAULT_NODE_TIMEOUT
from orx.pipeline.context_builder import ContextBuilder
from orx.pipeline.definition import NodeDefinition, NodeType, PipelineDefinition
from orx.pipeline.executors.base import ExecutionContext, NodeExecutor, NodeResult
from orx.pipeline.executors.custom import CustomNodeExecutor
from orx.pipeline.executors.gate import GateNodeExecutor
from orx.pipeline.executors.llm_apply import LLMApplyNodeExecutor
from orx.pipeline.executors.llm_text import LLMTextNodeExecutor
from orx.pipeline.executors.map import MapNodeExecutor
from orx.pipeline.registry import PipelineRegistry
from orx.prompts.renderer import PromptRenderer
from orx.state import Stage, StateManager
from orx.workspace.git_worktree import WorkspaceGitWorktree

if TYPE_CHECKING:
    from orx.config import ModelSelector, OrxConfig

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
    fix_attempts: int = 0  # Number of times implement was retried after verify failure

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
        state: StateManager | None = None,
        router: ModelRouter | None = None,
        metrics_writer: MetricsWriter | None = None,
        observability: RunObservability | None = None,
        cmd: CommandRunner | None = None,
    ) -> None:
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
            observability: Optional run observability runtime.
            cmd: Shared command runner for command context propagation.
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
        self.observability = observability
        self.cmd = cmd or CommandRunner(dry_run=False)

        # Initialize artifact store
        self.store = ArtifactStore(paths)

        # Initialize context builder
        self.context_builder = ContextBuilder(self.store, workspace.worktree_path)

        # Node executors
        self._executors: dict[NodeType, NodeExecutor] = {
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

            node_start_perf = time.perf_counter()
            node_start_ts = datetime.now(UTC)  # Wall-clock timestamp for metrics

            # Build context for this node
            context = self.context_builder.build_for_node(node)

            # Get executor and model selector for this node's stage
            executor, model_selector = self._get_executor_for_node(node)
            node_started = time.perf_counter()
            if self.observability:
                self.observability.stage_start(
                    stage=node.id,
                    attempt=1,
                    executor=executor.name,
                    model=model_selector.model if model_selector else None,
                )

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
                model_selector=model_selector,
                observability=self.observability,
            )

            # Execute node
            try:
                with self.cmd.command_context(stage=node.id):
                    node_result = self._execute_node(node, context, exec_ctx)
            except Exception as e:
                node_log.error("Node execution error", error=str(e))
                node_result = NodeResult(success=False, error=str(e))

            node_duration_ms = int((time.perf_counter() - node_start_perf) * 1000)

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
            if self.metrics_writer:
                try:
                    stage_metrics = self._convert_node_metrics(metrics, node_start_ts)
                    self.metrics_writer.write_stage(stage_metrics)
                except Exception as e:
                    node_log.warning("Failed to write stage metrics", error=str(e))
            if self.observability:
                self.observability.stage_end(
                    stage=node.id,
                    status="success" if node_result.success else "failure",
                    message=node_result.error,
                    duration_ms=int((time.perf_counter() - node_started) * 1000),
                )

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
                if (
                    node.id == "review"
                    and node_result.metadata.get("verdict") == "changes_requested"
                ):
                    node_log.info("Review requested changes - skipping ship stage")
                    # Don't execute ship node
                    # In fast_fix pipeline, this means we stop here (no loop implemented yet)
                    # TODO: implement proper review loop with backlog item creation
                    result.success = True
                    result.review_changes_requested = True
                    break

                # Handle reproduce stage validation (Fail-to-Pass)
                if node.id == "reproduce":
                    reproduce_verification = self._verify_reproduce_stage(node, context, exec_ctx)
                    if not reproduce_verification.success:
                        result.success = False
                        result.failed_node = node.id
                        result.error = reproduce_verification.error
                        node_log.error(
                            "Reproduction verification failed",
                            error=reproduce_verification.error,
                        )
                        break
                    else:
                        node_log.info("Reproduction verification successful (test failed as expected)")

                node_log.info("Node completed", duration_ms=node_duration_ms)

            else:
                # Handle verify failures: try to retry implement with error feedback
                if node.id == "verify" and self._should_retry_implement(result, nodes):
                    node_log.info(
                        "Verify gate failed - attempting to fix via implement retry",
                        error=node_result.error,
                        attempt=result.fix_attempts + 1,
                    )

                    # Find implement node to retry
                    implement_node = next(
                        (n for n in nodes if n.id in ("implement", "implement_direct")),
                        None,
                    )

                    if implement_node:
                        result.fix_attempts += 1

                        # Add error feedback to context for implement
                        error_context = {
                            "error_logs": node_result.error or "Verification failed",
                            "fix_attempt": result.fix_attempts,
                        }
                        self.store.set(
                            "verify_errors", error_context, source_node="verify"
                        )

                        # Rebuild context with error feedback
                        context = self.context_builder.build_for_node(implement_node)

                        # Get executor and retry implement
                        executor, model_selector = self._get_executor_for_node(
                            implement_node
                        )
                        retry_started = time.perf_counter()
                        if self.observability:
                            self.observability.stage_start(
                                stage=implement_node.id,
                                attempt=result.fix_attempts + 1,
                                executor=executor.name,
                                model=model_selector.model if model_selector else None,
                            )
                        exec_ctx = ExecutionContext(
                            config=self.config,
                            paths=self.paths,
                            store=self.store,
                            workspace=self.workspace,
                            executor=executor,
                            gates=self.gates,
                            renderer=self.renderer,
                            timeout_seconds=implement_node.config.timeout_seconds
                            or DEFAULT_NODE_TIMEOUT,
                            model_selector=model_selector,
                            observability=self.observability,
                        )

                        try:
                            with self.cmd.command_context(
                                stage=implement_node.id,
                                attempt=str(result.fix_attempts + 1),
                            ):
                                node_result = self._execute_node(
                                    implement_node, context, exec_ctx
                                )
                            if self.observability:
                                self.observability.stage_end(
                                    stage=implement_node.id,
                                    status="success"
                                    if node_result.success
                                    else "failure",
                                    message=node_result.error,
                                    duration_ms=int(
                                        (time.perf_counter() - retry_started) * 1000
                                    ),
                                )

                            # If implement succeeds, we need to re-run verify on the new changes
                            if node_result.success:
                                result.completed_nodes = [
                                    node_id
                                    for node_id in result.completed_nodes
                                    if node_id not in ("implement", "implement_direct")
                                ]
                                result.completed_nodes.append(implement_node.id)

                                # Store outputs
                                for key, value in node_result.outputs.items():
                                    self.store.set(
                                        key, value, source_node=implement_node.id
                                    )

                                node_log.info(
                                    "Implement retry successful - re-running verify gate",
                                    fix_attempt=result.fix_attempts,
                                )

                                # Re-run verify on the new changes by continuing to next iteration
                                # (which will be the verify node again)
                                # NOTE: We don't skip verify - we need to confirm the fix actually works
                                continue
                            else:
                                node_log.error(
                                    "Implement retry failed",
                                    error=node_result.error,
                                    fix_attempt=result.fix_attempts,
                                )
                        except Exception as e:
                            node_log.error("Implement retry error", error=str(e))
                            if self.observability:
                                self.observability.stage_end(
                                    stage=implement_node.id,
                                    status="failure",
                                    message=str(e),
                                    duration_ms=int(
                                        (time.perf_counter() - retry_started) * 1000
                                    ),
                                )

                # Standard failure handling
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

    def _get_executor_for_node(
        self, node: NodeDefinition
    ) -> tuple[Executor, ModelSelector | None]:
        """Get the appropriate LLM executor for a node.

        Uses model router if available and node has stage mapping.

        Args:
            node: Node definition.

        Returns:
            LLM executor.
        """
        if not self.router:
            return self.executor, None

        # Map node to stage name for routing
        stage = self._map_node_to_stage(node.id)
        if not stage:
            return self.executor, None

        executor, selector = self.router.get_executor_for_stage(stage.value)
        return executor, selector

    def _convert_node_metrics(
        self,
        node_metrics: NodeMetrics,
        start_ts: datetime,
    ) -> StageMetrics:
        """Convert NodeMetrics to StageMetrics schema."""
        log = logger.bind(node_id=node_metrics.node_id)
        log.debug("Converting node metrics", duration_ms=node_metrics.duration_ms)

        stage = node_metrics.node_id
        status = StageStatus.SUCCESS if node_metrics.success else StageStatus.FAIL

        gates: list[GateMetrics] = []
        if "gates" in node_metrics.extra:
            gates_data = node_metrics.extra.get("gates", [])
            if isinstance(gates_data, list):
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

        tokens: TokenUsage | None = None
        if "tokens" in node_metrics.extra:
            token_data = node_metrics.extra["tokens"]
            if isinstance(token_data, dict):
                try:
                    tokens = TokenUsage(**token_data)
                except Exception as e:
                    log.error(
                        "Failed to parse token usage",
                        token_data=token_data,
                        error=str(e),
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

    def _should_retry_implement(
        self,
        result: PipelineResult,
        nodes: list[NodeDefinition],
    ) -> bool:
        """Check if we should retry implement after verify failure.

        Args:
            result: Current pipeline result.
            nodes: All nodes in pipeline.

        Returns:
            True if we should retry implement, False otherwise.
        """
        # Only retry if:
        # 1. We have an implement node
        # 2. We haven't exceeded max fix attempts
        has_implement = any(n.id in ("implement", "implement_direct") for n in nodes)
        max_attempts = self.config.run.max_fix_attempts

        return has_implement and result.fix_attempts < max_attempts

    def _verify_reproduce_stage(
        self,
        node: NodeDefinition,
        context: dict[str, Any],
        exec_ctx: ExecutionContext,
    ) -> NodeResult:
        """Verify that the reproduction stage produced a failing test.

        Args:
            node: The reproduce node.
            context: Input context.
            exec_ctx: Execution context.

        Returns:
            NodeResult indicating success (test failed) or failure (test passed/missing).
        """
        # 1. Find the reproduction script
        # We look for reproduce_issue.py or tests/test_reproduce_issue.py
        # or verify what file was created.
        worktree = self.workspace.worktree_path
        candidates = [
            worktree / "reproduce_issue.py",
            worktree / "tests" / "test_reproduce_issue.py",
        ]
        
        # Also check changed files in workspace if possible
        try:
            changed = self.workspace.get_changed_files()
            for f in changed:
                path = worktree / f
                if path.name in ("reproduce_issue.py", "test_reproduce_issue.py") or (
                    path.suffix == ".py" and "reproduce" in path.name
                ):
                    candidates.insert(0, path)
        except Exception:
            pass

        target_file = None
        for cand in candidates:
            if cand.exists():
                target_file = cand
                break
        
        if not target_file:
            return NodeResult(
                success=False,
                error="Reproduction script not found (expected reproduce_issue.py)",
            )

        # 2. Run the test
        # Use pytest if it's a test file, or python if it's a script
        cmd = ["pytest", str(target_file)] if "test" in target_file.name or "pytest" in context.get("repo_context", "") else ["python", str(target_file)]
        
        # We assume pytest for consistency if available, otherwise python
        # Check if it's a pytest file
        if target_file.name.startswith("test_") or target_file.name.endswith("_test.py"):
            cmd = ["pytest", str(target_file)]
        else:
             # If it's a plain script, run with python
             cmd = ["python3", str(target_file)]

        logger.info("Running reproduction test", command=cmd)
        
        code, stdout, stderr = self.cmd.run_capture(cmd, cwd=worktree)
        
        # 3. Check exit code
        # We EXPECT failure (code != 0)
        if code == 0:
            return NodeResult(
                success=False,
                error=f"Reproduction test {target_file.name} PASSED, but expected FAILURE (Fail-to-Pass)",
            )
        
        # 4. Save failure output
        failure_log = f"Command: {' '.join(cmd)}\nExit Code: {code}\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}"
        self.paths.reproduce_failure_md.write_text(failure_log)
        
        # Store in artifact store for next stages
        self.store.set("reproduce_failure", failure_log, source_node="reproduce")
        
        return NodeResult(success=True)

    @classmethod
    def from_config(
        cls,
        config: OrxConfig,
        paths: RunPaths,
        workspace: WorkspaceGitWorktree,
        gates: list[Gate],
        state: StateManager | None = None,
        metrics_writer: MetricsWriter | None = None,
        observability: RunObservability | None = None,
        cmd: CommandRunner | None = None,
    ) -> PipelineRunner:
        """Create a pipeline runner from configuration.

        Args:
            config: ORX configuration.
            paths: Run paths.
            workspace: Git worktree.
            gates: Quality gates.
            state: Run state.
            metrics_writer: Optional metrics writer for stage metrics.
            observability: Optional run observability runtime.
            cmd: Shared command runner.

        Returns:
            Configured PipelineRunner.
        """
        from orx.prompts.renderer import PromptRenderer

        # Create router and get default executor
        shared_cmd = cmd or CommandRunner()
        router = ModelRouter(
            engine=config.engine,
            executors=config.executors,
            stages=config.stages,
            fallback=config.fallback,
            cmd=shared_cmd,
            dry_run=False,
        )
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
            observability=observability,
            cmd=shared_cmd,
        )


def run_pipeline(
    pipeline_id: str,
    task: str,
    config: OrxConfig,
    paths: RunPaths,
    workspace: WorkspaceGitWorktree,
    gates: list[Gate],
    state: StateManager | None = None,
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
        registry = PipelineRegistry.load()

    pipeline = registry.get(pipeline_id)

    runner = PipelineRunner.from_config(
        config=config,
        paths=paths,
        workspace=workspace,
        gates=gates,
        state=state,
    )

    return runner.run(pipeline, task)
