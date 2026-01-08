"""Integration tests for dashboard API endpoints."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from orx.dashboard.config import DashboardConfig
from orx.dashboard.server import create_app


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
        "task": "Integration test task",
        "base_branch": "main",
        "work_branch": "feature/test",
        "engine": "codex",
        "created_at": "2025-01-15T10:00:00Z",
    }))
    (run1 / "state.json").write_text(json.dumps({
        "current_stage": "done",
        "created_at": "2025-01-15T10:00:00Z",
        "updated_at": "2025-01-15T10:30:00Z",
        "stage_statuses": {
            "plan": {"status": "success"},
            "implement": {"status": "success"},
            "ship": {"status": "success"},
        },
    }))
    # Create context directory
    context = run1 / "context"
    context.mkdir()
    (context / "task.md").write_text("# Integration Test Task\n\nTest content.")
    (context / "plan.md").write_text("# Integration Test Plan\n\nTest content.")
    # Create artifacts directory
    artifacts = run1 / "artifacts"
    artifacts.mkdir()
    (artifacts / "patch.diff").write_text("diff --git a/test.py b/test.py\n+# test")
    # Create logs directory
    logs = run1 / "logs"
    logs.mkdir()
    (logs / "run.log").write_text("INFO Starting\nINFO Done\n")
    
    return runs


@pytest.fixture
def client(runs_root: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """Create a test client for the dashboard app."""
    # Set environment variables for config
    monkeypatch.setenv("ORX_RUNS_ROOT", str(runs_root))
    monkeypatch.setenv("ORX_DASHBOARD_HOST", "127.0.0.1")
    monkeypatch.setenv("ORX_DASHBOARD_PORT", "8421")
    
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_health_returns_ok(self, client: TestClient) -> None:
        """Test that health endpoint returns OK."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


