"""Dashboard metrics context tests backed by observability v2 events."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orx.dashboard.handlers.partials import _build_metrics_context
from orx.dashboard.store.filesystem import FileSystemRunStore


def _event(
    run_id: str,
    step_id: int,
    event_type: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "event_id": f"e{step_id}",
        "ts": f"2026-01-11T13:44:{step_id:02d}+00:00",
        "run_id": run_id,
        "source": "supervisor",
        "event_type": event_type,
        "step_id": step_id,
        "correlation": {},
        "payload": payload or {},
    }


@pytest.fixture
def temp_run_dir(tmp_path: Path) -> Path:
    run_id = "test_run_20260111_134427"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "logs").mkdir()
    (run_dir / "artifacts").mkdir()
    (run_dir / "context").mkdir()
    (run_dir / "observability").mkdir()

    (run_dir / "meta.json").write_text(
        json.dumps(
            {
                "created_at": "2026-01-11T13:44:27+00:00",
                "repo_path": "/fake/repo",
                "engine": "codex",
            }
        )
    )
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "current_stage": "done",
                "stage_statuses": {},
                "created_at": "2026-01-11T13:44:27+00:00",
                "updated_at": "2026-01-11T13:50:00+00:00",
            }
        )
    )

    events = [
        _event(run_id, 1, "run.start"),
        _event(run_id, 2, "stage.start", {"stage": "plan", "attempt": 1, "executor": "codex", "model": "gpt-4"}),
        _event(
            run_id,
            3,
            "llm.response",
            {"stage": "plan", "attempt": 1, "tokens": {"input": 1000, "output": 500, "total": 1500, "tool_calls": 10}},
        ),
        _event(
            run_id,
            4,
            "stage.end",
            {"stage": "plan", "attempt": 1, "status": "success", "duration_ms": 330000},
        ),
        _event(run_id, 5, "run.end", {"status": "success"}),
    ]
    (run_dir / "observability" / "events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n"
    )
    return run_dir


def test_store_projects_run_metrics(temp_run_dir: Path) -> None:
    store = FileSystemRunStore(temp_run_dir.parent)
    metrics = store.get_run_metrics(temp_run_dir.name)
    assert metrics is not None
    assert metrics["tokens"]["total"] == 1500
    assert metrics["stages_executed"] == 1


def test_store_projects_stage_metrics(temp_run_dir: Path) -> None:
    store = FileSystemRunStore(temp_run_dir.parent)
    stage_metrics = store.get_stage_metrics(temp_run_dir.name)
    assert len(stage_metrics) == 1
    assert stage_metrics[0]["stage"] == "plan"
    assert stage_metrics[0]["tokens"]["total"] == 1500


def test_build_metrics_context_from_projected_data(temp_run_dir: Path) -> None:
    store = FileSystemRunStore(temp_run_dir.parent)
    run_metrics = store.get_run_metrics(temp_run_dir.name) or {}
    stage_metrics = store.get_stage_metrics(temp_run_dir.name)

    context = _build_metrics_context(
        run_metrics=run_metrics,
        stage_metrics=stage_metrics,
        fallback_duration_ms=0,
        fallback_model="codex",
    )

    assert context["tokens"]["total"] == 1500
    assert context["stages"][0]["name"] == "plan"
    assert context["stages"][0]["model"] == "gpt-4"
