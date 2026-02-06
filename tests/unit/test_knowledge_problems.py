"""Unit tests for event-driven knowledge problems collection."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orx.knowledge.problems import (
    FixAttempt,
    ProblemsCollector,
    ProblemsSummary,
    StageProblem,
)


def _event(
    step_id: int,
    event_type: str,
    payload: dict[str, object] | None = None,
    *,
    event_id: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "event_id": event_id or f"e{step_id}",
        "ts": "2026-02-06T00:00:00+00:00",
        "run_id": "test_run_123",
        "source": "supervisor",
        "event_type": event_type,
        "step_id": step_id,
        "correlation": {},
        "payload": payload or {},
    }


class TestStageProblem:
    def test_to_summary_basic(self) -> None:
        problem = StageProblem(
            stage="implement",
            category="gate_failure",
            message="Ruff found 5 errors",
        )
        summary = problem.to_summary()
        assert "[implement:gate_failure]" in summary
        assert "Ruff found 5 errors" in summary

    def test_to_summary_with_gate_and_item(self) -> None:
        problem = StageProblem(
            stage="verify",
            category="gate_failure",
            message="Tests failed",
            gate_name="pytest",
            item_id="W001",
        )
        summary = problem.to_summary()
        assert "(pytest)" in summary
        assert "item=W001" in summary


class TestProblemsSummary:
    def test_has_problems_empty(self) -> None:
        assert not ProblemsSummary().has_problems()

    def test_has_problems_with_entries(self) -> None:
        summary = ProblemsSummary(
            problems=[StageProblem(stage="x", category="y", message="z")]
        )
        assert summary.has_problems()

    def test_to_prompt_section_contains_event_refs(self) -> None:
        summary = ProblemsSummary(
            problems=[
                StageProblem(
                    stage="verify",
                    category="gate_failure",
                    message="Gate ruff rejected",
                    event_refs=["ev-1 (step 10)"],
                )
            ],
            stages_failed=1,
            total_fix_iterations=0,
        )
        section = summary.to_prompt_section()
        assert "Event refs:" in section
        assert "ev-1 (step 10)" in section

    def test_lessons_include_context_bloat(self) -> None:
        summary = ProblemsSummary(failure_categories={"context_bloat": 1})
        lessons = summary.get_lessons_learned()
        assert any("context bloat" in lesson.lower() for lesson in lessons)


class TestProblemsCollector:
    @pytest.fixture
    def mock_paths(self, tmp_path: Path) -> MagicMock:
        paths = MagicMock()
        paths.run_id = "test_run_123"
        paths.observability_events_jsonl = tmp_path / "observability" / "events.jsonl"
        paths.observability_events_jsonl.parent.mkdir(parents=True, exist_ok=True)
        return paths

    def test_collect_empty(self, mock_paths: MagicMock) -> None:
        collector = ProblemsCollector(mock_paths)
        summary = collector.collect()
        assert not summary.has_problems()
        assert summary.problems == []

    def test_collect_stage_failure(self, mock_paths: MagicMock) -> None:
        events = [
            _event(
                1,
                "stage.end",
                {"stage": "implement", "attempt": 1, "status": "failure", "message": "boom"},
            )
        ]
        mock_paths.observability_events_jsonl.write_text(
            "\n".join(json.dumps(event) for event in events)
        )
        summary = ProblemsCollector(mock_paths).collect()
        assert summary.stages_failed == 1
        assert summary.failure_categories["stage_failure"] == 1
        assert len(summary.problems) == 1

    def test_collect_gate_failure(self, mock_paths: MagicMock) -> None:
        events = [
            _event(
                2,
                "gate.approval",
                {"gate": "ruff", "status": "rejected", "item_id": "W001", "attempt": 1},
            )
        ]
        mock_paths.observability_events_jsonl.write_text(
            "\n".join(json.dumps(event) for event in events)
        )
        summary = ProblemsCollector(mock_paths).collect()
        assert summary.gate_failures["ruff"] == 1
        assert any(problem.gate_name == "ruff" for problem in summary.problems)

    def test_collect_fix_iterations(self, mock_paths: MagicMock) -> None:
        events = [
            _event(
                1,
                "stage.end",
                {"stage": "fix", "item_id": "W001", "attempt": 1, "status": "success"},
            ),
            _event(
                2,
                "stage.end",
                {"stage": "fix", "item_id": "W001", "attempt": 2, "status": "failure"},
            ),
        ]
        mock_paths.observability_events_jsonl.write_text(
            "\n".join(json.dumps(event) for event in events)
        )
        summary = ProblemsCollector(mock_paths).collect()
        assert summary.total_fix_iterations == 2
        assert len(summary.fix_attempts) == 2

    def test_collect_retries_detection(self, mock_paths: MagicMock) -> None:
        events = [
            _event(
                1,
                "stage.end",
                {"stage": "implement", "item_id": "W001", "attempt": 1, "status": "failure"},
            ),
            _event(
                2,
                "stage.end",
                {"stage": "implement", "item_id": "W001", "attempt": 2, "status": "success"},
            ),
        ]
        mock_paths.observability_events_jsonl.write_text(
            "\n".join(json.dumps(event) for event in events)
        )
        summary = ProblemsCollector(mock_paths).collect()
        assert summary.stages_retried == 1

    def test_detect_context_bloat(self, mock_paths: MagicMock) -> None:
        events = [
            _event(1, "llm.request", {"chars": 100, "stage": "plan"}),
            _event(2, "llm.request", {"chars": 150, "stage": "spec"}),
            _event(3, "llm.request", {"chars": 240, "stage": "review"}),
        ]
        mock_paths.observability_events_jsonl.write_text(
            "\n".join(json.dumps(event) for event in events)
        )
        summary = ProblemsCollector(mock_paths).collect()
        assert summary.failure_categories["context_bloat"] == 1

    def test_detect_looping(self, mock_paths: MagicMock) -> None:
        events = [
            _event(i, "proc.exec.start", {"cmd": ["pytest", "-q"]}) for i in range(1, 7)
        ]
        mock_paths.observability_events_jsonl.write_text(
            "\n".join(json.dumps(event) for event in events)
        )
        summary = ProblemsCollector(mock_paths).collect()
        assert summary.failure_categories["looping"] == 1


class TestFixAttempt:
    def test_fix_attempt_creation(self) -> None:
        attempt = FixAttempt(
            item_id="W001",
            attempt=1,
            trigger="verify_failure",
            succeeded=True,
            duration_ms=200,
        )
        assert attempt.item_id == "W001"
        assert attempt.succeeded