class TestRunsListPage:
    """Tests for the runs list page."""

    def test_runs_page_loads(self, client: TestClient) -> None:
        """Test that the main runs page loads."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "ORX Dashboard" in response.text

    def test_runs_page_structure(self, client: TestClient) -> None:
        """Test that the runs page has correct structure."""
        response = client.get("/")
        assert "Active Runs" in response.text
        assert "Recent Runs" in response.text


class TestRunDetailPage:
    """Tests for the run detail page."""

    def test_run_detail_page_loads(self, client: TestClient) -> None:
        """Test that run detail page loads for existing run."""
        response = client.get("/runs/test-run-001")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_run_detail_page_not_found(self, client: TestClient) -> None:
        """Test that non-existent run returns 404 page."""
        response = client.get("/runs/non-existent")
        assert response.status_code == 404


class TestPartialEndpoints:
    """Tests for HTMX partial endpoints."""

    def test_active_runs_partial(self, client: TestClient) -> None:
        """Test the active runs partial endpoint."""
        response = client.get("/partials/active-runs")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_recent_runs_partial(self, client: TestClient) -> None:
        """Test the recent runs partial endpoint."""
        response = client.get("/partials/recent-runs")
        assert response.status_code == 200
        # Should contain our completed run
        assert "test-run-001" in response.text

    def test_run_header_partial(self, client: TestClient) -> None:
        """Test the run header partial endpoint."""
        response = client.get("/partials/run-header/test-run-001")
        assert response.status_code == 200

    def test_run_tab_overview_partial(self, client: TestClient) -> None:
        """Test the run tab partial endpoint."""
        response = client.get("/partials/run-tab/test-run-001?tab=overview")
        assert response.status_code == 200

    def test_artifact_preview_partial(self, client: TestClient) -> None:
        """Test the artifact preview partial endpoint."""
        response = client.get("/partials/artifact/test-run-001?path=context/plan.md")
        assert response.status_code == 200
        assert "Integration Test Plan" in response.text

    def test_artifact_preview_not_found(self, client: TestClient) -> None:
        """Test artifact preview for non-existent file."""
        response = client.get("/partials/artifact/test-run-001?path=context/nonexistent.md")
        assert response.status_code == 404

    def test_diff_partial(self, client: TestClient) -> None:
        """Test the diff partial endpoint."""
        response = client.get("/partials/diff/test-run-001")
        assert response.status_code == 200
        assert "diff --git" in response.text

    def test_log_tail_partial(self, client: TestClient) -> None:
        """Test the log tail partial endpoint."""
        response = client.get("/partials/log-tail/test-run-001?name=run.log&cursor=0")
        assert response.status_code == 200

    def test_active_runs_shows_running_run(self, client: TestClient) -> None:
        """Ensure active runs partial renders a running run."""
        runs_dir = client.app.state.store.runs_dir
        run_id = "running-run-001"
        run_dir = runs_dir / run_id
        run_dir.mkdir()
        (run_dir / "meta.json").write_text(json.dumps({
            "run_id": run_id,
            "task": "Still running task",
            "base_branch": "main",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }))
        (run_dir / "state.json").write_text(json.dumps({
            "current_stage": "implement",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "stage_statuses": {
                "plan": {"status": "success"},
                "implement": {"status": "running"},
            },
        }))
        (run_dir / "context").mkdir()
        (run_dir / "context" / "task.md").write_text("Running task description")

        response = client.get("/partials/active-runs")
        assert response.status_code == 200
        assert run_id in response.text

    def test_start_run_form_defaults_repo_path(self, client: TestClient) -> None:
        """Ensure start run form defaults repo path based on runs root."""
        runs_root = client.app.state.config.runs_root
        response = client.get("/partials/start-run-form")
        assert response.status_code == 200
        assert str(runs_root.parent) in response.text

class TestAPIEndpoints:
    """Tests for the control API endpoints."""

    def test_get_run_status(self, client: TestClient) -> None:
        """Test getting run status via API."""
        response = client.get("/api/runs/test-run-001/status")
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == "test-run-001"
        # Status should be success (current_stage="done")
        assert data["status"] in ("success", "running", "failed")

    def test_get_run_status_not_found(self, client: TestClient) -> None:
        """Test getting status for non-existent run."""
        response = client.get("/api/runs/non-existent/status")
        assert response.status_code == 404

    def test_start_run_missing_task(self, client: TestClient) -> None:
        """Test that starting run without task fails."""
        response = client.post("/api/runs/start", json={"repo_path": "/tmp/test"})
        assert response.status_code == 422  # Validation error

    def test_cancel_non_running_run_is_idempotent(self, client: TestClient) -> None:
        """Cancel on a completed run should return a non-error status."""
        response = client.post("/api/runs/test-run-001/cancel")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_running"
        assert data["run_id"] == "test-run-001"

    def test_cancel_run_missing_pid_returns_cannot_cancel(self, client: TestClient) -> None:
        """Runs that look active but lack pid can't be cancelled by the dashboard."""
        runs_dir = client.app.state.store.runs_dir
        run_id = "running-no-pid-001"
        run_dir = runs_dir / run_id
        run_dir.mkdir()
        (run_dir / "meta.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "task": "Running but missing pid",
                    "base_branch": "main",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        )
        (run_dir / "state.json").write_text(
            json.dumps(
                {
                    "current_stage": "implement",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "stage_statuses": {
                        "plan": {"status": "success"},
                        "implement": {"status": "running"},
                    },
                }
            )
        )
        (run_dir / "context").mkdir()
        (run_dir / "context" / "task.md").write_text("Task")

        response = client.post(f"/api/runs/{run_id}/cancel")
        assert response.status_code == 409
        data = response.json()
        assert data["status"] == "cannot_cancel"
        assert data["run_id"] == run_id


class TestStaticFiles:
    """Tests for static file serving."""

    def test_css_file_served(self, client: TestClient) -> None:
        """Test that CSS file is served."""
        response = client.get("/static/style.css")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]

    def test_htmx_file_served(self, client: TestClient) -> None:
        """Test that HTMX JS file is served."""
        response = client.get("/static/htmx.min.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]
