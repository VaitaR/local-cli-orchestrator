"""Tests for dashboard local worker."""

import time
from unittest.mock import MagicMock, patch

import pytest


class MockConfig:
    """Mock configuration for worker tests."""
    max_concurrency: int = 2
    cancel_grace_seconds: float = 2.0
    orx_bin: str = "orx"


@pytest.fixture
def mock_config() -> MockConfig:
    """Create a mock config for testing."""
    return MockConfig()


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

    def test_worker_can_queue_run(self, mock_config: MockConfig) -> None:
        """Test that worker can queue a run."""
        from orx.dashboard.worker.local import LocalWorker

        worker = LocalWorker(mock_config)
        worker.start()

        try:
            run_id = worker.start_run("Test task", repo_path="/tmp/test-repo")
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

    def test_worker_handles_multiple_runs(self, mock_config: MockConfig) -> None:
        """Test that worker can handle multiple run requests."""
        from orx.dashboard.worker.local import LocalWorker

        worker = LocalWorker(mock_config)
        worker.start()

        try:
            run_ids = []
            for i in range(3):
                run_id = worker.start_run(f"Task {i}", repo_path="/tmp/test-repo")
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

    def test_worker_stops_gracefully(self, mock_config: MockConfig) -> None:
        """Test that worker stops gracefully even with pending work."""
        from orx.dashboard.worker.local import LocalWorker

        worker = LocalWorker(mock_config)
        worker.start()

        # Queue some runs
        for i in range(3):
            worker.start_run(f"Task {i}", repo_path="/tmp/test-repo")

        # Stop should not hang
        worker.stop()
        time.sleep(0.2)
        assert worker._thread is None or not worker._thread.is_alive()
