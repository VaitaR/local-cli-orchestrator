"""Runner FSM orchestrator for orx."""

from __future__ import annotations

import json
import os
import signal
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from orx.config import EngineConfig, EngineType, ModelSelector, OrxConfig
from orx.context.backlog import Backlog, WorkItem
from orx.context.pack import ContextPack
from orx.context.repo_context import RepoContextBuilder
from orx.exceptions import GuardrailError
from orx.executors.base import Executor
from orx.executors.codex import CodexExecutor
from orx.executors.fake import FakeExecutor
from orx.executors.gemini import GeminiExecutor
from orx.executors.router import ModelRouter
from orx.gates.base import Gate, GateResult
from orx.gates.docker import DockerGate
from orx.gates.generic import GenericGate
from orx.gates.pytest import PytestGate
from orx.gates.ruff import RuffGate
from orx.infra.command import CommandRunner
from orx.metrics.collector import MetricsCollector
from orx.metrics.events import EventLogger
from orx.metrics.schema import FailureCategory, StageStatus
from orx.metrics.writer import MetricsWriter, append_to_index
from orx.paths import RunPaths
from orx.prompts.renderer import PromptRenderer
from orx.stages.base import StageContext, StageResult
from orx.stages.decompose import DecomposeStage
from orx.stages.implement import FixStage, ImplementStage
from orx.stages.knowledge import KnowledgeUpdateStage
from orx.stages.plan import PlanStage
from orx.stages.review import ReviewStage
from orx.stages.ship import ShipStage
from orx.stages.spec import SpecStage
from orx.stages.verify import VerifyStage
from orx.state import Stage, StateManager
from orx.workspace.git_worktree import WorkspaceGitWorktree
from orx.workspace.guardrails import Guardrails

logger = structlog.get_logger()


@contextmanager
def _termination_signals():
    """Convert SIGTERM/SIGINT into KeyboardInterrupt for graceful cleanup."""
    old_term = signal.getsignal(signal.SIGTERM)
    old_int = signal.getsignal(signal.SIGINT)

    def _handler(signum: int, frame: Any) -> None:  # noqa: ARG001
        raise KeyboardInterrupt(f"Received signal {signum}")

    try:
        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)
    except Exception:
        # Best-effort: signal handling isn't guaranteed in all environments.
        yield
        return

    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)


@dataclass
class StageModelInfo:
    """Model selection info for a stage execution.

    Attributes:
        stage: Stage name.
        executor: Executor used.
        model: Model used (if any).
        profile: Profile used (if any).
        reasoning_effort: Reasoning effort (if any).
        cmd: Full command executed.
        attempt: Attempt number.
        fallback_applied: Whether fallback was applied.
    """

    stage: str
    executor: str
    model: str | None = None
    profile: str | None = None
    reasoning_effort: str | None = None
    cmd: list[str] | None = None
    attempt: int = 1
    fallback_applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "stage": self.stage,
            "executor": self.executor,
            "selector": {
                "model": self.model,
                "profile": self.profile,
                "reasoning_effort": self.reasoning_effort,
            },
            "cmd": self.cmd,
            "attempt": self.attempt,
            "fallback_applied": self.fallback_applied,
        }


@dataclass
class RunMeta:
    """Metadata for a run.

    Attributes:
        run_id: The run identifier.
        start_time: When the run started.
        end_time: When the run ended.
        engine: Primary engine used.
        base_branch: Base branch.
        branch_name: Branch name for changes.
        versions: Version information.
        stage_statuses: Status of each stage.
        stage_models: Model selection info per stage.
    """

    run_id: str
    start_time: str
    end_time: str | None = None
    engine: str = ""
    base_branch: str = ""
    branch_name: str = ""
    versions: dict[str, str] = field(default_factory=dict)
    stage_statuses: dict[str, str] = field(default_factory=dict)
    stage_models: list[StageModelInfo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "run_id": self.run_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "engine": self.engine,
            "base_branch": self.base_branch,
            "branch_name": self.branch_name,
            "versions": self.versions,
            "stage_statuses": self.stage_statuses,
            "stage_models": [sm.to_dict() for sm in self.stage_models],
        }

    def record_stage_model(
        self,
        stage: str,
        executor: str,
        model: str | None = None,
        profile: str | None = None,
        reasoning_effort: str | None = None,
        cmd: list[str] | None = None,
        attempt: int = 1,
        fallback_applied: bool = False,
    ) -> None:
        """Record model selection for a stage.

        Args:
            stage: Stage name.
            executor: Executor used.
            model: Model used.
            profile: Profile used.
            reasoning_effort: Reasoning effort.
            cmd: Full command executed.
            attempt: Attempt number.
            fallback_applied: Whether fallback was applied.
        """
        self.stage_models.append(
            StageModelInfo(
                stage=stage,
                executor=executor,
                model=model,
                profile=profile,
                reasoning_effort=reasoning_effort,
                cmd=cmd,
                attempt=attempt,
                fallback_applied=fallback_applied,
            )
        )


