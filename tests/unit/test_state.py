"""Tests for StateManager."""

import pytest

from orx.exceptions import StateError
from orx.paths import RunPaths
from orx.state import RunState, Stage, StageStatus, StateManager


class TestStageStatus:
    """Tests for StageStatus."""

    def test_create(self) -> None:
        """Test creating a StageStatus."""
        status = StageStatus(stage=Stage.PLAN)

        assert status.stage == Stage.PLAN
        assert status.status == "pending"
        assert status.started_at is None
        assert status.completed_at is None

    def test_to_dict(self) -> None:
        """Test converting to dict."""
        status = StageStatus(
            stage=Stage.PLAN,
            status="completed",
            started_at="2024-01-01T00:00:00",
            completed_at="2024-01-01T00:01:00",
        )

        data = status.to_dict()

        assert data["stage"] == "plan"
        assert data["status"] == "completed"
        assert data["started_at"] == "2024-01-01T00:00:00"

    def test_from_dict(self) -> None:
        """Test creating from dict."""
        data = {
            "stage": "plan",
            "status": "completed",
            "started_at": "2024-01-01T00:00:00",
            "completed_at": "2024-01-01T00:01:00",
        }

        status = StageStatus.from_dict(data)

        assert status.stage == Stage.PLAN
        assert status.status == "completed"


class TestRunState:
    """Tests for RunState."""

    def test_create(self) -> None:
        """Test creating a RunState."""
        state = RunState(run_id="test_run")

        assert state.run_id == "test_run"
        assert state.current_stage == Stage.INIT
        assert state.current_item_id is None
        assert state.current_iteration == 0

    def test_to_dict(self) -> None:
        """Test converting to dict."""
        state = RunState(run_id="test_run")
        state.current_stage = Stage.PLAN
        state.baseline_sha = "abc123"

        data = state.to_dict()

        assert data["run_id"] == "test_run"
        assert data["current_stage"] == "plan"
        assert data["baseline_sha"] == "abc123"

    def test_from_dict(self) -> None:
        """Test creating from dict."""
        data = {
            "run_id": "test_run",
            "current_stage": "spec",
            "current_item_id": "W001",
            "current_iteration": 2,
            "baseline_sha": "abc123",
            "stage_statuses": {},
            "last_failure_evidence": {},
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:01:00",
        }

        state = RunState.from_dict(data)

        assert state.run_id == "test_run"
        assert state.current_stage == Stage.SPEC
        assert state.current_item_id == "W001"
        assert state.current_iteration == 2


class TestStateManager:
    """Tests for StateManager."""

    def test_initialize(self, run_paths: RunPaths) -> None:
        """Test initializing state."""
        mgr = StateManager(run_paths)
        state = mgr.initialize()

        assert state.run_id == run_paths.run_id
        assert state.current_stage == Stage.INIT
        assert run_paths.state_json.exists()

    def test_save_and_load(self, run_paths: RunPaths) -> None:
        """Test save and load roundtrip."""
        mgr = StateManager(run_paths)
        mgr.initialize()

        # Modify state
        mgr.transition_to(Stage.PLAN)
        mgr.set_baseline_sha("abc123")

        # Create new manager and load
        mgr2 = StateManager(run_paths)
        state = mgr2.load()

        assert state.current_stage == Stage.PLAN
        assert state.baseline_sha == "abc123"

    def test_transition_to(self, run_paths: RunPaths) -> None:
        """Test stage transitions."""
        mgr = StateManager(run_paths)
        mgr.initialize()

        assert mgr.current_stage == Stage.INIT

        mgr.transition_to(Stage.PLAN)
        assert mgr.current_stage == Stage.PLAN

        # Check stage status was created
        assert "plan" in mgr.state.stage_statuses
        assert mgr.state.stage_statuses["plan"].status == "running"

    def test_mark_stage_completed(self, run_paths: RunPaths) -> None:
        """Test marking stage as completed."""
        mgr = StateManager(run_paths)
        mgr.initialize()
        mgr.transition_to(Stage.PLAN)

        mgr.mark_stage_completed()

        assert mgr.state.stage_statuses["plan"].status == "completed"
        assert mgr.state.stage_statuses["plan"].completed_at is not None

    def test_mark_stage_failed(self, run_paths: RunPaths) -> None:
        """Test marking stage as failed."""
        mgr = StateManager(run_paths)
        mgr.initialize()
        mgr.transition_to(Stage.PLAN)

        mgr.mark_stage_failed("Something went wrong")

        assert mgr.state.stage_statuses["plan"].status == "failed"
        assert mgr.state.stage_statuses["plan"].error == "Something went wrong"

    def test_set_current_item(self, run_paths: RunPaths) -> None:
        """Test setting current work item."""
        mgr = StateManager(run_paths)
        mgr.initialize()

        mgr.set_current_item("W001")

        assert mgr.state.current_item_id == "W001"
        assert mgr.state.current_iteration == 0

    def test_increment_iteration(self, run_paths: RunPaths) -> None:
        """Test incrementing iteration counter."""
        mgr = StateManager(run_paths)
        mgr.initialize()
        mgr.set_current_item("W001")

        assert mgr.state.current_iteration == 0

        new_count = mgr.increment_iteration()
        assert new_count == 1
        assert mgr.state.current_iteration == 1

        new_count = mgr.increment_iteration()
        assert new_count == 2

    def test_set_baseline_sha(self, run_paths: RunPaths) -> None:
        """Test setting baseline SHA."""
        mgr = StateManager(run_paths)
        mgr.initialize()

        mgr.set_baseline_sha("abc123def456")

        assert mgr.state.baseline_sha == "abc123def456"

    def test_failure_evidence(self, run_paths: RunPaths) -> None:
        """Test failure evidence management."""
        mgr = StateManager(run_paths)
        mgr.initialize()

        evidence = {"ruff_log": "error details", "diff_empty": True}
        mgr.set_failure_evidence(evidence)

        assert mgr.state.last_failure_evidence == evidence

        mgr.clear_failure_evidence()
        assert mgr.state.last_failure_evidence == {}

    def test_is_resumable(self, run_paths: RunPaths) -> None:
        """Test resumability check."""
        mgr = StateManager(run_paths)
        mgr.initialize()

        # Should be resumable in INIT
        assert mgr.is_resumable()

        # Should be resumable in PLAN
        mgr.transition_to(Stage.PLAN)
        assert mgr.is_resumable()

        # Should not be resumable when DONE
        mgr.transition_to(Stage.DONE)
        assert not mgr.is_resumable()

    def test_is_resumable_when_failed(self, run_paths: RunPaths) -> None:
        """Test that FAILED state is not resumable."""
        mgr = StateManager(run_paths)
        mgr.initialize()
        mgr.transition_to(Stage.FAILED)

        assert not mgr.is_resumable()

    def test_get_resume_point(self, run_paths: RunPaths) -> None:
        """Test getting resume point."""
        mgr = StateManager(run_paths)
        mgr.initialize()
        mgr.transition_to(Stage.SPEC)

        # Resume point should be current stage
        assert mgr.get_resume_point() == Stage.SPEC

    def test_load_nonexistent(self, run_paths: RunPaths) -> None:
        """Test loading nonexistent state file."""
        mgr = StateManager(run_paths)

        # Don't initialize, just try to load
        with pytest.raises(StateError, match="not found"):
            mgr.load()

    def test_state_not_initialized(self, run_paths: RunPaths) -> None:
        """Test accessing state before initialization."""
        mgr = StateManager(run_paths)

        with pytest.raises(StateError, match="not initialized"):
            _ = mgr.state
