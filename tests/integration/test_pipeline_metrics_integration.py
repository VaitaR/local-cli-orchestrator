"""Integration test for custom pipeline metrics in dashboard."""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from orx.dashboard.store.filesystem import FileSystemRunStore
from orx.metrics.schema import StageMetrics, StageStatus, TokenUsage
from orx.metrics.writer import MetricsWriter
from orx.paths import RunPaths


@pytest.fixture
def temp_runs_dir():
    """Create temporary runs directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        runs_dir = Path(tmpdir) / "runs"
        runs_dir.mkdir()
        yield runs_dir


@pytest.fixture
def run_id():
    """Test run ID."""
    return "test-custom-pipeline-run"


@pytest.fixture
def run_paths(temp_runs_dir, run_id):
    """Create run paths for testing."""
    # RunPaths expects base_dir and run_id separately
    paths = RunPaths(base_dir=temp_runs_dir.parent, run_id=run_id)
    paths.create_directories()
    return paths


class TestCustomPipelineMetrics:
    """Tests for dashboard reading custom pipeline metrics."""

    def test_get_stage_metrics_custom_pipeline(self, run_paths):
        """Test that get_stage_metrics reads stages.jsonl for custom pipelines."""
        from orx.dashboard.store.filesystem import FileSystemRunStore

        # Create custom pipeline stage metrics (non-standard stage names)
        custom_stages = [
            StageMetrics(
                run_id=run_paths.run_id,
                stage="custom_analysis",
                start_ts=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC).isoformat(),
                end_ts=datetime(2024, 1, 1, 10, 0, 5, tzinfo=UTC).isoformat(),
                duration_ms=5000,
                status=StageStatus.SUCCESS,
                tokens=TokenUsage(input=1000, output=500, total=1500),
            ),
            StageMetrics(
                run_id=run_paths.run_id,
                stage="data_processing",
                start_ts=datetime(2024, 1, 1, 10, 0, 5, tzinfo=UTC).isoformat(),
                end_ts=datetime(2024, 1, 1, 10, 0, 15, tzinfo=UTC).isoformat(),
                duration_ms=10000,
                status=StageStatus.SUCCESS,
                tokens=TokenUsage(input=2000, output=1000, total=3000),
            ),
            StageMetrics(
                run_id=run_paths.run_id,
                stage="custom_output",
                start_ts=datetime(2024, 1, 1, 10, 0, 15, tzinfo=UTC).isoformat(),
                end_ts=datetime(2024, 1, 1, 10, 0, 17, tzinfo=UTC).isoformat(),
                duration_ms=2000,
                status=StageStatus.FAIL,
                failure_message="Custom stage failed",
            ),
        ]

        # Write metrics
        writer = MetricsWriter(run_paths)
        for stage_metric in custom_stages:
            writer.write_stage(stage_metric)

        # Read back through store
        store = FileSystemRunStore(run_paths.run_dir.parent)
        stage_metrics = store.get_stage_metrics(run_paths.run_id)

        # Verify all custom stages are read
        assert len(stage_metrics) == 3
        assert stage_metrics[0]["stage"] == "custom_analysis"
        assert stage_metrics[1]["stage"] == "data_processing"
        assert stage_metrics[2]["stage"] == "custom_output"

        # Verify metrics data
        assert stage_metrics[0]["duration_ms"] == 5000
        assert stage_metrics[0]["status"] == "success"
        assert stage_metrics[0]["tokens"]["total"] == 1500

        assert stage_metrics[2]["status"] == "fail"
        assert stage_metrics[2]["failure_message"] == "Custom stage failed"

    def test_build_metrics_context_custom_stages(self):
        """Test that _build_metrics_context renders any stage name dynamically."""
        from orx.dashboard.handlers.partials import _build_metrics_context

        # Custom stage metrics (non-standard names)
        stage_metrics = [
            {
                "stage": "extract_data",
                "duration_ms": 3000,
                "status": "success",
                "tokens": {"input": 500, "output": 200, "total": 700},
                "model": "claude-3-opus",
            },
            {
                "stage": "transform_results",
                "duration_ms": 5000,
                "status": "success",
                "tokens": {"input": 1000, "output": 800, "total": 1800},
                "model": "claude-3-sonnet",
            },
            {
                "stage": "load_to_db",
                "duration_ms": 2000,
                "status": "fail",
                "failure_message": "Connection timeout",
            },
        ]

        # Run metrics (empty - testing fallback behavior)
        run_metrics = {}

        # Build context
        context = _build_metrics_context(
            run_metrics=run_metrics,
            stage_metrics=stage_metrics,
            fallback_duration_ms=10000,
            fallback_model="claude-3-opus",
        )

        # Verify stages are rendered
        assert "stages" in context
        assert len(context["stages"]) == 3

        # Check custom stage names are preserved
        stage_names = [s["name"] for s in context["stages"]]
        assert "extract_data" in stage_names
        assert "transform_results" in stage_names
        assert "load_to_db" in stage_names

        # Verify metrics data
        extract_stage = next(s for s in context["stages"] if s["name"] == "extract_data")
        assert extract_stage["duration"] == 3.0
        assert extract_stage["status"] == "success"
        assert extract_stage["tokens"] == 700
        assert extract_stage["model"] == "claude-3-opus"

        # Verify failed stage
        load_stage = next(s for s in context["stages"] if s["name"] == "load_to_db")
        assert load_stage["status"] == "fail"
        assert load_stage["error"] == "Connection timeout"

    def test_end_to_end_custom_pipeline_metrics(self, run_paths, run_id):
        """Test end-to-end: custom pipeline run → stages.jsonl → dashboard displays metrics."""
        # Create custom pipeline metrics
        writer = MetricsWriter(run_paths)

        custom_stages = [
            StageMetrics(
                run_id=run_id,
                stage="etl_extract",
                start_ts=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC).isoformat(),
                end_ts=datetime(2024, 1, 1, 12, 0, 3, tzinfo=UTC).isoformat(),
                duration_ms=3000,
                status=StageStatus.SUCCESS,
                tokens=TokenUsage(input=1500, output=500, total=2000),
            ),
            StageMetrics(
                run_id=run_id,
                stage="etl_transform",
                start_ts=datetime(2024, 1, 1, 12, 0, 3, tzinfo=UTC).isoformat(),
                end_ts=datetime(2024, 1, 1, 12, 0, 10, tzinfo=UTC).isoformat(),
                duration_ms=7000,
                status=StageStatus.SUCCESS,
                tokens=TokenUsage(input=3000, output=2000, total=5000),
            ),
            StageMetrics(
                run_id=run_id,
                stage="etl_load",
                start_ts=datetime(2024, 1, 1, 12, 0, 10, tzinfo=UTC).isoformat(),
                end_ts=datetime(2024, 1, 1, 12, 0, 12, tzinfo=UTC).isoformat(),
                duration_ms=2000,
                status=StageStatus.SUCCESS,
                tokens=TokenUsage(input=1000, output=500, total=1500),
            ),
        ]

        for stage_metric in custom_stages:
            writer.write_stage(stage_metric)

        # Create minimal run.json for summary display
        run_json = run_paths.run_dir / "metrics" / "run.json"
        run_json.parent.mkdir(parents=True, exist_ok=True)
        run_json.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "start_ts": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC).isoformat(),
                    "final_status": "success",
                    "total_duration_ms": 12000,
                    "stages_executed": 3,
                    "tokens": {
                        "input": 5500,
                        "output": 3000,
                        "total": 8500,
                    },
                }
            )
        )

        # Create state.json for run detail
        state_json = run_paths.run_dir / "state.json"
        state_json.write_text(
            json.dumps(
                {
                    "current_stage": "done",
                    "created_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC).isoformat(),
                    "updated_at": datetime(2024, 1, 1, 12, 0, 12, tzinfo=UTC).isoformat(),
                    "stage_statuses": {
                        "etl_extract": {"status": "success"},
                        "etl_transform": {"status": "success"},
                        "etl_load": {"status": "success"},
                    },
                }
            )
        )

        # Create meta.json
        meta_json = run_paths.run_dir / "meta.json"
        meta_json.write_text(
            json.dumps(
                {
                    "created_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC).isoformat(),
                    "repo_path": "/tmp/test",
                    "engine": "claude-3-opus",
                }
            )
        )

        # Verify through the store and metrics context builder
        from orx.dashboard.handlers.partials import _build_metrics_context

        store = FileSystemRunStore(run_paths.run_dir.parent)

        # Get stage metrics from store
        stage_metrics = store.get_stage_metrics(run_id)
        assert len(stage_metrics) == 3

        # Get run metrics from store
        run_metrics = store.get_run_metrics(run_id)
        assert run_metrics is not None
        assert run_metrics["stages_executed"] == 3

        # Build metrics context (what the dashboard uses)
        context = _build_metrics_context(
            run_metrics=run_metrics,
            stage_metrics=stage_metrics,
            fallback_duration_ms=12000,
            fallback_model="claude-3-opus",
        )

        # Verify custom stage names are in the context
        stage_names = [s["name"] for s in context["stages"]]
        assert "etl_extract" in stage_names
        assert "etl_transform" in stage_names
        assert "etl_load" in stage_names

        # Verify tokens are aggregated correctly
        assert context["tokens"]["total"] == 8500

        # Verify duration
        assert context["duration"] == 12.0

    def test_mixed_standard_and_custom_stages(self, run_paths):
        """Test that both standard and custom stages are displayed correctly."""
        from orx.dashboard.store.filesystem import FileSystemRunStore

        # Mix of standard and custom stages
        stages = [
            StageMetrics(
                run_id=run_paths.run_id,
                stage="plan",  # Standard
                start_ts=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC).isoformat(),
                end_ts=datetime(2024, 1, 1, 10, 0, 2, tzinfo=UTC).isoformat(),
                duration_ms=2000,
                status=StageStatus.SUCCESS,
            ),
            StageMetrics(
                run_id=run_paths.run_id,
                stage="custom_preprocess",  # Custom
                start_ts=datetime(2024, 1, 1, 10, 0, 2, tzinfo=UTC).isoformat(),
                end_ts=datetime(2024, 1, 1, 10, 0, 5, tzinfo=UTC).isoformat(),
                duration_ms=3000,
                status=StageStatus.SUCCESS,
            ),
            StageMetrics(
                run_id=run_paths.run_id,
                stage="implement",  # Standard
                start_ts=datetime(2024, 1, 1, 10, 0, 5, tzinfo=UTC).isoformat(),
                end_ts=datetime(2024, 1, 1, 10, 0, 15, tzinfo=UTC).isoformat(),
                duration_ms=10000,
                status=StageStatus.SUCCESS,
            ),
        ]

        writer = MetricsWriter(run_paths)
        for stage_metric in stages:
            writer.write_stage(stage_metric)

        # Read back
        store = FileSystemRunStore(run_paths.run_dir.parent)
        stage_metrics = store.get_stage_metrics(run_paths.run_id)

        # Verify all stages are present
        assert len(stage_metrics) == 3
        stage_names = [s["stage"] for s in stage_metrics]
        assert "plan" in stage_names
        assert "custom_preprocess" in stage_names
        assert "implement" in stage_names

    def test_empty_stages_jsonl(self, run_paths):
        """Test that empty stages.jsonl is handled gracefully."""
        from orx.dashboard.store.filesystem import FileSystemRunStore

        # Create empty stages.jsonl
        stages_jsonl = run_paths.run_dir / "metrics" / "stages.jsonl"
        stages_jsonl.parent.mkdir(parents=True, exist_ok=True)
        stages_jsonl.write_text("")

        # Read back
        store = FileSystemRunStore(run_paths.run_dir.parent)
        stage_metrics = store.get_stage_metrics(run_paths.run_id)

        # Should return empty list
        assert stage_metrics == []

    def test_missing_stages_jsonl(self, run_paths):
        """Test that missing stages.jsonl is handled gracefully."""
        from orx.dashboard.store.filesystem import FileSystemRunStore

        # Don't create stages.jsonl at all

        # Read back
        store = FileSystemRunStore(run_paths.run_dir.parent)
        stage_metrics = store.get_stage_metrics(run_paths.run_id)

        # Should return empty list
        assert stage_metrics == []
