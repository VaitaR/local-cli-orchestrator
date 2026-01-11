"""FastAPI integration tests for dashboard timer display.

These tests verify that dashboard pages render timer data attributes
and start time displays correctly for real-time tracking.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orx.dashboard.server import create_app


@pytest.fixture
def runs_root(tmp_path: Path) -> Path:
    """Create a temporary runs directory with test data."""
    runs = tmp_path / "runs"
    runs.mkdir()

    # Create a completed run with known timestamps
    run1 = runs / "completed-run-001"
    run1.mkdir()
    created_at_1 = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
    updated_at_1 = datetime(2025, 1, 15, 10, 30, 45, tzinfo=UTC)

    (run1 / "meta.json").write_text(
        json.dumps(
            {
                "run_id": "completed-run-001",
                "task": "Completed test task",
                "base_branch": "main",
                "work_branch": "feature/completed",
                "engine": "codex",
                "created_at": created_at_1.isoformat(),
            }
        )
    )
    (run1 / "state.json").write_text(
        json.dumps(
            {
                "current_stage": "done",
                "created_at": created_at_1.isoformat(),
                "updated_at": updated_at_1.isoformat(),
                "stage_statuses": {
                    "plan": {"status": "success"},
                    "implement": {"status": "success"},
                    "ship": {"status": "success"},
                },
            }
        )
    )
    (run1 / "context").mkdir()
    (run1 / "artifacts").mkdir()

    # Create an active run with known start time
    run2 = runs / "active-run-002"
    run2.mkdir()
    created_at_2 = datetime(2025, 1, 15, 11, 15, 30, tzinfo=UTC)

    (run2 / "meta.json").write_text(
        json.dumps(
            {
                "run_id": "active-run-002",
                "task": "Active test task",
                "base_branch": "main",
                "work_branch": "feature/active",
                "engine": "gemini",
                "created_at": created_at_2.isoformat(),
            }
        )
    )
    (run2 / "state.json").write_text(
        json.dumps(
            {
                "current_stage": "implement",
                "created_at": created_at_2.isoformat(),
                "stage_statuses": {
                    "plan": {"status": "success"},
                    "spec": {"status": "success"},
                },
            }
        )
    )
    (run2 / "context").mkdir()
    (run2 / "logs").mkdir()

    # Create a failed run
    run3 = runs / "failed-run-003"
    run3.mkdir()
    created_at_3 = datetime(2025, 1, 15, 9, 45, 0, tzinfo=UTC)
    updated_at_3 = datetime(2025, 1, 15, 9, 50, 0, tzinfo=UTC)

    (run3 / "meta.json").write_text(
        json.dumps(
            {
                "run_id": "failed-run-003",
                "task": "Failed test task",
                "base_branch": "main",
                "work_branch": "feature/failed",
                "engine": "codex",
                "created_at": created_at_3.isoformat(),
            }
        )
    )
    (run3 / "state.json").write_text(
        json.dumps(
            {
                "current_stage": "failed",
                "created_at": created_at_3.isoformat(),
                "updated_at": updated_at_3.isoformat(),
                "last_failure_evidence": {
                    "category": "test_failure",
                    "message": "Tests failed",
                },
            }
        )
    )
    (run3 / "context").mkdir()

    return runs


@pytest.fixture
def client(runs_root: Path) -> TestClient:
    """Create a test client with configured runs directory."""
    from orx.dashboard.config import DashboardConfig

    config = DashboardConfig(runs_dir=runs_root)
    app = create_app(config)
    return TestClient(app)


class TestActiveRunsTimerDisplay:
    """Tests for active runs page timer display."""

    def test_active_runs_page_displays_data_started_at_attribute(
        self, client: TestClient
    ) -> None:
        """Test that active runs page displays data-started-at attribute with ISO timestamp."""
        response = client.get("/partials/active-runs")
        assert response.status_code == 200
        html = response.text

        # Check for data-started-at attribute with ISO timestamp
        assert 'data-started-at="2025-01-15T11:15:30+00:00"' in html

    def test_active_runs_page_includes_data_run_status_running(
        self, client: TestClient
    ) -> None:
        """Test that active runs page includes data-run-status='running' for active runs."""
        response = client.get("/partials/active-runs")
        assert response.status_code == 200
        html = response.text

        # Check for data-run-status attribute with 'running' value
        assert 'data-run-status="running"' in html

    def test_active_runs_page_displays_start_time_in_short_format(
        self, client: TestClient
    ) -> None:
        """Test that active runs page displays start time in short format (HH:MM)."""
        response = client.get("/partials/active-runs")
        assert response.status_code == 200
        html = response.text

        # Check for short time format display
        assert "11:15" in html

    def test_active_runs_page_includes_elapsed_human_display(
        self, client: TestClient
    ) -> None:
        """Test that active runs page shows elapsed_human duration."""
        response = client.get("/partials/active-runs")
        assert response.status_code == 200
        html = response.text

        # Check for elapsed time display (should show something like "Xm Ys" or "Xs")
        # The exact value depends on current time, so we just check the structure
        assert "data-timer-for" in html


class TestRecentRunsTimerDisplay:
    """Tests for recent/completed runs page timer display."""

    def test_completed_runs_page_shows_static_elapsed_human_duration(
        self, client: TestClient
    ) -> None:
        """Test that completed runs page shows static elapsed_human duration."""
        response = client.get("/partials/recent-runs")
        assert response.status_code == 200
        html = response.text

        # Completed run should show static duration
        # The run took 30m 45s (10:00:00 to 10:30:45)
        assert "30m 45s" in html

    def test_completed_runs_page_displays_data_started_at_attribute(
        self, client: TestClient
    ) -> None:
        """Test that completed runs page displays data-started-at attribute."""
        response = client.get("/partials/recent-runs")
        assert response.status_code == 200
        html = response.text

        # Check for data-started-at attribute
        assert 'data-started-at="2025-01-15T10:00:00+00:00"' in html

    def test_completed_runs_page_includes_data_run_status(
        self, client: TestClient
    ) -> None:
        """Test that completed runs page includes correct data-run-status."""
        response = client.get("/partials/recent-runs")
        assert response.status_code == 200
        html = response.text

        # Should have 'success' status for completed run
        assert 'data-run-status="success"' in html

    def test_failed_run_shows_correct_status(self, client: TestClient) -> None:
        """Test that failed runs display correct status."""
        response = client.get("/partials/recent-runs")
        assert response.status_code == 200
        html = response.text

        # Should have 'fail' status for failed run
        assert 'data-run-status="fail"' in html


class TestRunDetailTimerDisplay:
    """Tests for run detail page timer display."""

    def test_run_detail_page_displays_start_time_in_header(
        self, client: TestClient
    ) -> None:
        """Test that run detail page displays start time in header."""
        response = client.get("/runs/active-run-002")
        assert response.status_code == 200
        html = response.text

        # Check for "Started" label and short time format
        assert "Started" in html
        assert "11:15" in html

    def test_run_detail_header_includes_timer_data_attributes(
        self, client: TestClient
    ) -> None:
        """Test that run detail header includes timer data attributes."""
        response = client.get("/runs/completed-run-001")
        assert response.status_code == 200
        html = response.text

        # Check for timer data attributes
        assert 'data-started-at="2025-01-15T10:00:00+00:00"' in html
        assert 'data-run-status="success"' in html
        assert "data-timer-for" in html

    def test_run_detail_page_for_completed_run_shows_static_duration(
        self, client: TestClient
    ) -> None:
        """Test that run detail page for completed run shows static duration."""
        response = client.get("/runs/completed-run-001")
        assert response.status_code == 200
        html = response.text

        # Check for elapsed duration
        assert "Elapsed" in html
        assert "30m 45s" in html


class TestHTMXPartialSwapTimerAttributes:
    """Tests for HTMX partial swap timer data attributes."""

    def test_active_runs_partial_includes_all_timer_attributes(
        self, client: TestClient
    ) -> None:
        """Test that active runs HTMX partial includes all timer attributes."""
        response = client.get("/partials/active-runs")
        assert response.status_code == 200
        html = response.text

        # Check for all timer-related attributes
        assert "data-timer-for=" in html
        assert "data-started-at=" in html
        assert "data-run-status=" in html

    def test_run_header_partial_includes_timer_attributes(
        self, client: TestClient
    ) -> None:
        """Test that run header HTMX partial includes timer attributes."""
        response = client.get("/partials/run-header/active-run-002")
        assert response.status_code == 200
        html = response.text

        # Check for timer attributes in run header
        assert 'data-started-at="2025-01-15T11:15:30+00:00"' in html
        assert 'data-run-status="running"' in html
        assert 'data-timer-for="active-run-002"' in html

    def test_run_header_partial_displays_start_time(
        self, client: TestClient
    ) -> None:
        """Test that run header partial displays start time in short format."""
        response = client.get("/partials/run-header/active-run-002")
        assert response.status_code == 200
        html = response.text

        # Check for short time format
        assert "Started" in html
        assert "11:15" in html

    def test_completed_run_header_shows_correct_status(
        self, client: TestClient
    ) -> None:
        """Test that completed run header shows correct status and static duration."""
        response = client.get("/partials/run-header/completed-run-001")
        assert response.status_code == 200
        html = response.text

        # Check for success status
        assert 'data-run-status="success"' in html
        assert "30m 45s" in html


class TestTimerDataAttributeFormats:
    """Tests for timer data attribute format consistency."""

    def test_data_started_at_uses_iso8601_format(
        self, client: TestClient
    ) -> None:
        """Test that data-started-at uses ISO 8601 format with timezone."""
        response = client.get("/partials/active-runs")
        assert response.status_code == 200
        html = response.text

        # ISO 8601 format should include timezone (+00:00 for UTC)
        assert "T" in html  # Date/time separator
        assert "+00:00" in html  # UTC timezone indicator

    def test_data_run_status_matches_status_enum(
        self, client: TestClient
    ) -> None:
        """Test that data-run-status values match RunStatus enum values."""
        response = client.get("/partials/recent-runs")
        assert response.status_code == 200
        html = response.text

        # Check that status values match enum
        assert 'data-run-status="success"' in html
        assert 'data-run-status="fail"' in html

        response = client.get("/partials/active-runs")
        assert response.status_code == 200
        html = response.text

        assert 'data-run-status="running"' in html

    def test_data_timer_for_matches_run_id(
        self, client: TestClient
    ) -> None:
        """Test that data-timer-for attribute matches run ID."""
        response = client.get("/partials/active-runs")
        assert response.status_code == 200
        html = response.text

        # Check that timer-for attribute contains run ID
        assert 'data-timer-for="active-run-002"' in html
