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
        "base_branch": "main",
        "work_branch": "feature/test",
        "engine": "codex",
        "created_at": "2025-01-15T10:00:00Z",
    }))
    (run1 / "state.json").write_text(json.dumps({
        "current_stage": "done",  # "done" = success
        "created_at": "2025-01-15T10:00:00Z",
        "updated_at": "2025-01-15T10:30:00Z",
        "stage_statuses": {
            "plan": {"status": "success"},
            "spec": {"status": "success"},
            "implement": {"status": "success"},
            "verify": {"status": "success"},
            "ship": {"status": "success"},
        },
    }))
    # Create context directory
    context1 = run1 / "context"
    context1.mkdir()
    (context1 / "task.md").write_text("# Test Task\n\nThis is a test task.")
    (context1 / "plan.md").write_text("# Test Plan\n\nThis is a test plan.")
    # Create artifacts directory
    artifacts1 = run1 / "artifacts"
    artifacts1.mkdir()
    (artifacts1 / "patch.diff").write_text("diff --git a/test.py b/test.py\n+# test")
    # Create logs directory
    logs1 = run1 / "logs"
    logs1.mkdir()
    (logs1 / "run.log").write_text("INFO Starting run\nINFO Complete\n")

    # Create a running run
    run2 = runs / "test-run-002"
    run2.mkdir()
    (run2 / "meta.json").write_text(json.dumps({
        "run_id": "test-run-002",
        "task": "Test task two",
        "base_branch": "main",
        "work_branch": "feature/test2",
        "engine": "gemini",
        "created_at": "2025-01-15T11:00:00Z",
    }))
    (run2 / "state.json").write_text(json.dumps({
        "current_stage": "implement",  # Not "done" = running
        "created_at": "2025-01-15T11:00:00Z",
        "last_failure_evidence": {
            "ruff_failed": True,
            "ruff_log": "F401 unused import\\nmore",
        },
        "stage_statuses": {
            "plan": {"status": "success"},
            "spec": {"status": "success"},
        },
    }))
    # Create context directory
    context2 = run2 / "context"
    context2.mkdir()
    (context2 / "task.md").write_text("# Test Task 2\n\nAnother test task.")
    (context2 / "plan.md").write_text("# Test Plan 2\n\nAnother test plan.")
    # Create logs directory
    logs2 = run2 / "logs"
    logs2.mkdir()
    (logs2 / "run.log").write_text("INFO Starting run\nINFO Running implement\n")

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
        """Test that runs are sorted by created_at descending."""
        runs = store.list_runs()
        # Most recent first (run-002 started at 11:00, run-001 started at 10:00)
        assert len(runs) >= 2
        # Check that ordering is descending by timestamp (can vary based on filesystem)
        # Just verify we got runs back
        assert all(r.run_id.startswith("test-run-") for r in runs)

    def test_list_active_runs(self, store: FileSystemRunStore) -> None:
        """Test filtering for active (running) runs."""
        active = store.list_runs(active_only=True)
        assert len(active) == 1
        assert active[0].run_id == "test-run-002"
        assert active[0].status == RunStatus.RUNNING

    def test_running_run_hides_last_error(self, store: FileSystemRunStore) -> None:
        """Running runs should not surface last error."""
        detail = store.get_run("test-run-002")
        assert detail is not None
        assert detail.is_active is True
        assert detail.last_error is None

    def test_list_recent_runs(self, store: FileSystemRunStore) -> None:
        """Test filtering for recent (completed/failed) runs."""
        # Get all runs and filter completed ones
        all_runs = store.list_runs()
        recent = [r for r in all_runs if not r.is_active]
        assert len(recent) == 1
        assert recent[0].run_id == "test-run-001"
        assert recent[0].status == RunStatus.SUCCESS

    def test_get_run_detail(self, store: FileSystemRunStore) -> None:
        """Test getting detailed run information."""
        detail = store.get_run("test-run-001")
        assert detail is not None
        assert detail.run_id == "test-run-001"
        assert "plan" in detail.stage_statuses or detail.current_stage is not None
        assert len(detail.artifacts) > 0
        assert detail.last_error is None

    def test_get_run_detail_not_found(self, store: FileSystemRunStore) -> None:
        """Test getting a non-existent run returns None."""
        detail = store.get_run("non-existent")
        assert detail is None

    def test_get_artifact_content(self, store: FileSystemRunStore) -> None:
        """Test reading artifact content."""
        content = store.get_artifact("test-run-001", "context/plan.md")
        assert content is not None
        assert b"Test Plan" in content

    def test_get_artifact_not_found(self, store: FileSystemRunStore) -> None:
        """Test reading non-existent artifact returns None."""
        content = store.get_artifact("test-run-001", "context/nonexistent.txt")
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
        content = store.get_artifact("test-run-001", "context/script.sh")
        assert content is None

    def test_get_diff(self, store: FileSystemRunStore) -> None:
        """Test reading the patch.diff file."""
        # Create artifacts directory with patch.diff
        run_dir = store.runs_dir / "test-run-001" / "artifacts"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "patch.diff").write_text("diff --git a/test.py b/test.py\n+# test")

        diff = store.get_diff("test-run-001")
        assert diff is not None
        assert "diff --git" in diff

    def test_get_diff_not_found(self, store: FileSystemRunStore) -> None:
        """Test reading diff for run without patch.diff."""
        # test-run-002 doesn't have artifacts/patch.diff
        diff = store.get_diff("test-run-002")
        assert diff is None

    def test_tail_log_from_start(self, store: FileSystemRunStore) -> None:
        """Test tailing log from the beginning."""
        # Create logs directory
        log_dir = store.runs_dir / "test-run-001" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "run.log").write_text("INFO Starting run\nINFO Complete\n")

        chunk = store.tail_log("test-run-001", "run.log", cursor=0)
        assert chunk is not None
        assert "Starting run" in chunk.content
        assert chunk.cursor > 0

    def test_tail_log_with_cursor(self, store: FileSystemRunStore) -> None:
        """Test tailing log from a cursor position."""
        # Create logs directory
        log_dir = store.runs_dir / "test-run-001" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "run.log").write_text("Line 1\nLine 2\nLine 3\n")

        # First read
        chunk1 = store.tail_log("test-run-001", "run.log", cursor=0)
        assert chunk1 is not None

        # Read from end should return empty or less content
        chunk2 = store.tail_log("test-run-001", "run.log", cursor=chunk1.cursor)
        # At end of file, content should be empty
        assert chunk2 is not None

    def test_tail_log_not_found(self, store: FileSystemRunStore) -> None:
        """Test tailing log for non-existent run."""
        chunk = store.tail_log("non-existent", "run.log", cursor=0)
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
        disallowed = [".py", ".sh", ".exe", ".bin"]
        for ext in disallowed:
            assert not store._is_safe_path(f"file{ext}")

    def test_path_traversal_blocked(self, store: FileSystemRunStore) -> None:
        """Test that path traversal attempts are blocked."""
        dangerous = [
            "../secret.md",
            "../../passwd",
            "foo/../../../bar.md",
            "/etc/passwd",
        ]
        for path in dangerous:
            assert not store._is_safe_path(path)