class Runner:
    """FSM orchestrator for orx runs.

    Manages the complete lifecycle of a run including:
    - Stage execution
    - Fix loops
    - State persistence
    - Resume support
    - Model routing and fallback

    Example:
        >>> config = OrxConfig.default()
        >>> runner = Runner(config, base_dir=Path("/project"))
        >>> runner.run(task="Implement feature X")
    """

    def __init__(
        self,
        config: OrxConfig,
        *,
        base_dir: Path,
        run_id: str | None = None,
        dry_run: bool = False,
    ) -> None:
        """Initialize the runner.

        Args:
            config: OrxConfig instance.
            base_dir: Base directory for the project.
            run_id: Optional run ID (for resume).
            dry_run: If True, don't execute commands.
        """
        self.config = config
        self.base_dir = base_dir
        self.dry_run = dry_run

        # Create or load paths
        if run_id:
            self.paths = RunPaths.from_existing(base_dir, run_id)
        else:
            self.paths = RunPaths.create_new(base_dir)

        # Initialize components
        self.cmd = CommandRunner(dry_run=dry_run)
        self.state = StateManager(self.paths)
        self.pack = ContextPack(self.paths)
        self.workspace = WorkspaceGitWorktree(self.paths, self.cmd, base_dir)
        self.renderer = PromptRenderer()
        self.guardrails = Guardrails(config.guardrails)

        # Initialize model router for per-stage model selection
        self.model_router = ModelRouter(
            engine=config.engine,
            executors=config.executors,
            stages=config.stages,
            fallback=config.fallback,
            cmd=self.cmd,
            dry_run=dry_run,
        )

        # Use model router's primary executor (ensures consistent binary)
        self.executor = self.model_router.get_primary_executor()
        self.stage_executors = self._create_stage_executors()

        # Create gates
        self.gates = self._create_gates()

        # Create stage instances
        self.stages = {
            "plan": PlanStage(),
            "spec": SpecStage(),
            "decompose": DecomposeStage(),
            "implement": ImplementStage(),
            "fix": FixStage(),
            "verify": VerifyStage(),
            "review": ReviewStage(),
            "ship": ShipStage(),
            "knowledge_update": KnowledgeUpdateStage(),
        }

        # Meta tracking
        self.meta = RunMeta(
            run_id=self.paths.run_id,
            start_time=datetime.now(tz=UTC).isoformat(),
            engine=config.engine.type.value,
            base_branch=config.git.base_branch,
        )

        # Initialize metrics collection
        self.metrics = MetricsCollector(
            run_id=self.paths.run_id,
            engine=config.engine.type.value,
            model=config.engine.model,
            base_branch=config.git.base_branch,
        )
        self.metrics_writer = MetricsWriter(self.paths)
        self.events = EventLogger(self.paths.events_jsonl)

    def _create_executor(self, engine_config: EngineConfig | None = None) -> Executor:
        """Create an executor from engine config."""
        engine_config = engine_config or self.config.engine

        if engine_config.type == EngineType.CODEX:
            codex_cfg = self.config.executors.codex
            return CodexExecutor(
                cmd=self.cmd,
                binary=engine_config.binary or codex_cfg.bin or "codex",
                extra_args=engine_config.extra_args,
                dry_run=self.dry_run,
                default_model=engine_config.model or codex_cfg.default.model,
                default_profile=engine_config.profile,
                default_reasoning_effort=engine_config.reasoning_effort
                or codex_cfg.default.reasoning_effort,
            )
        elif engine_config.type == EngineType.GEMINI:
            gemini_cfg = self.config.executors.gemini
            return GeminiExecutor(
                cmd=self.cmd,
                binary=engine_config.binary or gemini_cfg.bin or "gemini",
                extra_args=engine_config.extra_args,
                dry_run=self.dry_run,
                default_model=engine_config.model or gemini_cfg.default.model,
                output_format=engine_config.output_format
                or gemini_cfg.default.output_format
                or "json",
            )
        elif engine_config.type == EngineType.FAKE:
            return FakeExecutor()
        else:
            msg = f"Unknown engine type: {engine_config.type}"
            raise ValueError(msg)

    def _create_stage_executors(self) -> dict[str, Executor]:
        """Create executor overrides for specific stages."""
        executors: dict[str, Executor] = {}
        for stage_name, engine_cfg in self.config.stage_engines.items():
            executors[stage_name.lower()] = self._create_executor(engine_cfg)
        return executors

    def _get_executor_for_stage(self, stage: str | None) -> Executor:
        """Get the executor for a specific stage."""
        if not stage:
            return self.executor
        return self.stage_executors.get(stage.lower(), self.executor)

    def _create_gates(self) -> list[Gate]:
        """Create gates based on config."""
        gates: list[Gate] = []

        for gate_config in self.config.get_enabled_gates():
            if gate_config.name == "ruff":
                gates.append(
                    RuffGate(
                        cmd=self.cmd,
                        command=gate_config.command or "ruff",
                        args=gate_config.args or None,
                        required=gate_config.required,
                    )
                )
            elif gate_config.name == "pytest":
                gates.append(
                    PytestGate(
                        cmd=self.cmd,
                        command=gate_config.command or "pytest",
                        args=gate_config.args or None,
                        required=gate_config.required,
                    )
                )
            elif gate_config.name == "docker":
                gates.append(
                    DockerGate(
                        cmd=self.cmd,
                        command=gate_config.command or "docker",
                        args=gate_config.args or None,
                        required=gate_config.required,
                    )
                )
            else:
                # Use GenericGate for custom gates (e.g., helm-lint, e2e-tests)
                if not gate_config.command:
                    msg = f"Custom gate '{gate_config.name}' must specify a command"
                    raise ValueError(msg)
                gates.append(
                    GenericGate(
                        name=gate_config.name,
                        cmd=self.cmd,
                        command=gate_config.command,
                        args=gate_config.args or None,
                        required=gate_config.required,
                    )
                )

        return gates

    def _get_stage_context(self, stage: str | None = None) -> StageContext:
        """Build the stage context.

        Args:
            stage: Optional stage name for model routing.

        Returns:
            StageContext with executor and model_selector.

        Note:
            If self.executor has been replaced (e.g., by tests), it takes
            precedence over the model router's executor selection.
        """
        # Check if executor was overridden (for testing)
        default_executor = self.model_router.get_primary_executor()
        executor_overridden = self.executor is not default_executor

        # Use model router if stage is specified and executor wasn't overridden
        if stage and not executor_overridden:
            executor, model_selector = self.model_router.get_executor_for_stage(stage)
        elif executor_overridden:
            # Use the overridden executor (for testing compatibility)
            executor = self.executor
            if stage:
                _, model_selector = self.model_router.get_executor_for_stage(stage)
            else:
                model_selector = ModelSelector()
        else:
            executor = self.executor
            model_selector = ModelSelector()

        timeout_seconds: int | None = None
        if stage:
            timeout_seconds = self.config.engine.stage_timeouts.get(
                stage, self.config.engine.timeout
            )
        else:
            timeout_seconds = self.config.engine.timeout

        return StageContext(
            paths=self.paths,
            pack=self.pack,
            state=self.state,
            workspace=self.workspace,
            executor=executor,
            gates=self.gates,
            renderer=self.renderer,
            config=self.config.model_dump(),
            timeout_seconds=timeout_seconds,
            model_selector=model_selector,
            events=self.events,
        )

    def _collect_versions(self) -> dict[str, str]:
        """Collect version information for meta.json."""
        versions: dict[str, str] = {}

        commands = [
            ("python", ["python", "--version"]),
            ("ruff", ["ruff", "--version"]),
            ("pytest", ["pytest", "--version"]),
            ("git", ["git", "--version"]),
        ]

        # Add engine versions
        engine_types = {self.config.engine.type}
        for engine_cfg in self.config.stage_engines.values():
            engine_types.add(engine_cfg.type)
        if self.config.fallback_engine:
            engine_types.add(self.config.fallback_engine.type)

        if EngineType.CODEX in engine_types:
            commands.append(("codex", ["codex", "--version"]))
        if EngineType.GEMINI in engine_types:
            commands.append(("gemini", ["gemini", "--version"]))

        for name, cmd in commands:
            try:
                code, stdout, _stderr = self.cmd.run_capture(cmd, timeout=5)
                if code == 0:
                    versions[name] = stdout.strip().split("\n")[0]
                else:
                    versions[name] = "unknown"
            except Exception:
                versions[name] = "unknown"

        return versions

    def _save_meta(self, success: bool = True) -> None:
        """Save meta.json and metrics."""
        self.meta.versions = self._collect_versions()
        self.meta.end_time = datetime.now(tz=UTC).isoformat()

        # Collect stage statuses
        for stage_key, status in self.state.state.stage_statuses.items():
            self.meta.stage_statuses[stage_key] = status.status

        meta_path = self.paths.meta_json
        meta_path.write_text(json.dumps(self.meta.to_dict(), indent=2))

        # Save metrics
        self._save_metrics(success)

    def _save_metrics(self, success: bool = True) -> None:
        """Save metrics to files.

        Args:
            success: Whether the run was successful.
        """
        try:
            # Write all stage metrics
            self.metrics_writer.write_stages(self.metrics.get_stage_metrics())

            # Get final diff for run metrics
            final_diff = None
            if self.paths.patch_diff.exists():
                final_diff = self.paths.patch_diff.read_text()

            # Build and write run metrics
            final_status = StageStatus.SUCCESS if success else StageStatus.FAIL
            failure_reason = None
            if not success and self.state.state.stage_statuses:
                # Get last failure message
                for status in reversed(list(self.state.state.stage_statuses.values())):
                    if status.error:
                        failure_reason = status.error
                        break

            run_metrics = self.metrics.build_run_metrics(
                final_status=final_status,
                failure_reason=failure_reason,
                final_diff=final_diff,
            )
            self.metrics_writer.write_run(run_metrics)

            # Append to global index
            append_to_index(
                self.base_dir,
                self.paths.run_id,
                {
                    "run_id": self.paths.run_id,
                    "status": final_status.value,
                    "duration_ms": run_metrics.total_duration_ms,
                    "engine": self.config.engine.type.value,
                    "stages_executed": run_metrics.stages_executed,
                    "fix_attempts": run_metrics.fix_attempts_total,
                },
            )

        except Exception as e:
            logger.warning("Failed to save metrics", error=str(e))

    def _build_repo_context(self, *, force_rebuild: bool = False) -> None:
        """Build repo context pack from the worktree.

        Collects stack, tooling configuration, and gate commands
        and writes them to context files for use in prompts.

        Args:
            force_rebuild: If True, rebuild even if files exist.
        """
        log = logger.bind(run_id=self.paths.run_id)

        # Skip if files already exist (for resume stability)
        if (
            not force_rebuild
            and self.pack.tooling_snapshot_exists()
            and self.pack.project_map_exists()
        ):
            log.debug("Repo context pack already exists, reusing")
            return

        try:
            builder = RepoContextBuilder(
                worktree=self.workspace.worktree_path,
                gates=self.gates,
            )
            result = builder.build()

            # Write project map (stack profile)
            if result.project_map:
                self.pack.write_project_map(result.project_map)

            # Write tooling snapshot (full context)
            if result.tooling_snapshot:
                self.pack.write_tooling_snapshot(result.tooling_snapshot)

            # Write verify commands
            if result.verify_commands:
                self.pack.write_verify_commands(result.verify_commands)

            log.info(
                "Repo context pack built",
                stacks=result.detected_stacks,
                profile_size=len(result.project_map),
                tooling_size=len(result.tooling_snapshot),
            )

        except Exception as e:
            # Non-fatal: log warning and continue
            log.warning("Failed to build repo context pack", error=str(e))

    def run(self, task: str | Path) -> bool:
        """Run the full orchestration.

        Args:
            task: Task description or path to task file.

        Returns:
            True if run completed successfully.
        """
        log = logger.bind(run_id=self.paths.run_id)
        log.info("Starting run")
        if self.events:
            self.events.log("run_start", run_id=self.paths.run_id)

        state_initialized = False

        try:
            with _termination_signals():
                # Initialize state
                self.state.initialize()
                state_initialized = True
                self.state.set_pid(os.getpid())

                # Write task
                task_content = task.read_text() if isinstance(task, Path) else task
                self.pack.write_task(task_content)

                # Set task fingerprint for metrics
                self.metrics.set_task_fingerprint(task_content)

                # Create workspace
                base_branch = self.config.git.base_branch
                self.workspace.create(base_branch)
                self.state.set_baseline_sha(self.workspace.baseline_sha())
                self.meta.branch_name = f"orx/{self.paths.run_id}"

                # Validate base branch (warn if mismatch)
                try:
                    self.workspace.validate_base_branch(base_branch)
                except Exception as e:
                    log.warning("Base branch validation warning", error=str(e))

                # Build repo context pack (stack, tooling, gates)
                self._build_repo_context()

                # Execute stages
                success = self._execute_stages()
                if state_initialized:
                    self.state.set_pid(None)
                if self.events:
                    self.events.log(
                        "run_end",
                        run_id=self.paths.run_id,
                        status="success" if success else "failure",
                    )
                return success

        except BaseException as e:
            msg = "Cancelled" if isinstance(e, KeyboardInterrupt) else str(e)
            log.error("Run failed", error=msg)
            if self.events:
                self.events.log(
                    "run_end",
                    run_id=self.paths.run_id,
                    status="failure",
                    error=msg,
                )
            if state_initialized:
                self.state.mark_stage_failed(msg)
                self.state.set_pid(None)
                self._save_meta(success=False)
            raise

    def resume(self) -> bool:
        """Resume a previously started run.

        Returns:
            True if run completed successfully.
        """
        log = logger.bind(run_id=self.paths.run_id)
        log.info("Resuming run")
        if self.events:
            self.events.log("run_resume", run_id=self.paths.run_id)

        state_loaded = False

        try:
            with _termination_signals():
                # Load state
                self.state.load()
                state_loaded = True
                self.state.set_pid(os.getpid())

                if not self.state.is_resumable():
                    log.warning("Run is not resumable")
                    return False

                self._recover_running_text_stage()

                # Restore workspace if needed
                if not self.workspace.exists():
                    base_branch = self.config.git.base_branch
                    self.workspace.create(base_branch)
                    # Restore baseline
                    if self.state.state.baseline_sha:
                        self.workspace.reset(self.state.state.baseline_sha)

                # Rebuild repo context pack if missing (for resume stability)
                self._build_repo_context()

                # Continue from resume point
                success = self._execute_stages()
                if state_loaded:
                    self.state.set_pid(None)
                if self.events:
                    self.events.log(
                        "run_end",
                        run_id=self.paths.run_id,
                        status="success" if success else "failure",
                    )
                return success

        except BaseException as e:
            msg = "Cancelled" if isinstance(e, KeyboardInterrupt) else str(e)
            log.error("Resume failed", error=msg)
            if self.events:
                self.events.log(
                    "run_end",
                    run_id=self.paths.run_id,
                    status="failure",
                    error=msg,
                )
            if state_loaded:
                self.state.mark_stage_failed(msg)
                self.state.set_pid(None)
                self._save_meta(success=False)
            raise

    def _recover_running_text_stage(self) -> None:
        """Recover a text stage output if the run was interrupted after LLM output.

        If a stage is marked as running and a corresponding `<stage>_output.md`
        exists in the context directory, this method attempts to copy it into the
        final artifact (plan.md/spec.md/backlog.yaml/review.md) and advance the
        current stage to the next stage in the FSM.
        """
        stage = self.state.current_stage
        if stage not in (Stage.PLAN, Stage.SPEC, Stage.DECOMPOSE, Stage.REVIEW):
            return

        status = self.state.state.stage_statuses.get(stage.value)
        if status is None or status.status != "running":
            return

        out_path = self.paths.context_dir / f"{stage.value}_output.md"
        if not out_path.exists():
            return

        content = out_path.read_text()

        if stage == Stage.PLAN and not self.paths.plan_md.exists():
            self.pack.write_plan(content)
        elif stage == Stage.SPEC and not self.paths.spec_md.exists():
            self.pack.write_spec(content)
        elif stage == Stage.DECOMPOSE and not self.paths.backlog_yaml.exists():
            # Validate that the recovered backlog is parseable.
            self.paths.backlog_yaml.write_text(content)
            Backlog.load(self.paths.backlog_yaml)
        elif stage == Stage.REVIEW and not self.paths.review_md.exists():
            self.pack.write_review(content)
        else:
            return

        self.state.mark_stage_completed(stage)

        next_stage_map = {
            Stage.PLAN: Stage.SPEC,
            Stage.SPEC: Stage.DECOMPOSE,
            Stage.DECOMPOSE: Stage.IMPLEMENT_ITEM,
            Stage.REVIEW: Stage.SHIP,
        }
        next_stage = next_stage_map.get(stage)
        if next_stage:
            self.state.transition_to(next_stage)

    def _execute_stages(self) -> bool:
        """Execute the FSM stages.

        Returns:
            True if all stages completed successfully.
        """
        log = logger.bind(run_id=self.paths.run_id)
        # Stage execution order
        stage_order = [
            Stage.PLAN,
            Stage.SPEC,
            Stage.DECOMPOSE,
            Stage.IMPLEMENT_ITEM,
            Stage.REVIEW,
            Stage.SHIP,
            Stage.KNOWLEDGE_UPDATE,
        ]

        # Find starting point
        current = self.state.current_stage
        start_idx = 0
        for i, stage in enumerate(stage_order):
            if stage == current:
                start_idx = i
                break

        # Execute stages
        for stage in stage_order[start_idx:]:
            self.state.transition_to(stage)

            if stage == Stage.PLAN:
                result = self._run_stage_with_metrics("plan", self._run_plan)
            elif stage == Stage.SPEC:
                result = self._run_stage_with_metrics("spec", self._run_spec)
            elif stage == Stage.DECOMPOSE:
                result = self._run_stage_with_metrics("decompose", self._run_decompose)
            elif stage == Stage.IMPLEMENT_ITEM:
                result = self._run_implement_loop()
            elif stage == Stage.REVIEW:
                result = self._run_stage_with_metrics("review", self._run_review)
            elif stage == Stage.SHIP:
                result = self._run_stage_with_metrics("ship", self._run_ship)
            elif stage == Stage.KNOWLEDGE_UPDATE:
                result = self._run_stage_with_metrics(
                    "knowledge_update", self._run_knowledge_update
                )
            else:
                continue

            if not result.success:
                log.error("Stage failed", stage=stage.value, error=result.message)
                self.state.mark_stage_failed(result.message)
                self.state.transition_to(Stage.FAILED)
                self._save_meta(success=False)
                return False

            self.state.mark_stage_completed()

        # All done
        self.state.transition_to(Stage.DONE)
        self.state.mark_stage_completed()
        self._save_meta(success=True)
        log.info("Run completed successfully")
        return True

    def _run_stage_with_metrics(
        self,
        stage_name: str,
        run_fn: Any,
    ) -> StageResult:
        """Run a stage with metrics collection.

        Args:
            stage_name: Name of the stage.
            run_fn: Function to run the stage.

        Returns:
            StageResult from the stage execution.
        """
        ctx = self._get_stage_context(stage_name)

        if self.events:
            self.events.log("stage_start", stage=stage_name)

        with self.metrics.stage(stage_name) as timer:
            # Record model selection
            self.metrics.record_model_selection(
                executor=ctx.executor.name,
                model_selector=ctx.model_selector,
            )

            # Record input fingerprint
            self._record_stage_inputs(stage_name)

            # Time LLM call
            timer.start_llm()
            result = run_fn(ctx)
            timer.end_llm()

            # Record outputs and result
            self._record_stage_outputs(stage_name, result)

            if result.success:
                self.metrics.record_success()
            else:
                failure_cat = self._categorize_failure(result.message)
                self.metrics.record_failure(failure_cat, result.message)

        if self.events:
            self.events.log(
                "stage_end",
                stage=stage_name,
                status="success" if result.success else "failure",
                message=result.message,
            )

        return result

    def _record_stage_inputs(self, stage: str) -> None:
        """Record input fingerprints for a stage.

        Args:
            stage: Stage name.
        """
        inputs: list[str | Path] = []

        # Task is always an input
        if self.paths.task_md.exists():
            inputs.append(self.paths.task_md)

        # Stage-specific inputs
        if (
            stage in ("spec", "decompose", "implement", "fix", "review")
            and self.paths.plan_md.exists()
        ):
            inputs.append(self.paths.plan_md)
        if (
            stage in ("decompose", "implement", "fix", "review")
            and self.paths.spec_md.exists()
        ):
            inputs.append(self.paths.spec_md)
        if stage in ("implement", "fix", "review") and self.paths.backlog_yaml.exists():
            inputs.append(self.paths.backlog_yaml)
        if inputs:
            self.metrics.record_inputs_fingerprint(*inputs)

    def _record_stage_outputs(self, stage: str, result: StageResult) -> None:  # noqa: ARG002
        """Record output fingerprints and artifacts for a stage.

        Args:
            stage: Stage name.
            result: Stage result.
        """
        outputs: list[str | Path] = []
        artifacts: dict[str, Path] = {}

        # Stage-specific outputs
        if stage == "plan" and self.paths.plan_md.exists():
            outputs.append(self.paths.plan_md)
            artifacts["plan"] = self.paths.plan_md
        elif stage == "spec" and self.paths.spec_md.exists():
            outputs.append(self.paths.spec_md)
            artifacts["spec"] = self.paths.spec_md
        elif stage == "decompose" and self.paths.backlog_yaml.exists():
            outputs.append(self.paths.backlog_yaml)
            artifacts["backlog"] = self.paths.backlog_yaml
        elif stage == "review" and self.paths.review_md.exists():
            outputs.append(self.paths.review_md)
            artifacts["review"] = self.paths.review_md

        if outputs:
            self.metrics.record_outputs_fingerprint(*outputs)
        if artifacts:
            self.metrics.record_artifacts(artifacts)

    def _categorize_failure(self, message: str | None) -> FailureCategory:
        """Categorize a failure message.

        Args:
            message: Error message.

        Returns:
            FailureCategory enum value.
        """
        if not message:
            return FailureCategory.UNKNOWN

        msg_lower = message.lower()

        if "gate" in msg_lower or "ruff" in msg_lower or "pytest" in msg_lower:
            return FailureCategory.GATE_FAILURE
        if "guardrail" in msg_lower or "forbidden" in msg_lower:
            return FailureCategory.GUARDRAIL_VIOLATION
        if "timeout" in msg_lower:
            return FailureCategory.TIMEOUT
        if "parse" in msg_lower or "yaml" in msg_lower or "invalid" in msg_lower:
            return FailureCategory.PARSE_ERROR
        if "empty" in msg_lower and "diff" in msg_lower:
            return FailureCategory.EMPTY_DIFF
        if "executor" in msg_lower or "failed" in msg_lower:
            return FailureCategory.EXECUTOR_ERROR

        return FailureCategory.UNKNOWN

    def _run_plan(self, ctx: StageContext) -> StageResult:
        """Run the plan stage."""
        return self.stages["plan"].execute(ctx)

    def _run_spec(self, ctx: StageContext) -> StageResult:
        """Run the spec stage."""
        return self.stages["spec"].execute(ctx)

    def _run_decompose(self, ctx: StageContext) -> StageResult:
        """Run the decompose stage."""
        return self.stages["decompose"].execute(ctx)

    def _run_implement_loop(self) -> StageResult:
        """Run the implementation loop over all work items."""
        log = logger.bind(stage="implement_loop")
        log.info("Starting implementation loop")

        if self.events:
            self.events.log("stage_start", stage="implement_item")

        base_ctx = self._get_stage_context()
        implement_ctx = self._get_stage_context("implement")
        fix_ctx = self._get_stage_context("fix")
        verify_ctx = self._get_stage_context("verify")

        # Load backlog
        def _finish(result: StageResult) -> StageResult:
            if self.events:
                self.events.log(
                    "stage_end",
                    stage="implement_item",
                    status="success" if result.success else "failure",
                    message=result.message,
                )
            return result

        try:
            backlog = Backlog.load(self.paths.backlog_yaml)
        except Exception as e:
            return _finish(
                StageResult(success=False, message=f"Failed to load backlog: {e}")
            )

        # Track items for metrics
        self.metrics.set_items_count(total=len(backlog.items))

        max_attempts = self.config.run.max_fix_attempts

        while not backlog.all_done():
            item = backlog.get_next_todo()
            if not item:
                log.warning("No more items to process but backlog not done")
                break

            log.info("Processing work item", item_id=item.id, title=item.title)
            if self.events:
                self.events.log(
                    "item_start",
                    item_id=item.id,
                    title=item.title,
                )
            self.state.set_current_item(item.id)
            item.mark_in_progress()
            backlog.save(self.paths.backlog_yaml)

            # Implementation/fix loop
            success = False

            for attempt in range(1, max_attempts + 1):
                item.increment_attempts()
                log.info("Implementation attempt", attempt=attempt)

                # Choose stage name based on attempt
                stage_name = "implement" if attempt == 1 else "fix"
                ctx = implement_ctx if attempt == 1 else fix_ctx

                with self.metrics.stage(
                    stage_name, item_id=item.id, attempt=attempt
                ) as timer:
                    # Record model selection
                    self.metrics.record_model_selection(
                        executor=ctx.executor.name,
                        model_selector=ctx.model_selector,
                    )

                    # Track fix attempts
                    if attempt > 1:
                        self.metrics.add_fix_attempt()

                    # Run implement or fix
                    timer.start_llm()
                    if attempt == 1:
                        result = self.stages["implement"].execute_for_item(
                            implement_ctx, item
                        )
                    else:
                        evidence = self.state.state.last_failure_evidence
                        result = self.stages["fix"].execute_fix(
                            fix_ctx, item, attempt, evidence
                        )  # type: ignore[attr-defined]
                    timer.end_llm()

                    if not result.success:
                        log.warning("Implementation failed", error=result.message)
                        self.metrics.record_failure(
                            FailureCategory.EXECUTOR_ERROR, result.message
                        )
                        continue

                    # Capture diff
                    base_ctx.workspace.diff_to(base_ctx.paths.patch_diff)

                    # Check for empty diff
                    if base_ctx.workspace.diff_empty():
                        log.warning("No changes produced")
                        self.state.set_failure_evidence({"diff_empty": True})
                        self.metrics.record_failure(
                            FailureCategory.EMPTY_DIFF, "No changes produced"
                        )
                        continue

                    # Record diff stats
                    diff_content = base_ctx.paths.patch_diff.read_text()
                    self.metrics.record_diff_stats(diff_content)

                    # Check guardrails
                    try:
                        changed_files = base_ctx.workspace.get_changed_files()
                        self.guardrails.check_files(changed_files)
                    except GuardrailError as e:
                        log.error("Guardrail violation", error=str(e))
                        item.mark_failed(str(e))
                        backlog.save(self.paths.backlog_yaml)
                        self.metrics.record_failure(
                            FailureCategory.GUARDRAIL_VIOLATION, str(e)
                        )
                        return _finish(StageResult(success=False, message=str(e)))

                    # Implementation attempt is considered successful if it produces a non-empty diff
                    # and passes guardrails. Verification is recorded as its own stage.
                    self.metrics.record_success()

                    verify_mode = self._resolve_verify_mode(backlog)
                    verify_result = self._run_verify_with_metrics(
                        verify_ctx,
                        item,
                        attempt,
                        mode=verify_mode,
                    )

                if verify_result.success:
                    log.info("Verification passed")
                    success = True
                    self.state.clear_failure_evidence()

                    # Track first green
                    if attempt == 1 and verify_mode == "full":
                        self.metrics.mark_first_green()

                    break
                else:
                    log.warning("Verification failed", message=verify_result.message)
                    if verify_result.data and "evidence" in verify_result.data:
                        self.state.set_failure_evidence(verify_result.data["evidence"])

            if success:
                item.mark_done()
                self.metrics.set_items_count(
                    total=len(backlog.items),
                    completed=backlog.done_count(),
                    failed=backlog.failed_count(),
                )
                if self.events:
                    self.events.log(
                        "item_end",
                        item_id=item.id,
                        status="success",
                    )
            else:
                log.error("Item failed after max attempts", item_id=item.id)
                item.mark_failed(f"Failed after {max_attempts} attempts")
                self.metrics.set_items_count(
                    total=len(backlog.items),
                    completed=backlog.done_count(),
                    failed=backlog.failed_count(),
                )
                if self.events:
                    self.events.log(
                        "item_end",
                        item_id=item.id,
                        status="failure",
                    )

                if self.config.run.stop_on_first_failure:
                    backlog.save(self.paths.backlog_yaml)
                    return _finish(
                        StageResult(
                            success=False,
                            message=f"Item {item.id} failed after {max_attempts} attempts",
                        )
                    )

            backlog.save(self.paths.backlog_yaml)

        # Check final status
        if backlog.failed_count() > 0:
            return _finish(
                StageResult(
                    success=False,
                    message=f"{backlog.failed_count()} items failed",
                )
            )

        return _finish(
            StageResult(
                success=True,
                message=f"Completed {backlog.done_count()} items",
            )
        )

    def _run_verify_with_metrics(
        self,
        ctx: StageContext,
        item: WorkItem,
        attempt: int,
        *,
        mode: str = "full",
    ) -> StageResult:
        """Run verification with gate metrics collection.

        Args:
            ctx: Stage context.
            item: Work item.
            attempt: Attempt number.
            mode: Verification mode ("full" or "fast").

        Returns:
            StageResult from verification.
        """
        gates = ctx.gates if mode == "full" else self._build_fast_gates(ctx, item)

        if self.events:
            self.events.log(
                "verify_start",
                item_id=item.id,
                attempt=attempt,
                mode=mode,
                gate_count=len(gates),
            )

        with self.metrics.stage("verify", item_id=item.id, attempt=attempt) as timer:
            timer.start_verify()

            if not gates:
                timer.end_verify()
                self.metrics.record_success()
                if self.events:
                    self.events.log(
                        "verify_end",
                        item_id=item.id,
                        attempt=attempt,
                        mode=mode,
                        status="success",
                        skipped=True,
                    )
                return StageResult(success=True, message="No gates to run")

            # Run each gate and record metrics
            for gate in gates:
                if self.events:
                    self.events.log(
                        "gate_start",
                        item_id=item.id,
                        attempt=attempt,
                        mode=mode,
                        gate=gate.name,
                    )
                gate_start = time.perf_counter()
                log_path = ctx.paths.log_path(f"gate_{gate.name}_{item.id}_{attempt}")
                result = gate.run(cwd=ctx.workspace.worktree_path, log_path=log_path)
                gate_duration = int((time.perf_counter() - gate_start) * 1000)

                if (
                    result.failed
                    and gate.name == "ruff"
                    and self.config.run.auto_fix_ruff
                    and "--fix" not in (getattr(gate, "args", []) or [])
                ):
                    fix_result, fix_duration = self._run_ruff_fix(
                        ctx,
                        gate,
                        item,
                        attempt,
                        mode=mode,
                    )
                    gate_duration += fix_duration
                    if fix_result.ok:
                        retry_log = ctx.paths.log_path(
                            f"gate_{gate.name}_{item.id}_{attempt}_retry"
                        )
                        retry_start = time.perf_counter()
                        result = gate.run(
                            cwd=ctx.workspace.worktree_path,
                            log_path=retry_log,
                        )
                        gate_duration += int((time.perf_counter() - retry_start) * 1000)
                        log_path = retry_log

                # Extract test counts for pytest
                tests_failed = None
                tests_total = None
                if gate.name == "pytest" and result.failed:
                    # Try to parse test counts from output
                    log_content = result.read_log()
                    tests_failed, tests_total = self._parse_pytest_output(log_content)

                self.metrics.record_gate(
                    name=gate.name,
                    result=result,
                    duration_ms=gate_duration,
                    tests_failed=tests_failed,
                    tests_total=tests_total,
                )

                if self.events:
                    self.events.log(
                        "gate_end",
                        item_id=item.id,
                        attempt=attempt,
                        mode=mode,
                        gate=gate.name,
                        status="success" if result.ok else "failure",
                        duration_ms=gate_duration,
                        returncode=result.returncode,
                    )

                if result.failed:
                    timer.end_verify()
                    self.metrics.record_failure(
                        FailureCategory.GATE_FAILURE, result.message
                    )
                    if self.events:
                        self.events.log(
                            "verify_end",
                            item_id=item.id,
                            attempt=attempt,
                            mode=mode,
                            status="failure",
                            failed_gate=gate.name,
                        )
                    evidence = self._build_gate_evidence(
                        ctx,
                        failed_gate=gate.name,
                        log_tail=result.get_log_tail(50),
                    )
                    return StageResult(
                        success=False,
                        message=f"Gate {gate.name} failed",
                        data={"evidence": evidence},
                    )

            timer.end_verify()
            self.metrics.record_success()
            if self.events:
                self.events.log(
                    "verify_end",
                    item_id=item.id,
                    attempt=attempt,
                    mode=mode,
                    status="success",
                )
            return StageResult(success=True, message="All gates passed")

    def _build_gate_evidence(
        self,
        ctx: StageContext,
        *,
        failed_gate: str,
        log_tail: str,
    ) -> dict[str, Any]:
        """Build evidence payload for fix prompts."""
        evidence: dict[str, Any] = {
            "ruff_failed": failed_gate == "ruff",
            "pytest_failed": failed_gate == "pytest",
        }

        if failed_gate == "ruff":
            evidence["ruff_log"] = log_tail
        elif failed_gate == "pytest":
            evidence["pytest_log"] = log_tail

        diff = ctx.pack.read_patch_diff()
        if diff:
            evidence["patch_diff"] = diff[:5000] + (
                "\n... (truncated)" if len(diff) > 5000 else ""
            )

        return evidence

    def _parse_pytest_output(self, output: str) -> tuple[int | None, int | None]:
        """Parse pytest output for test counts.

        Args:
            output: Pytest output text.

        Returns:
            Tuple of (failed_count, total_count).
        """
        import re

        # Look for patterns like "3 failed, 10 passed"
        failed = None
        passed = None

        failed_match = re.search(r"(\d+) failed", output)
        if failed_match:
            failed = int(failed_match.group(1))

        passed_match = re.search(r"(\d+) passed", output)
        if passed_match:
            passed = int(passed_match.group(1))

        if failed is not None or passed is not None:
            total = (failed or 0) + (passed or 0)
            return failed, total

        return None, None

    def _resolve_verify_mode(self, backlog: Backlog) -> str:
        """Select verification mode for the current item."""
        if self.config.run.per_item_verify == "full":
            return "full"
        if backlog.todo_count() == 0:
            return "full"
        return "fast"

    @staticmethod
    def _is_test_path(path: Path) -> bool:
        name = path.name
        return (
            "tests" in path.parts
            or (name.startswith("test_") and name.endswith(".py"))
            or name.endswith("_test.py")
        )

    def _collect_pytest_targets(self, item: WorkItem, worktree: Path) -> list[str]:
        targets: list[str] = []
        seen: set[str] = set()

        for raw in item.files_hint:
            path = Path(raw)
            if self._is_test_path(path):
                full_path = worktree / path
                if full_path.exists():
                    rel = str(path)
                    if rel not in seen:
                        targets.append(rel)
                        seen.add(rel)
                continue

            if path.suffix == ".py":
                stem = path.stem
                candidates = [
                    Path("tests") / f"test_{stem}.py",
                    Path("tests") / f"{stem}_test.py",
                ]
                for candidate in candidates:
                    full_path = worktree / candidate
                    if full_path.exists() and str(candidate) not in seen:
                        targets.append(str(candidate))
                        seen.add(str(candidate))

        # Fallback to changed test files if any
        if not targets:
            try:
                changed = self.workspace.get_changed_files()
            except Exception:
                changed = []
            for raw in changed:
                path = Path(raw)
                if not self._is_test_path(path):
                    continue
                full_path = worktree / path
                if not full_path.exists():
                    continue
                rel = str(path)
                if rel not in seen:
                    targets.append(rel)
                    seen.add(rel)

        max_targets = self.config.run.fast_verify_max_pytest_targets
        return targets[:max_targets]

    def _build_fast_gates(self, ctx: StageContext, item: WorkItem) -> list[Gate]:
        """Build a fast gate set for per-item verification."""
        fast_gates: list[Gate] = []
        pytest_targets = self._collect_pytest_targets(item, ctx.workspace.worktree_path)

        for gate in ctx.gates:
            if gate.name == "ruff":
                fast_gates.append(gate)
                continue
            if gate.name != "pytest":
                continue

            if (
                not pytest_targets
                and self.config.run.fast_verify_skip_pytest_if_no_targets
            ):
                if self.events:
                    self.events.log(
                        "gate_skipped",
                        gate="pytest",
                        item_id=item.id,
                        reason="no_targets",
                    )
                continue

            base_args = list(getattr(gate, "args", ["-q"]))
            args = base_args + pytest_targets if pytest_targets else base_args
            command = getattr(gate, "command", "pytest")
            required = getattr(gate, "required", True)
            fast_gates.append(
                PytestGate(
                    cmd=self.cmd,
                    command=command,
                    args=args,
                    required=required,
                )
            )

        return fast_gates

    def _run_ruff_fix(
        self,
        ctx: StageContext,
        gate: Gate,
        item: WorkItem,
        attempt: int,
        *,
        mode: str,
    ) -> tuple[GateResult, int]:
        """Run ruff with --fix to auto-apply lint changes."""
        args = list(getattr(gate, "args", []) or ["check", "."])
        # Defensive check: current callers ensure "--fix" is not in args,
        # but we guard here to remain robust if call sites change.
        if "--fix" not in args:
            args.append("--fix")

        fix_gate = RuffGate(
            cmd=self.cmd,
            command=getattr(gate, "command", "ruff"),
            args=args,
            required=getattr(gate, "required", True),
        )
        log_path = ctx.paths.log_path(f"gate_ruff_fix_{item.id}_{attempt}")
        if self.events:
            self.events.log(
                "gate_fix_start",
                item_id=item.id,
                attempt=attempt,
                mode=mode,
                gate="ruff",
            )
        gate_start = time.perf_counter()
        result = fix_gate.run(cwd=ctx.workspace.worktree_path, log_path=log_path)
        gate_duration = int((time.perf_counter() - gate_start) * 1000)
        if self.events:
            self.events.log(
                "gate_fix_end",
                item_id=item.id,
                attempt=attempt,
                mode=mode,
                gate="ruff",
                status="success" if result.ok else "failure",
                duration_ms=gate_duration,
                returncode=result.returncode,
            )
        return result, gate_duration

    def _run_review(self, ctx: StageContext) -> StageResult:
        """Run the review stage."""
        return self.stages["review"].execute(ctx)

    def _run_ship(self, ctx: StageContext) -> StageResult:
        """Run the ship stage."""
        return self.stages["ship"].execute(ctx)

    def _run_knowledge_update(self, ctx: StageContext) -> StageResult:
        """Run the knowledge update stage.

        This stage updates AGENTS.md and ARCHITECTURE.md based on
        what was learned during the run.
        """
        return self.stages["knowledge_update"].execute(ctx)


def create_runner(
    base_dir: Path,
    *,
    config: OrxConfig | None = None,
    config_path: Path | None = None,
    run_id: str | None = None,
    engine: EngineType | None = None,
    base_branch: str | None = None,
    dry_run: bool = False,
) -> Runner:
    """Create a Runner instance with configuration.

    Args:
        base_dir: Base directory for the project.
        config: Optional OrxConfig instance.
        config_path: Optional path to config file.
        run_id: Optional run ID (for resume).
        engine: Optional engine override.
        base_branch: Optional base branch override.
        dry_run: If True, don't execute commands.

    Returns:
        Configured Runner instance.
    """
    # Load or create config
    if config:
        cfg = config
    elif config_path and config_path.exists():
        cfg = OrxConfig.load(config_path)
    else:
        cfg = OrxConfig.default()

    # Apply overrides
    if engine:
        cfg.engine.type = engine
    if base_branch:
        cfg.git.base_branch = base_branch

    return Runner(cfg, base_dir=base_dir, run_id=run_id, dry_run=dry_run)
