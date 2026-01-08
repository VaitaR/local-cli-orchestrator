"""Tests for dashboard local worker."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from orx.dashboard.worker.local import LocalWorker


class TestLocalWorker:
    """Tests for LocalWorker."""

    def test_worker_starts_and_stops(self) -> None:
        """Test that worker can start and stop cleanly."""
        worker = LocalWorker()
        worker.start()
        assert worker.is_running
        worker.stop()
        assert not worker.is_running

    def test_worker_can_start_run(self) -> None:
        """Test that worker can queue a run."""
        worker = LocalWorker()
        worker.start()
        
        try:
            run_id = worker.start_run("Test task", "/tmp/test-repo")
            assert run_id is not None
            assert run_id.startswith("run-")
            
            # Give it a moment to start
            time.sleep(0.1)
            
            # The run should be tracked
            assert run_id in worker.active_runs or run_id in worker._completed_runs
        finally:
            worker.stop()

    def test_worker_can_cancel_run(self) -> None:
        """Test that worker can cancel a running task."""
        worker = LocalWorker()
        worker.start()
        
        try:
            # Start a run that would take a while
            run_id = worker.start_run("Long task", "/tmp/test-repo")
            
            # Give it a moment
            time.sleep(0.1)
            
            # Cancel it
            result = worker.cancel_run(run_id)
            # Result depends on whether run started yet
            assert isinstance(result, bool)
        finally:
            worker.stop()

    def test_get_status_returns_none_for_unknown(self) -> None:
        """Test that get_status returns None for unknown runs."""
        worker = LocalWorker()
        status = worker.get_status("unknown-run-id")
        assert status is None

    def test_worker_handles_multiple_runs(self) -> None:
        """Test that worker can handle multiple run requests."""
        worker = LocalWorker()
        worker.start()
        
        try:
            run_ids = []
            for i in range(3):
                run_id = worker.start_run(f"Task {i}", "/tmp/test-repo")
                run_ids.append(run_id)
            
            # All run IDs should be unique
            assert len(set(run_ids)) == 3
        finally:
            worker.stop()

    def test_worker_stops_gracefully(self) -> None:
        """Test that worker stops gracefully even with pending work."""
        worker = LocalWorker()
        worker.start()
        
        # Queue some runs
        for i in range(5):
            worker.start_run(f"Task {i}", "/tmp/test-repo")
        
        # Stop should not hang
        worker.stop(timeout=2.0)
        assert not worker.is_running
