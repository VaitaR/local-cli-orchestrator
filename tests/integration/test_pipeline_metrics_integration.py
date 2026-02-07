"""Integration tests for dashboard stage/run metrics from observability v2 events."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from orx.dashboard.store.filesystem import FileSystemRunStore
from orx.paths import RunPaths


@pytest.fixture
def temp_runs_dir() -> Generator[Path, None, None]:
    """Create temporary runs directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        runs_dir = Path(tmpdir) / "runs"
        runs_dir.mkdir()
        yield runs_dir


@pytest.fixture
def run_id() -> str:
    """Test run ID."""
    return "test-custom-pipeline-run"


@pytest.fixture
def run_paths(temp_runs_dir: Path, run_id: str) -> RunPaths:
    """Create run paths for testing."""
    paths = RunPaths(base_dir=temp_runs_dir.parent, run_id=run_id)
    paths.create_directories()
    return paths


def _event(
    *,
    run_id: str,
    step_id: int,
    ts: str,
    event_type: str,
    payload: dict[str, Any],
    source: str = "supervisor",
) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "event_id": f"e{step_id}",
        "ts": ts,
        "run_id": run_id,
        "source": source,
        "event_type": event_type,
        "step_id": step_id,
        "correlation": {},
        "payload": payload,
    }


def _write_events(run_paths: RunPaths, events: list[dict[str, Any]]) -> None:
    run_paths.observability_events_jsonl.parent.mkdir(parents=True, exist_ok=True)
    run_paths.observability_events_jsonl.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n"
    )


