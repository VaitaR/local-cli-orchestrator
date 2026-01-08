"""Tests for dashboard store filesystem implementation."""

import json
from pathlib import Path

import pytest

from orx.dashboard.store.filesystem import FileSystemRunStore
from orx.dashboard.store.models import RunStatus


@pytest.fixture
def runs_root(tmp_path: Path) -> Path:
    """Create a temporary runs directory with test data."""
    runs = tmp_path / "runs"
    runs.mkdir()
    
    # Create a completed run
    run1 = runs / "test-run-001"
    run1.mkdir()
    (run1 / "meta.json").write_text(json.dumps({
        "run_id": "test-run-001",
        "task": "Test task one",
        "started_at": "2025-01-15T10:00:00Z",
        "finished_at": "2025-01-15T10:30:00Z",
        "status": "success",
        "base_branch": "main",
        "work_branch": "feature/test",
        "engine": "codex",
    }))
    (run1 / "state.json").write_text(json.dumps({
        "current_stage": "ship",
        "completed_stages": ["plan", "spec", "implement", "verify", "ship"],
        "fix_loop_count": 0,
        "last_error": None,
    }))
    (run1 / "plan.md").write_text("# Test Plan\n\nThis is a test plan.")
    (run1 / "patch.diff").write_text("diff --git a/test.py b/test.py\n+# test")
    (run1 / "run.log").write_text("INFO Starting run\nINFO Complete\n")
    
    # Create a running run
    run2 = runs / "test-run-002"
    run2.mkdir()
    (run2 / "meta.json").write_text(json.dumps({
        "run_id": "test-run-002",
        "task": "Test task two",
        "started_at": "2025-01-15T11:00:00Z",
        "finished_at": None,
        "status": "running",
        "base_branch": "main",
        "work_branch": "feature/test2",
        "engine": "gemini",
    }))
    (run2 / "state.json").write_text(json.dumps({
        "current_stage": "implement",
        "completed_stages": ["plan", "spec"],
        "fix_loop_count": 0,
        "last_error": None,
    }))
    (run2 / "plan.md").write_text("# Test Plan 2\n\nAnother test plan.")
    (run2 / "run.log").write_text("INFO Starting run\nINFO Running implement\n")
    
    return runs


@pytest.fixture
def store(runs_root: Path) -> FileSystemRunStore:
    """Create a FileSystemRunStore with test data."""
    return FileSystemRunStore(runs_root)


class TestFileSystemRunStore:
    """Tests for FileSystemRunStore."""

    def test_list_runs_returns_all_runs(self, store: FileSystemRunStore) -> None:
        """Test that list_runs returns all runs."""
        runs = store.list_runs()
        assert len(runs) == 2
        run_ids = {r.run_id for r in runs}
        assert run_ids == {"test-run-001", "test-run-002"}

    def test_list_runs_sorted_by_started_at(self, store: FileSystemRunStore) -> None:
        """Test that runs are sorted by started_at descending."""
        runs = store.list_runs()
        # Most recent first
        assert runs[0].run_id == "test-run-002"
        assert runs[1].run_id == "test-run-001"

    def test_list_active_runs(self, store: FileSystemRunStore) -> None:
        """Test filtering for active (running) runs."""
        active = store.list_active_runs()
        assert len(active) == 1
        assert active[0].run_id == "test-run-002"
        assert active[0].status == RunStatus.RUNNING

    def test_list_recent_runs(self, store: FileSystemRunStore) -> None:
        """Test filtering for recent (completed/failed) runs."""
        recent = store.list_recent_runs()
        assert len(recent) == 1
        assert recent[0].run_id == "test-run-001"
        assert recent[0].status == RunStatus.SUCCESS

    def test_get_run_detail(self, store: FileSystemRunStore) -> None:
        """Test getting detailed run information."""
        detail = store.get_run_detail("test-run-001")
        assert detail is not None
        assert detail.run_id == "test-run-001"
        assert detail.task == "Test task one"
        assert detail.current_stage == "ship"
        assert "plan" in detail.completed_stages
        assert len(detail.artifacts) > 0

    def test_get_run_detail_not_found(self, store: FileSystemRunStore) -> None:
        """Test getting a non-existent run returns None."""
        detail = store.get_run_detail("non-existent")
        assert detail is None

    def test_get_artifact_content(self, store: FileSystemRunStore) -> None:
        """Test reading artifact content."""
        content = store.get_artifact("test-run-001", "plan.md")
        assert content is not None
        assert "Test Plan" in content

    def test_get_artifact_not_found(self, store: FileSystemRunStore) -> None:
        """Test reading non-existent artifact returns None."""
        content = store.get_artifact("test-run-001", "nonexistent.txt")
        assert content is None

    def test_get_artifact_blocks_path_traversal(
        self, store: FileSystemRunStore
    ) -> None:
        """Test that path traversal is blocked."""
        content = store.get_artifact("test-run-001", "../../../etc/passwd")
        assert content is None

    def test_get_artifact_blocks_invalid_extension(
        self, store: FileSystemRunStore
    ) -> None:
        """Test that invalid file extensions are blocked."""
        content = store.get_artifact("test-run-001", "script.sh")
        assert content is None

    def test_get_diff(self, store: FileSystemRunStore) -> None:
        """Test reading the patch.diff file."""
        diff = store.get_diff("test-run-001")
        assert diff is not None
        assert "diff --git" in diff

    def test_get_diff_not_found(self, store: FileSystemRunStore) -> None:
        """Test reading diff for run without patch.diff."""
        diff = store.get_diff("test-run-002")
        assert diff is None

    def test_tail_log_from_start(self, store: FileSystemRunStore) -> None:
        """Test tailing log from the beginning."""
        chunk = store.tail_log("test-run-001", cursor=0)
        assert chunk is not None
        assert "Starting run" in chunk.content
        assert chunk.cursor > 0

    def test_tail_log_with_cursor(self, store: FileSystemRunStore) -> None:
        """Test tailing log from a cursor position."""
        # First read
        chunk1 = store.tail_log("test-run-001", cursor=0)
        assert chunk1 is not None
        
        # Read from end should return empty or less content
        chunk2 = store.tail_log("test-run-001", cursor=chunk1.cursor)
        # At end of file, content should be empty
        assert chunk2 is not None

    def test_tail_log_not_found(self, store: FileSystemRunStore) -> None:
        """Test tailing log for non-existent run."""
        chunk = store.tail_log("non-existent", cursor=0)
        assert chunk is None


class TestPathSafety:
    """Tests for path safety in FileSystemRunStore."""

    def test_allowed_extensions(self, store: FileSystemRunStore) -> None:
        """Test that allowed extensions are accepted."""
        allowed = [".md", ".json", ".log", ".diff", ".txt", ".yaml"]
        for ext in allowed:
            assert store._is_safe_path(f"file{ext}")

    def test_disallowed_extensions(self, store: FileSystemRunStore) -> None:
        """Test that disallowed extensions are rejected."""
        disallowed = [".py", ".sh", ".exe", ".bin", ""]
        for ext in disallowed:
            assert not store._is_safe_path(f"file{ext}")

    def test_path_traversal_blocked(self, store: FileSystemRunStore) -> None:
        """Test that path traversal attempts are blocked."""
        dangerous = [
            "../secret.md",
            "../../passwd",
            "foo/../../../bar.md",
            "/etc/passwd",
            "..\\..\\windows.md",
        ]
        for path in dangerous:
            assert not store._is_safe_path(path)
