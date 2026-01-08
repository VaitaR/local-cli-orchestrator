"""Integration tests for dashboard API endpoints."""

import json
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
        "started_at": "2025-01-15T10:00:00Z",
        "finished_at": "2025-01-15T10:30:00Z",
        "status": "success",
        "base_branch": "main",
        "work_branch": "feature/test",
        "engine": "codex",
    }))
    (run1 / "state.json").write_text(json.dumps({
        "current_stage": "ship",
        "completed_stages": ["plan", "implement", "ship"],
        "fix_loop_count": 0,
        "last_error": None,
    }))
    (run1 / "plan.md").write_text("# Integration Test Plan\n\nTest content.")
    (run1 / "patch.diff").write_text("diff --git a/test.py b/test.py\n+# test")
    (run1 / "run.log").write_text("INFO Starting\nINFO Done\n")
    
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

    def test_runs_page_contains_run(self, client: TestClient) -> None:
        """Test that the runs page shows our test run."""
        response = client.get("/")
        assert "test-run-001" in response.text or "Integration test task" in response.text


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
        assert "test-run-001" in response.text or "Integration test" in response.text

    def test_run_header_partial(self, client: TestClient) -> None:
        """Test the run header partial endpoint."""
        response = client.get("/partials/run-header/test-run-001")
        assert response.status_code == 200

    def test_run_tab_partial(self, client: TestClient) -> None:
        """Test the run tab partial endpoint."""
        response = client.get("/partials/run-tab/test-run-001/overview")
        assert response.status_code == 200

    def test_artifact_preview_partial(self, client: TestClient) -> None:
        """Test the artifact preview partial endpoint."""
        response = client.get("/partials/artifact/test-run-001/plan.md")
        assert response.status_code == 200
        assert "Integration Test Plan" in response.text

    def test_artifact_preview_not_found(self, client: TestClient) -> None:
        """Test artifact preview for non-existent file."""
        response = client.get("/partials/artifact/test-run-001/nonexistent.md")
        assert response.status_code == 404

    def test_diff_partial(self, client: TestClient) -> None:
        """Test the diff partial endpoint."""
        response = client.get("/partials/diff/test-run-001")
        assert response.status_code == 200
        assert "diff --git" in response.text

    def test_log_tail_partial(self, client: TestClient) -> None:
        """Test the log tail partial endpoint."""
        response = client.get("/partials/log-tail/test-run-001?cursor=0")
        assert response.status_code == 200


class TestAPIEndpoints:
    """Tests for the control API endpoints."""

    def test_get_run_status(self, client: TestClient) -> None:
        """Test getting run status via API."""
        response = client.get("/api/runs/test-run-001/status")
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == "test-run-001"
        assert data["status"] == "success"

    def test_get_run_status_not_found(self, client: TestClient) -> None:
        """Test getting status for non-existent run."""
        response = client.get("/api/runs/non-existent/status")
        assert response.status_code == 404

    def test_start_run_missing_task(self, client: TestClient) -> None:
        """Test that starting run without task fails."""
        response = client.post("/api/runs/start", json={"repo_path": "/tmp/test"})
        assert response.status_code == 422  # Validation error


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
