"""Runner FSM orchestrator for orx."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from orx.config import EngineType, OrxConfig
from orx.context.backlog import Backlog
from orx.context.pack import ContextPack
from orx.exceptions import GuardrailError
from orx.executors.base import Executor
from orx.executors.codex import CodexExecutor
from orx.executors.fake import FakeExecutor
from orx.executors.gemini import GeminiExecutor
from orx.gates.base import Gate
from orx.gates.docker import DockerGate
from orx.gates.generic import GenericGate
from orx.gates.pytest import PytestGate
from orx.gates.ruff import RuffGate
from orx.infra.command import CommandRunner
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


@dataclass
class RunMeta:
    """Metadata for a run.

    Attributes:
        run_id: The run identifier.
        start_time: When the run started.
        end_time: When the run ended.
        engine: Engine used.
        base_branch: Base branch.
        branch_name: Branch name for changes.
        versions: Version information.
        stage_statuses: Status of each stage.
    """

    run_id: str
    start_time: str
    end_time: str | None = None
    engine: str = ""
    base_branch: str = ""
    branch_name: str = ""
    versions: dict[str, str] = field(default_factory=dict)
    stage_statuses: dict[str, str] = field(default_factory=dict)

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
        }


class Runner:
    """FSM orchestrator for orx runs.

    Manages the complete lifecycle of a run including:
    - Stage execution
    - Fix loops
    - State persistence
    - Resume support

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

        # Create executor
        self.executor = self._create_executor()

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

    def _create_executor(self) -> Executor:
        """Create the executor based on config."""
        engine_config = self.config.engine

        if engine_config.type == EngineType.CODEX:
            return CodexExecutor(
                cmd=self.cmd,
                binary=engine_config.binary,
                extra_args=engine_config.extra_args,
                dry_run=self.dry_run,
            )
        elif engine_config.type == EngineType.GEMINI:
            return GeminiExecutor(
                cmd=self.cmd,
                binary=engine_config.binary,
                extra_args=engine_config.extra_args,
                dry_run=self.dry_run,
            )
        elif engine_config.type == EngineType.FAKE:
            return FakeExecutor()
        else:
            msg = f"Unknown engine type: {engine_config.type}"
            raise ValueError(msg)

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

    def _get_stage_context(self) -> StageContext:
        """Build the stage context."""
        return StageContext(
            paths=self.paths,
            pack=self.pack,
            state=self.state,
            workspace=self.workspace,
            executor=self.executor,
            gates=self.gates,
            renderer=self.renderer,
            config=self.config.model_dump(),
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

        # Add engine version
        if self.config.engine.type == EngineType.CODEX:
            commands.append(("codex", ["codex", "--version"]))
        elif self.config.engine.type == EngineType.GEMINI:
            commands.append(("gemini", ["gemini", "--version"]))

        for name, cmd in commands:
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if result.returncode == 0:
                    versions[name] = result.stdout.strip().split("\n")[0]
            except Exception:
                versions[name] = "unknown"

        return versions

    def _save_meta(self) -> None:
        """Save meta.json."""
        self.meta.versions = self._collect_versions()
        self.meta.end_time = datetime.now(tz=UTC).isoformat()

        # Collect stage statuses
        for stage_key, status in self.state.state.stage_statuses.items():
            self.meta.stage_statuses[stage_key] = status.status

        meta_path = self.paths.meta_json
        meta_path.write_text(json.dumps(self.meta.to_dict(), indent=2))

    def run(self, task: str | Path) -> bool:
        """Run the full orchestration.

        Args:
            task: Task description or path to task file.

        Returns:
            True if run completed successfully.
        """
        log = logger.bind(run_id=self.paths.run_id)
        log.info("Starting run")

        try:
            # Initialize state
            self.state.initialize()

            # Write task
            task_content = task.read_text() if isinstance(task, Path) else task
            self.pack.write_task(task_content)

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

            # Execute stages
            return self._execute_stages()

        except Exception as e:
            log.error("Run failed", error=str(e))
            self.state.mark_stage_failed(str(e))
            self._save_meta()
            raise

    def resume(self) -> bool:
        """Resume a previously started run.

        Returns:
            True if run completed successfully.
        """
        log = logger.bind(run_id=self.paths.run_id)
        log.info("Resuming run")

        try:
            # Load state
            self.state.load()

            if not self.state.is_resumable():
                log.warning("Run is not resumable")
                return False

            # Restore workspace if needed
            if not self.workspace.exists():
                base_branch = self.config.git.base_branch
                self.workspace.create(base_branch)
                # Restore baseline
                if self.state.state.baseline_sha:
                    self.workspace.reset(self.state.state.baseline_sha)

            # Continue from resume point
            return self._execute_stages()

        except Exception as e:
            log.error("Resume failed", error=str(e))
            self.state.mark_stage_failed(str(e))
            self._save_meta()
            raise

    def _execute_stages(self) -> bool:
        """Execute the FSM stages.

        Returns:
            True if all stages completed successfully.
        """
        log = logger.bind(run_id=self.paths.run_id)
        ctx = self._get_stage_context()

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
                result = self._run_plan(ctx)
            elif stage == Stage.SPEC:
                result = self._run_spec(ctx)
            elif stage == Stage.DECOMPOSE:
                result = self._run_decompose(ctx)
            elif stage == Stage.IMPLEMENT_ITEM:
                result = self._run_implement_loop(ctx)
            elif stage == Stage.REVIEW:
                result = self._run_review(ctx)
            elif stage == Stage.SHIP:
                result = self._run_ship(ctx)
            elif stage == Stage.KNOWLEDGE_UPDATE:
                result = self._run_knowledge_update(ctx)
            else:
                continue

            if not result.success:
                log.error("Stage failed", stage=stage.value, error=result.message)
                self.state.mark_stage_failed(result.message)
                self.state.transition_to(Stage.FAILED)
                self._save_meta()
                return False

            self.state.mark_stage_completed()

        # All done
        self.state.transition_to(Stage.DONE)
        self.state.mark_stage_completed()
        self._save_meta()
        log.info("Run completed successfully")
        return True

    def _run_plan(self, ctx: StageContext) -> StageResult:
        """Run the plan stage."""
        return self.stages["plan"].execute(ctx)

    def _run_spec(self, ctx: StageContext) -> StageResult:
        """Run the spec stage."""
        return self.stages["spec"].execute(ctx)

    def _run_decompose(self, ctx: StageContext) -> StageResult:
        """Run the decompose stage."""
        return self.stages["decompose"].execute(ctx)

    def _run_implement_loop(self, ctx: StageContext) -> StageResult:
        """Run the implementation loop over all work items."""
        log = logger.bind(stage="implement_loop")
        log.info("Starting implementation loop")

        # Load backlog
        try:
            backlog = Backlog.load(self.paths.backlog_yaml)
        except Exception as e:
            return StageResult(success=False, message=f"Failed to load backlog: {e}")

        max_attempts = self.config.run.max_fix_attempts

        while not backlog.all_done():
            item = backlog.get_next_todo()
            if not item:
                log.warning("No more items to process but backlog not done")
                break

            log.info("Processing work item", item_id=item.id, title=item.title)
            self.state.set_current_item(item.id)
            item.mark_in_progress()
            backlog.save(self.paths.backlog_yaml)

            # Implementation/fix loop
            success = False
            for attempt in range(1, max_attempts + 1):
                item.increment_attempts()
                log.info("Implementation attempt", attempt=attempt)

                # Run implement or fix
                if attempt == 1:
                    result = self.stages["implement"].execute_for_item(ctx, item)
                else:
                    evidence = self.state.state.last_failure_evidence
                    result = self.stages["fix"].execute_fix(
                        ctx, item, attempt, evidence
                    )  # type: ignore[attr-defined]

                if not result.success:
                    log.warning("Implementation failed", error=result.message)
                    continue

                # Capture diff
                ctx.workspace.diff_to(ctx.paths.patch_diff)

                # Check for empty diff
                if ctx.workspace.diff_empty():
                    log.warning("No changes produced")
                    self.state.set_failure_evidence({"diff_empty": True})
                    continue

                # Check guardrails
                try:
                    changed_files = ctx.workspace.get_changed_files()
                    self.guardrails.check_files(changed_files)
                except GuardrailError as e:
                    log.error("Guardrail violation", error=str(e))
                    item.mark_failed(str(e))
                    backlog.save(self.paths.backlog_yaml)
                    return StageResult(success=False, message=str(e))

                # Run verification
                verify_result = self.stages["verify"].execute(ctx)

                if verify_result.success:
                    log.info("Verification passed")
                    success = True
                    self.state.clear_failure_evidence()
                    break
                else:
                    log.warning("Verification failed", message=verify_result.message)
                    if verify_result.data and "evidence" in verify_result.data:
                        self.state.set_failure_evidence(verify_result.data["evidence"])

            if success:
                item.mark_done()
            else:
                log.error("Item failed after max attempts", item_id=item.id)
                item.mark_failed(f"Failed after {max_attempts} attempts")

                if self.config.run.stop_on_first_failure:
                    backlog.save(self.paths.backlog_yaml)
                    return StageResult(
                        success=False,
                        message=f"Item {item.id} failed after {max_attempts} attempts",
                    )

            backlog.save(self.paths.backlog_yaml)

        # Check final status
        if backlog.failed_count() > 0:
            return StageResult(
                success=False,
                message=f"{backlog.failed_count()} items failed",
            )

        return StageResult(
            success=True,
            message=f"Completed {backlog.done_count()} items",
        )

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
