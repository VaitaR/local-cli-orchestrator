"""State management for orx runs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import structlog

from orx.exceptions import StateError
from orx.paths import RunPaths

logger = structlog.get_logger()


class Stage(str, Enum):
    """FSM stages for the orchestrator."""

    INIT = "init"
    PLAN = "plan"
    SPEC = "spec"
    DECOMPOSE = "decompose"
    IMPLEMENT_ITEM = "implement_item"
    CAPTURE_DIFF = "capture_diff"
    VERIFY = "verify"
    FIX_LOOP = "fix_loop"
    NEXT_ITEM = "next_item"
    REVIEW = "review"
    SHIP = "ship"
    KNOWLEDGE_UPDATE = "knowledge_update"
    DONE = "done"
    FAILED = "failed"


# Stage transitions
STAGE_ORDER = [
    Stage.INIT,
    Stage.PLAN,
    Stage.SPEC,
    Stage.DECOMPOSE,
    Stage.IMPLEMENT_ITEM,
    Stage.CAPTURE_DIFF,
    Stage.VERIFY,
    Stage.REVIEW,
    Stage.SHIP,
    Stage.KNOWLEDGE_UPDATE,
    Stage.DONE,
]


@dataclass
class StageStatus:
    """Status of a stage execution.

    Attributes:
        stage: The stage.
        status: Execution status (pending/running/completed/failed).
        started_at: When the stage started.
        completed_at: When the stage completed.
        error: Error message if failed.
    """

    stage: Stage
    status: str = "pending"
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "stage": self.stage.value,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StageStatus:
        """Create from dictionary."""
        return cls(
            stage=Stage(data["stage"]),
            status=data.get("status", "pending"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error=data.get("error"),
        )


@dataclass
class RunState:
    """Complete state of a run.

    Attributes:
        run_id: The run identifier.
        current_stage: Current stage in the FSM.
        current_item_id: Current work item being processed.
        current_iteration: Current fix-loop iteration.
        baseline_sha: Git SHA of the baseline.
        stage_statuses: Status of each stage.
        last_failure_evidence: Pointers to failure evidence.
        created_at: When the run was created.
        updated_at: When the state was last updated.
    """

    run_id: str
    current_stage: Stage = Stage.INIT
    current_item_id: str | None = None
    current_iteration: int = 0
    baseline_sha: str | None = None
    stage_statuses: dict[str, StageStatus] = field(default_factory=dict)
    last_failure_evidence: dict[str, str] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "run_id": self.run_id,
            "current_stage": self.current_stage.value,
            "current_item_id": self.current_item_id,
            "current_iteration": self.current_iteration,
            "baseline_sha": self.baseline_sha,
            "stage_statuses": {k: v.to_dict() for k, v in self.stage_statuses.items()},
            "last_failure_evidence": self.last_failure_evidence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunState:
        """Create from dictionary."""
        stage_statuses = {
            k: StageStatus.from_dict(v)
            for k, v in data.get("stage_statuses", {}).items()
        }
        return cls(
            run_id=data["run_id"],
            current_stage=Stage(data.get("current_stage", "init")),
            current_item_id=data.get("current_item_id"),
            current_iteration=data.get("current_iteration", 0),
            baseline_sha=data.get("baseline_sha"),
            stage_statuses=stage_statuses,
            last_failure_evidence=data.get("last_failure_evidence", {}),
            created_at=data.get("created_at", datetime.now(tz=UTC).isoformat()),
            updated_at=data.get("updated_at", datetime.now(tz=UTC).isoformat()),
        )


class StateManager:
    """Manages run state persistence and transitions.

    Example:
        >>> paths = RunPaths.create_new(Path("/project"), "test_run")
        >>> state_mgr = StateManager(paths)
        >>> state_mgr.initialize()
        >>> state_mgr.transition_to(Stage.PLAN)
        >>> state_mgr.current_stage
        <Stage.PLAN: 'plan'>
    """

    def __init__(self, paths: RunPaths) -> None:
        """Initialize the state manager.

        Args:
            paths: RunPaths for the run.
        """
        self.paths = paths
        self._state: RunState | None = None

    @property
    def state(self) -> RunState:
        """Get the current state."""
        if self._state is None:
            msg = "State not initialized. Call initialize() or load() first."
            raise StateError(msg, run_id=self.paths.run_id)
        return self._state

    @property
    def current_stage(self) -> Stage:
        """Get the current stage."""
        return self.state.current_stage

    def initialize(self) -> RunState:
        """Initialize a new run state.

        Returns:
            The initialized RunState.
        """
        log = logger.bind(run_id=self.paths.run_id)
        log.info("Initializing run state")

        self._state = RunState(run_id=self.paths.run_id)
        self.save()
        return self._state

    def load(self) -> RunState:
        """Load state from disk.

        Returns:
            The loaded RunState.

        Raises:
            StateError: If state file doesn't exist or is invalid.
        """
        log = logger.bind(run_id=self.paths.run_id)
        state_path = self.paths.state_json

        if not state_path.exists():
            msg = f"State file not found: {state_path}"
            raise StateError(msg, run_id=self.paths.run_id)

        try:
            data = json.loads(state_path.read_text())
            self._state = RunState.from_dict(data)
            log.info("Loaded run state", stage=self._state.current_stage.value)
            return self._state
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            msg = f"Invalid state file: {e}"
            raise StateError(msg, run_id=self.paths.run_id) from e

    def save(self) -> None:
        """Save state to disk."""
        self.state.updated_at = datetime.now(tz=UTC).isoformat()
        state_path = self.paths.state_json
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(self.state.to_dict(), indent=2))
        logger.debug("Saved run state", path=str(state_path))

    def transition_to(self, stage: Stage) -> None:
        """Transition to a new stage.

        Args:
            stage: The stage to transition to.
        """
        log = logger.bind(from_stage=self.current_stage.value, to_stage=stage.value)

        # Mark previous stage as completed
        prev_stage_key = f"{self.current_stage.value}"
        if prev_stage_key in self.state.stage_statuses:
            prev_status = self.state.stage_statuses[prev_stage_key]
            if prev_status.status == "running":
                prev_status.status = "completed"
                prev_status.completed_at = datetime.now(tz=UTC).isoformat()

        # Set new stage
        self.state.current_stage = stage

        # Initialize stage status
        stage_key = f"{stage.value}"
        if stage_key not in self.state.stage_statuses:
            self.state.stage_statuses[stage_key] = StageStatus(stage=stage)

        self.state.stage_statuses[stage_key].status = "running"
        self.state.stage_statuses[stage_key].started_at = datetime.now(
            tz=UTC
        ).isoformat()

        self.save()
        log.info("Stage transition complete")

    def mark_stage_completed(self, stage: Stage | None = None) -> None:
        """Mark a stage as completed.

        Args:
            stage: The stage to mark (defaults to current).
        """
        target_stage = stage or self.current_stage
        stage_key = f"{target_stage.value}"

        if stage_key in self.state.stage_statuses:
            self.state.stage_statuses[stage_key].status = "completed"
            self.state.stage_statuses[stage_key].completed_at = datetime.now(
                tz=UTC
            ).isoformat()

        self.save()

    def mark_stage_failed(self, error: str, stage: Stage | None = None) -> None:
        """Mark a stage as failed.

        Args:
            error: Error message.
            stage: The stage to mark (defaults to current).
        """
        target_stage = stage or self.current_stage
        stage_key = f"{target_stage.value}"

        if stage_key not in self.state.stage_statuses:
            self.state.stage_statuses[stage_key] = StageStatus(stage=target_stage)

        self.state.stage_statuses[stage_key].status = "failed"
        self.state.stage_statuses[stage_key].error = error
        self.state.stage_statuses[stage_key].completed_at = datetime.now(
            tz=UTC
        ).isoformat()

        self.save()

    def set_current_item(self, item_id: str) -> None:
        """Set the current work item.

        Args:
            item_id: The work item ID.
        """
        self.state.current_item_id = item_id
        self.state.current_iteration = 0
        self.save()
        logger.debug("Set current item", item_id=item_id)

    def increment_iteration(self) -> int:
        """Increment the fix-loop iteration counter.

        Returns:
            The new iteration number.
        """
        self.state.current_iteration += 1
        self.save()
        return self.state.current_iteration

    def set_baseline_sha(self, sha: str) -> None:
        """Set the baseline SHA.

        Args:
            sha: The git SHA.
        """
        self.state.baseline_sha = sha
        self.save()
        logger.debug("Set baseline SHA", sha=sha[:8])

    def set_failure_evidence(self, evidence: dict[str, str]) -> None:
        """Set failure evidence for fix prompts.

        Args:
            evidence: Dict of evidence name to content/path.
        """
        self.state.last_failure_evidence = evidence
        self.save()

    def clear_failure_evidence(self) -> None:
        """Clear failure evidence."""
        self.state.last_failure_evidence = {}
        self.save()

    def is_resumable(self) -> bool:
        """Check if the run can be resumed.

        Returns:
            True if the run is in a resumable state.
        """
        if self._state is None:
            try:
                self.load()
            except StateError:
                return False

        # Can resume if not done or failed
        return self.current_stage not in (Stage.DONE, Stage.FAILED)

    def get_resume_point(self) -> Stage:
        """Get the stage to resume from.

        Returns:
            The stage to resume execution from.
        """
        if self._state is None:
            self.load()

        # If current stage was running, resume from there
        stage_key = f"{self.current_stage.value}"
        if stage_key in self.state.stage_statuses:
            status = self.state.stage_statuses[stage_key]
            if status.status in ("running", "pending"):
                return self.current_stage

        # Otherwise, resume from current stage
        return self.current_stage
