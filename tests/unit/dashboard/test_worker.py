"""Tests for dashboard local worker."""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class MockConfig:
    """Mock configuration for worker tests."""

    max_concurrency: int = 2
    cancel_grace_seconds: float = 2.0
    orx_bin: str = "orx"
    runs_root: Path = Path("/tmp/test-repo/runs")
    run_id_timeout_seconds: float = 0.1
    run_id_poll_interval: float = 0.01


@pytest.fixture
def mock_config(tmp_path: Path) -> MockConfig:
    """Create a mock config for testing."""
    config = MockConfig()
    config.runs_root = tmp_path / "repo" / "runs"
    config.runs_root.parent.mkdir(parents=True, exist_ok=True)
    return config


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """Create a repository root directory."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    return repo


class TestLocalWorker:
    """Tests for LocalWorker."""

    def test_worker_starts_and_stops(self, mock_config: MockConfig) -> None:
        """Test that worker can start and stop cleanly."""
        from orx.dashboard.worker.local import LocalWorker

        worker = LocalWorker(mock_config)
        worker.start()
        assert worker._thread is not None
        assert worker._thread.is_alive()
        worker.stop()
        # After stop, thread should be None or not alive
        assert worker._thread is None or not worker._thread.is_alive()

    def test_worker_can_queue_run(
        self, mock_config: MockConfig, repo_root: Path
    ) -> None:
        """Test that worker can queue a run."""
        from orx.dashboard.worker.local import LocalWorker

        worker = LocalWorker(mock_config)
        worker.start()

        try:
            run_id = worker.start_run("Test task", repo_path=str(repo_root))
            assert run_id is not None
            assert "_" in run_id  # Format: YYYYMMDD_HHMMSS_uuid
        finally:
            worker.stop()

    def test_cancel_non_existent_run(self, mock_config: MockConfig) -> None:
        """Test that cancelling non-existent run returns False."""
        from orx.dashboard.worker.local import LocalWorker

        worker = LocalWorker(mock_config)
        result = worker.cancel_run("non-existent-run")
        assert result is False

    def test_get_pid_returns_none_for_unknown(self, mock_config: MockConfig) -> None:
        """Test that get_run_pid returns None for unknown runs."""
        from orx.dashboard.worker.local import LocalWorker

        worker = LocalWorker(mock_config)
        pid = worker.get_run_pid("unknown-run-id")
        assert pid is None

    def test_worker_handles_multiple_runs(
        self, mock_config: MockConfig, repo_root: Path
    ) -> None:
        """Test that worker can handle multiple run requests."""
        from orx.dashboard.worker.local import LocalWorker

        worker = LocalWorker(mock_config)
        worker.start()

        try:
            run_ids = []
            for i in range(3):
                run_id = worker.start_run(f"Task {i}", repo_path=str(repo_root))
                run_ids.append(run_id)

            # All run IDs should be unique
            assert len(set(run_ids)) == 3
        finally:
            worker.stop()

    def test_empty_task_raises_error(self, mock_config: MockConfig) -> None:
        """Test that empty task raises ValueError."""
        from orx.dashboard.worker.local import LocalWorker

        worker = LocalWorker(mock_config)
        with pytest.raises(ValueError, match="Task cannot be empty"):
            worker.start_run("   ")

    def test_worker_stops_gracefully(
        self, mock_config: MockConfig, repo_root: Path
    ) -> None:
        """Test that worker stops gracefully even with pending work."""
        from orx.dashboard.worker.local import LocalWorker

        worker = LocalWorker(mock_config)
        worker.start()

        # Queue some runs
        for i in range(3):
            worker.start_run(f"Task {i}", repo_path=str(repo_root))

        # Stop should not hang
        worker.stop()
        time.sleep(0.2)
        assert worker._thread is None or not worker._thread.is_alive()

    def test_cleanup_completed_removes_finished_jobs(
        self, mock_config: MockConfig
    ) -> None:
        """Ensure finished jobs are removed from active list."""
        from orx.dashboard.worker.local import LocalWorker, RunJob

        worker = LocalWorker(mock_config)
        finished_proc = MagicMock()
        finished_proc.poll.return_value = 0
        finished_proc.returncode = 0

        job = RunJob(
            run_id="test", task="t", repo_path=str(mock_config.runs_root.parent)
        )
        job.process = finished_proc
        with worker._lock:
            worker._active_jobs[job.run_id] = job

        worker._cleanup_completed()

        with worker._lock:
            assert "test" not in worker._active_jobs

    def test_cancel_run_by_pid_from_state(self, mock_config: MockConfig) -> None:
        """Cancel should fall back to pid from state.json when job not tracked."""
        from orx.dashboard.worker.local import LocalWorker

        run_id = "20260108_000000_deadbeef"
        run_dir = mock_config.runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "state.json").write_text('{"pid": 12345}')

        worker = LocalWorker(mock_config)

        with patch("os.killpg") as killpg, patch("os.kill") as kill:
            killpg.return_value = None
            kill.side_effect = ProcessLookupError()
            assert worker.cancel_run(run_id) is True
