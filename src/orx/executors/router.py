"""Model routing and fallback policy for executors."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from orx.config import (
    EngineConfig,
    EngineType,
    ExecutorsConfig,
    FallbackPolicyConfig,
    ModelSelector,
    StageExecutorConfig,
    StagesConfig,
)
from orx.executors.base import ExecResult, Executor, LogPaths, ResolvedInvocation
from orx.executors.codex import CodexExecutor
from orx.executors.fake import FakeExecutor
from orx.executors.gemini import GeminiExecutor

if TYPE_CHECKING:
    from orx.infra.command import CommandRunner
    from orx.paths import RunPaths

logger = structlog.get_logger()


@dataclass
class AttemptRecord:
    """Record of an execution attempt.

    Attributes:
        attempt_number: Which attempt this was (1-based).
        model_info: Model/profile information used.
        invocation: The resolved invocation.
        result: The execution result.
        fallback_applied: Whether a fallback was applied.
    """

    attempt_number: int
    model_info: dict[str, Any]
    invocation: ResolvedInvocation
    result: ExecResult | None = None
    fallback_applied: bool = False


@dataclass
class StageExecution:
    """Record of all attempts for a stage execution.

    Attributes:
        stage: Stage name.
        item_id: Optional work item ID.
        attempts: List of attempt records.
    """

    stage: str
    item_id: str | None = None
    attempts: list[AttemptRecord] = field(default_factory=list)

    def latest_attempt(self) -> AttemptRecord | None:
        """Get the latest attempt."""
        return self.attempts[-1] if self.attempts else None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "stage": self.stage,
            "item_id": self.item_id,
            "attempts": [
                {
                    "attempt_number": a.attempt_number,
                    "model_info": a.model_info,
                    "cmd": a.invocation.cmd,
                    "fallback_applied": a.fallback_applied,
                    "success": a.result.success if a.result else None,
                    "returncode": a.result.returncode if a.result else None,
                }
                for a in self.attempts
            ],
        }


class ModelRouter:
    """Routes model selection and handles fallback policy.

    This class coordinates:
    1. Model resolution based on stage configuration
    2. Executor selection per stage
    3. Fallback policy application on errors

    Model selection priority (deterministic):
    1. stages.<stage>.model|profile (explicit override)
    2. executors.<name>.profiles[stage] (stage-specific profile for Codex)
    3. executors.<name>.default.model (executor default)
    4. engine.model (legacy global config)
    5. CLI built-in default

    Example:
        >>> router = ModelRouter(
        ...     engine=engine_config,
        ...     executors=executors_config,
        ...     stages=stages_config,
        ...     fallback=fallback_config,
        ...     cmd=command_runner,
        ... )
        >>> executor, selector = router.get_executor_for_stage("implement")
        >>> result = executor.run_apply(
        ...     cwd=worktree,
        ...     prompt_path=prompt,
        ...     logs=logs,
        ...     model_selector=selector,
        ... )
    """

    def __init__(
        self,
        *,
        engine: EngineConfig,
        executors: ExecutorsConfig,
        stages: StagesConfig,
        fallback: FallbackPolicyConfig,
        cmd: "CommandRunner",
        dry_run: bool = False,
    ) -> None:
        """Initialize the model router.

        Args:
            engine: Primary engine configuration.
            executors: Configuration for all executors.
            stages: Per-stage configuration.
            fallback: Fallback policy configuration.
            cmd: CommandRunner instance.
            dry_run: If True, executors run in dry-run mode.
        """
        self.engine = engine
        self.executors_config = executors
        self.stages_config = stages
        self.fallback = fallback
        self.cmd = cmd
        self.dry_run = dry_run

        # Create executor instances
        self._executors: dict[EngineType, Executor] = {}
        self._create_executors()

        # Track executions for logging/meta
        self._executions: dict[str, StageExecution] = {}

    def _create_executors(self) -> None:
        """Create executor instances for each engine type."""
        # Codex executor
        codex_cfg = self.executors_config.codex
        self._executors[EngineType.CODEX] = CodexExecutor(
            cmd=self.cmd,
            binary=codex_cfg.bin or "codex",
            dry_run=self.dry_run,
            default_model=codex_cfg.default.model,
            default_reasoning_effort=codex_cfg.default.reasoning_effort,
        )

        # Gemini executor
        gemini_cfg = self.executors_config.gemini
        self._executors[EngineType.GEMINI] = GeminiExecutor(
            cmd=self.cmd,
            binary=gemini_cfg.bin or "gemini",
            dry_run=self.dry_run,
            default_model=gemini_cfg.default.model,
            output_format=gemini_cfg.default.output_format or "json",
        )

        # Fake executor (for testing)
        self._executors[EngineType.FAKE] = FakeExecutor()

    def get_primary_executor(self) -> Executor:
        """Get the primary executor (based on engine config).

        Returns:
            The executor for the primary engine type.
        """
        return self._executors[self.engine.type]

    def _get_executor_type_for_stage(self, stage: str) -> EngineType:
        """Get the executor type for a stage.

        Args:
            stage: Stage name.

        Returns:
            EngineType to use for this stage.
        """
        stage_cfg = self.stages_config.get_stage_config(stage)

        # Stage override takes precedence
        if stage_cfg.executor:
            return stage_cfg.executor

        # Fall back to primary engine
        return self.engine.type

    def resolve_model_selector(self, stage: str) -> ModelSelector:
        """Resolve the model selector for a stage.

        Priority (deterministic):
        1. stages.<stage>.model|profile
        2. executors.<name>.profiles[stage]
        3. executors.<name>.default.model
        4. engine.model

        Args:
            stage: Stage name.

        Returns:
            ModelSelector with resolved model/profile.
        """
        stage_cfg = self.stages_config.get_stage_config(stage)
        executor_type = self._get_executor_type_for_stage(stage)

        # Priority 1: Stage-level override
        if stage_cfg.model or stage_cfg.profile:
            return stage_cfg.to_model_selector()

        # Priority 2: Executor profiles (for Codex)
        if executor_type == EngineType.CODEX:
            codex_cfg = self.executors_config.codex
            if stage in codex_cfg.profiles:
                return ModelSelector(profile=codex_cfg.profiles[stage])

        # Priority 3: Executor default
        if executor_type == EngineType.CODEX:
            codex_default = self.executors_config.codex.default
            if codex_default.model:
                return ModelSelector(
                    model=codex_default.model,
                    reasoning_effort=codex_default.reasoning_effort,
                )
        elif executor_type == EngineType.GEMINI:
            gemini_default = self.executors_config.gemini.default
            if gemini_default.model:
                return ModelSelector(model=gemini_default.model)

        # Priority 4: Engine config (legacy)
        if self.engine.model:
            return ModelSelector(
                model=self.engine.model,
                profile=self.engine.profile,
                reasoning_effort=self.engine.reasoning_effort,
            )

        # No model configured - will use CLI default
        return ModelSelector()

    def get_executor_for_stage(self, stage: str) -> tuple[Executor, ModelSelector]:
        """Get the executor and model selector for a stage.

        Args:
            stage: Stage name.

        Returns:
            Tuple of (Executor, ModelSelector).
        """
        executor_type = self._get_executor_type_for_stage(stage)
        executor = self._executors[executor_type]
        selector = self.resolve_model_selector(stage)

        logger.debug(
            "Resolved executor for stage",
            stage=stage,
            executor=executor_type.value,
            model=selector.model,
            profile=selector.profile,
        )

        return executor, selector

    def apply_fallback(
        self,
        stage: str,
        result: ExecResult,
        current_selector: ModelSelector,
    ) -> tuple[ModelSelector, bool]:
        """Apply fallback policy based on error.

        Args:
            stage: Stage name.
            result: Failed execution result.
            current_selector: Current model selector.

        Returns:
            Tuple of (new ModelSelector, whether fallback was applied).
        """
        if not self.fallback.enabled or not self.fallback.rules:
            return current_selector, False

        executor_type = self._get_executor_type_for_stage(stage)
        stderr = result.read_stderr().lower()
        error_msg = result.error_message.lower()

        for rule in self.fallback.rules:
            # Check executor match
            if rule.match.executor and rule.match.executor != executor_type:
                continue

            # Check error markers
            if rule.match.error_contains:
                matches = any(
                    marker.lower() in stderr or marker.lower() in error_msg
                    for marker in rule.match.error_contains
                )
                if not matches:
                    continue

            # Rule matched - apply fallback
            logger.info(
                "Applying fallback rule",
                stage=stage,
                original_model=current_selector.model,
                fallback_model=rule.switch_to.model,
                fallback_profile=rule.switch_to.profile,
            )

            return ModelSelector(
                model=rule.switch_to.model,
                profile=rule.switch_to.profile,
            ), True

        return current_selector, False

    def record_attempt(
        self,
        stage: str,
        item_id: str | None,
        invocation: ResolvedInvocation,
        result: ExecResult | None = None,
        fallback_applied: bool = False,
    ) -> AttemptRecord:
        """Record an execution attempt for logging/meta.

        Args:
            stage: Stage name.
            item_id: Optional work item ID.
            invocation: The resolved invocation.
            result: The execution result (if completed).
            fallback_applied: Whether fallback was applied.

        Returns:
            The created AttemptRecord.
        """
        key = f"{stage}_{item_id}" if item_id else stage

        if key not in self._executions:
            self._executions[key] = StageExecution(stage=stage, item_id=item_id)

        execution = self._executions[key]
        attempt_num = len(execution.attempts) + 1

        record = AttemptRecord(
            attempt_number=attempt_num,
            model_info=invocation.model_info,
            invocation=invocation,
            result=result,
            fallback_applied=fallback_applied,
        )
        execution.attempts.append(record)

        return record

    def get_execution_history(self) -> dict[str, StageExecution]:
        """Get all recorded execution history.

        Returns:
            Dict of stage key to StageExecution.
        """
        return self._executions.copy()

    def get_stage_execution(
        self,
        stage: str,
        item_id: str | None = None,
    ) -> StageExecution | None:
        """Get execution record for a stage.

        Args:
            stage: Stage name.
            item_id: Optional work item ID.

        Returns:
            StageExecution if found, None otherwise.
        """
        key = f"{stage}_{item_id}" if item_id else stage
        return self._executions.get(key)

    def create_attempts_dir(
        self,
        paths: "RunPaths",
        stage: str,
        attempt: int,
    ) -> Path:
        """Create directory for attempt artifacts.

        Args:
            paths: RunPaths instance.
            stage: Stage name.
            attempt: Attempt number.

        Returns:
            Path to the attempts directory.
        """
        attempts_dir = paths.logs_dir / f"{stage}.attempts" / f"attempt-{attempt:02d}"
        attempts_dir.mkdir(parents=True, exist_ok=True)
        return attempts_dir