class TestCustomPipelineMetrics:
    """Tests for dashboard reading custom pipeline observability metrics."""

    def test_get_stage_metrics_custom_pipeline(self, run_paths: RunPaths) -> None:
        """Custom stage names should be projected from v2 stage events."""
        events = [
            _event(
                run_id=run_paths.run_id,
                step_id=1,
                ts="2024-01-01T10:00:00+00:00",
                event_type="run.start",
                payload={},
            ),
            _event(
                run_id=run_paths.run_id,
                step_id=2,
                ts="2024-01-01T10:00:00+00:00",
                event_type="stage.start",
                payload={"stage": "custom_analysis", "attempt": 1},
            ),
            _event(
                run_id=run_paths.run_id,
                step_id=3,
                ts="2024-01-01T10:00:03+00:00",
                event_type="llm.response",
                source="gateway",
                payload={
                    "stage": "custom_analysis",
                    "attempt": 1,
                    "tokens": {"input": 1000, "output": 500, "total": 1500},
                },
            ),
            _event(
                run_id=run_paths.run_id,
                step_id=4,
                ts="2024-01-01T10:00:05+00:00",
                event_type="stage.end",
                payload={
                    "stage": "custom_analysis",
                    "attempt": 1,
                    "status": "success",
                },
            ),
            _event(
                run_id=run_paths.run_id,
                step_id=5,
                ts="2024-01-01T10:00:05+00:00",
                event_type="stage.start",
                payload={"stage": "data_processing", "attempt": 1},
            ),
            _event(
                run_id=run_paths.run_id,
                step_id=6,
                ts="2024-01-01T10:00:10+00:00",
                event_type="llm.response",
                source="gateway",
                payload={
                    "stage": "data_processing",
                    "attempt": 1,
                    "tokens": {"input": 2000, "output": 1000, "total": 3000},
                },
            ),
            _event(
                run_id=run_paths.run_id,
                step_id=7,
                ts="2024-01-01T10:00:15+00:00",
                event_type="stage.end",
                payload={
                    "stage": "data_processing",
                    "attempt": 1,
                    "status": "success",
                },
            ),
            _event(
                run_id=run_paths.run_id,
                step_id=8,
                ts="2024-01-01T10:00:15+00:00",
                event_type="stage.start",
                payload={"stage": "custom_output", "attempt": 1},
            ),
            _event(
                run_id=run_paths.run_id,
                step_id=9,
                ts="2024-01-01T10:00:17+00:00",
                event_type="stage.end",
                payload={
                    "stage": "custom_output",
                    "attempt": 1,
                    "status": "failure",
                    "message": "Custom stage failed",
                },
            ),
            _event(
                run_id=run_paths.run_id,
                step_id=10,
                ts="2024-01-01T10:00:17+00:00",
                event_type="run.end",
                payload={"status": "failure"},
            ),
        ]
        _write_events(run_paths, events)

        store = FileSystemRunStore(run_paths.run_dir.parent)
        stage_metrics = store.get_stage_metrics(run_paths.run_id)

        assert len(stage_metrics) == 3
        assert stage_metrics[0]["stage"] == "custom_analysis"
        assert stage_metrics[1]["stage"] == "data_processing"
        assert stage_metrics[2]["stage"] == "custom_output"

        assert stage_metrics[0]["duration_ms"] == 5000
        assert stage_metrics[0]["status"] == "success"
        assert stage_metrics[0]["tokens"]["total"] == 1500

        assert stage_metrics[2]["status"] == "failure"
        assert stage_metrics[2]["failure_message"] == "Custom stage failed"

    def test_build_metrics_context_custom_stages(self) -> None:
        """_build_metrics_context should render arbitrary stage names."""
        from orx.dashboard.handlers.partials import _build_metrics_context

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

        run_metrics: dict[str, Any] = {}

        context = _build_metrics_context(
            run_metrics=run_metrics,
            stage_metrics=stage_metrics,
            fallback_duration_ms=10000,
            fallback_model="claude-3-opus",
        )

        assert "stages" in context
        assert len(context["stages"]) == 3

        stage_names = [s["name"] for s in context["stages"]]
        assert "extract_data" in stage_names
        assert "transform_results" in stage_names
        assert "load_to_db" in stage_names

        extract_stage = next(
            s for s in context["stages"] if s["name"] == "extract_data"
        )
        assert extract_stage["duration"] == 3.0
        assert extract_stage["status"] == "success"
        assert extract_stage["tokens"] == 700
        assert extract_stage["model"] == "claude-3-opus"

        load_stage = next(s for s in context["stages"] if s["name"] == "load_to_db")
        assert load_stage["status"] == "fail"
        assert load_stage["error"] == "Connection timeout"

    def test_end_to_end_custom_pipeline_metrics(
        self, run_paths: RunPaths, run_id: str
    ) -> None:
        """End-to-end projection should aggregate custom stages and token totals."""
        events = [
            _event(
                run_id=run_id,
                step_id=1,
                ts="2024-01-01T12:00:00+00:00",
                event_type="run.start",
                payload={},
            ),
            _event(
                run_id=run_id,
                step_id=2,
                ts="2024-01-01T12:00:00+00:00",
                event_type="stage.start",
                payload={"stage": "etl_extract", "attempt": 1},
            ),
            _event(
                run_id=run_id,
                step_id=3,
                ts="2024-01-01T12:00:02+00:00",
                event_type="llm.response",
                source="gateway",
                payload={
                    "stage": "etl_extract",
                    "attempt": 1,
                    "tokens": {"input": 1500, "output": 500, "total": 2000},
                },
            ),
            _event(
                run_id=run_id,
                step_id=4,
                ts="2024-01-01T12:00:03+00:00",
                event_type="stage.end",
                payload={"stage": "etl_extract", "attempt": 1, "status": "success"},
            ),
            _event(
                run_id=run_id,
                step_id=5,
                ts="2024-01-01T12:00:03+00:00",
                event_type="stage.start",
                payload={"stage": "etl_transform", "attempt": 1},
            ),
            _event(
                run_id=run_id,
                step_id=6,
                ts="2024-01-01T12:00:09+00:00",
                event_type="llm.response",
                source="gateway",
                payload={
                    "stage": "etl_transform",
                    "attempt": 1,
                    "tokens": {"input": 3000, "output": 2000, "total": 5000},
                },
            ),
            _event(
                run_id=run_id,
                step_id=7,
                ts="2024-01-01T12:00:10+00:00",
                event_type="stage.end",
                payload={
                    "stage": "etl_transform",
                    "attempt": 1,
                    "status": "success",
                },
            ),
            _event(
                run_id=run_id,
                step_id=8,
                ts="2024-01-01T12:00:10+00:00",
                event_type="stage.start",
                payload={"stage": "etl_load", "attempt": 1},
            ),
            _event(
                run_id=run_id,
                step_id=9,
                ts="2024-01-01T12:00:11+00:00",
                event_type="llm.response",
                source="gateway",
                payload={
                    "stage": "etl_load",
                    "attempt": 1,
                    "tokens": {"input": 1000, "output": 500, "total": 1500},
                },
            ),
            _event(
                run_id=run_id,
                step_id=10,
                ts="2024-01-01T12:00:12+00:00",
                event_type="stage.end",
                payload={"stage": "etl_load", "attempt": 1, "status": "success"},
            ),
            _event(
                run_id=run_id,
                step_id=11,
                ts="2024-01-01T12:00:12+00:00",
                event_type="run.end",
                payload={"status": "success"},
            ),
        ]
        _write_events(run_paths, events)

        from orx.dashboard.handlers.partials import _build_metrics_context

        store = FileSystemRunStore(run_paths.run_dir.parent)
        stage_metrics = store.get_stage_metrics(run_id)
        assert len(stage_metrics) == 3

        run_metrics = store.get_run_metrics(run_id)
        assert run_metrics is not None
        assert run_metrics["stages_executed"] == 3

        context = _build_metrics_context(
            run_metrics=run_metrics,
            stage_metrics=stage_metrics,
            fallback_duration_ms=12000,
            fallback_model="claude-3-opus",
        )

        stage_names = [s["name"] for s in context["stages"]]
        assert "etl_extract" in stage_names
        assert "etl_transform" in stage_names
        assert "etl_load" in stage_names

        assert context["tokens"]["total"] == 8500
        assert context["duration"] == 12.0

    def test_mixed_standard_and_custom_stages(self, run_paths: RunPaths) -> None:
        """Standard and custom stage names should both be projected."""
        events = [
            _event(
                run_id=run_paths.run_id,
                step_id=1,
                ts="2024-01-01T10:00:00+00:00",
                event_type="run.start",
                payload={},
            ),
            _event(
                run_id=run_paths.run_id,
                step_id=2,
                ts="2024-01-01T10:00:00+00:00",
                event_type="stage.start",
                payload={"stage": "plan", "attempt": 1},
            ),
            _event(
                run_id=run_paths.run_id,
                step_id=3,
                ts="2024-01-01T10:00:02+00:00",
                event_type="stage.end",
                payload={"stage": "plan", "attempt": 1, "status": "success"},
            ),
            _event(
                run_id=run_paths.run_id,
                step_id=4,
                ts="2024-01-01T10:00:02+00:00",
                event_type="stage.start",
                payload={"stage": "custom_preprocess", "attempt": 1},
            ),
            _event(
                run_id=run_paths.run_id,
                step_id=5,
                ts="2024-01-01T10:00:05+00:00",
                event_type="stage.end",
                payload={
                    "stage": "custom_preprocess",
                    "attempt": 1,
                    "status": "success",
                },
            ),
            _event(
                run_id=run_paths.run_id,
                step_id=6,
                ts="2024-01-01T10:00:05+00:00",
                event_type="stage.start",
                payload={"stage": "implement", "attempt": 1},
            ),
            _event(
                run_id=run_paths.run_id,
                step_id=7,
                ts="2024-01-01T10:00:15+00:00",
                event_type="stage.end",
                payload={"stage": "implement", "attempt": 1, "status": "success"},
            ),
            _event(
                run_id=run_paths.run_id,
                step_id=8,
                ts="2024-01-01T10:00:15+00:00",
                event_type="run.end",
                payload={"status": "success"},
            ),
        ]
        _write_events(run_paths, events)

        store = FileSystemRunStore(run_paths.run_dir.parent)
        stage_metrics = store.get_stage_metrics(run_paths.run_id)

        assert len(stage_metrics) == 3
        stage_names = [s["stage"] for s in stage_metrics]
        assert "plan" in stage_names
        assert "custom_preprocess" in stage_names
        assert "implement" in stage_names

    def test_empty_events_jsonl(self, run_paths: RunPaths) -> None:
        """Empty events.jsonl should be handled gracefully."""
        run_paths.observability_events_jsonl.parent.mkdir(parents=True, exist_ok=True)
        run_paths.observability_events_jsonl.write_text("")

        store = FileSystemRunStore(run_paths.run_dir.parent)
        stage_metrics = store.get_stage_metrics(run_paths.run_id)

        assert stage_metrics == []

    def test_missing_events_jsonl(self, run_paths: RunPaths) -> None:
        """Missing events.jsonl should be handled gracefully."""
        store = FileSystemRunStore(run_paths.run_dir.parent)
        stage_metrics = store.get_stage_metrics(run_paths.run_id)

        assert stage_metrics == []
