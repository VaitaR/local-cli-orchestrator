"""Unit test for dashboard stage progress display logic."""

import json

# Add src to path
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from orx.dashboard.store.filesystem import FileSystemRunStore
from orx.dashboard.store.models import RunStatus


@pytest.fixture
def temp_runs_dir(tmp_path):
    """Create temporary runs directory."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    return runs_dir


@pytest.fixture
def store(temp_runs_dir):
    """Create FileSystemRunStore instance."""
    # Use direct Path mode for testing
    return FileSystemRunStore(temp_runs_dir)


def create_run(runs_dir: Path, run_id: str, current_stage: str, stage_statuses: dict):
    """Helper to create a test run."""
    import os

    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Use current process PID so pid_alive check passes
    current_pid = os.getpid()

    state = {
        "run_id": run_id,
        "current_stage": current_stage,
        "stage_statuses": stage_statuses,
        "created_at": "2026-01-08T10:00:00Z",
        "updated_at": "2026-01-08T10:05:00Z",
        "pid": current_pid,  # Use current PID for active runs
        "current_item_id": None,
        "current_iteration": 0,
        "baseline_sha": "abc123",
        "last_failure_evidence": {},
    }
    (run_dir / "state.json").write_text(json.dumps(state, indent=2))

    meta = {
        "run_id": run_id,
        "task": "Test task",
        "repo_path": "/tmp/test",
        "base_branch": "main",
        "created_at": "2026-01-08T10:00:00Z",
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    context = run_dir / "context"
    context.mkdir(exist_ok=True)
    (context / "task.md").write_text("# Test Task")

    logs = run_dir / "logs"
    logs.mkdir(exist_ok=True)


def test_stage_progress_plan_running(store, temp_runs_dir):
    """Test that plan running shows correct status."""
    run_id = "test_plan_running"
    create_run(
        temp_runs_dir,
        run_id,
        "plan",
        {"plan": {"status": "running", "started_at": "2026-01-08T10:00:00Z"}},
    )

    run = store.get_run(run_id)
    assert run is not None
    assert run.status == RunStatus.RUNNING
    assert run.current_stage == "plan"
    assert "plan" in run.stage_statuses
    assert run.stage_statuses["plan"] == "running"


def test_stage_progress_spec_running_after_plan(store, temp_runs_dir):
    """Test that spec running after plan completed shows correct status."""
    run_id = "test_spec_running"
    create_run(
        temp_runs_dir,
        run_id,
        "spec",
        {
            "plan": {"status": "completed", "completed_at": "2026-01-08T10:05:00Z"},
            "spec": {"status": "running", "started_at": "2026-01-08T10:05:01Z"},
        },
    )

    run = store.get_run(run_id)
    assert run is not None
    assert run.status == RunStatus.RUNNING
    assert run.current_stage == "spec"
    assert run.stage_statuses["plan"] == "completed"
    assert run.stage_statuses["spec"] == "running"


def test_stage_progress_multiple_stages_completed(store, temp_runs_dir):
    """Test multiple stages completed with implement running."""
    run_id = "test_multi_stages"
    create_run(
        temp_runs_dir,
        run_id,
        "implement",
        {
            "plan": {"status": "completed"},
            "spec": {"status": "completed"},
            "decompose": {"status": "completed"},
            "implement": {"status": "running"},
        },
    )

    run = store.get_run(run_id)
    assert run is not None
    assert run.status == RunStatus.RUNNING
    assert run.current_stage == "implement"
    assert run.stage_statuses["plan"] == "completed"
    assert run.stage_statuses["spec"] == "completed"
    assert run.stage_statuses["decompose"] == "completed"
    assert run.stage_statuses["implement"] == "running"


def test_stage_progress_stage_failed(store, temp_runs_dir):
    """Test that failed stage shows correct status."""
    run_id = "test_stage_failed"
    create_run(
        temp_runs_dir,
        run_id,
        "spec",
        {
            "plan": {"status": "completed"},
            "spec": {"status": "failed", "error": "API capacity exhausted"},
        },
    )

    run = store.get_run(run_id)
    assert run is not None
    assert run.status == RunStatus.FAIL
    assert run.current_stage == "spec"
    assert run.stage_statuses["plan"] == "completed"
    assert run.stage_statuses["spec"] == "failed"


def test_stage_progress_run_completed(store, temp_runs_dir):
    """Test that completed run shows success status."""
    run_id = "test_completed"
    create_run(
        temp_runs_dir,
        run_id,
        "done",
        {
            "plan": {"status": "completed"},
            "spec": {"status": "completed"},
            "decompose": {"status": "completed"},
            "implement": {"status": "completed"},
            "review": {"status": "completed"},
            "ship": {"status": "completed"},
        },
    )

    run = store.get_run(run_id)
    assert run is not None
    assert run.status == RunStatus.SUCCESS
    assert run.current_stage == "done"
    assert all(status == "completed" for status in run.stage_statuses.values())


def test_stage_progress_is_active(store, temp_runs_dir):
    """Test is_active property for running stages."""
    # Running stage
    run_id = "test_active"
    create_run(temp_runs_dir, run_id, "plan", {"plan": {"status": "running"}})

    run = store.get_run(run_id)
    assert run is not None
    assert run.is_active is True

    # Completed run
    run_id2 = "test_inactive"
    create_run(temp_runs_dir, run_id2, "done", {"plan": {"status": "completed"}})

    run2 = store.get_run(run_id2)
    assert run2 is not None
    assert run2.is_active is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
