"""Unit tests for knowledge problems collection."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orx.knowledge.problems import (
    FixAttempt,
    ProblemsCollector,
    ProblemsSummary,
    StageProblem,
)


class TestStageProblem:
    """Tests for StageProblem dataclass."""

    def test_to_summary_basic(self) -> None:
        """Test basic summary generation."""
        problem = StageProblem(
            stage="implement",
            category="gate_failure",
            message="Ruff found 5 errors",
        )
        summary = problem.to_summary()

        assert "[implement:gate_failure]" in summary
        assert "Ruff found 5 errors" in summary

    def test_to_summary_with_gate(self) -> None:
        """Test summary with gate name."""
        problem = StageProblem(
            stage="verify",
            category="gate_failure",
            message="Tests failed",
            gate_name="pytest",
            item_id="W001",
        )
        summary = problem.to_summary()

        assert "[verify:gate_failure]" in summary
        assert "(pytest)" in summary
        assert "item=W001" in summary

    def test_to_summary_truncates_message(self) -> None:
        """Test that long messages are truncated."""
        problem = StageProblem(
            stage="implement",
            category="timeout",
            message="A" * 200,
        )
        summary = problem.to_summary()

        # Message should be truncated to 100 chars
        assert len(summary) < 250


class TestProblemsSummary:
    """Tests for ProblemsSummary dataclass."""

    def test_has_problems_empty(self) -> None:
        """Test has_problems with no problems."""
        summary = ProblemsSummary()
        assert not summary.has_problems()

    def test_has_problems_with_problems(self) -> None:
        """Test has_problems with problems."""
        summary = ProblemsSummary(
            problems=[StageProblem(stage="test", category="error", message="fail")]
        )
        assert summary.has_problems()

    def test_has_problems_with_fix_iterations(self) -> None:
        """Test has_problems with fix iterations only."""
        summary = ProblemsSummary(total_fix_iterations=2)
        assert summary.has_problems()

    def test_to_prompt_section_no_problems(self) -> None:
        """Test prompt section with no problems."""
        summary = ProblemsSummary()
        section = summary.to_prompt_section()

        assert "No significant problems" in section

    def test_to_prompt_section_with_problems(self) -> None:
        """Test prompt section with problems."""
        summary = ProblemsSummary(
            problems=[
                StageProblem(
                    stage="implement",
                    category="gate_failure",
                    message="Ruff check failed",
                    gate_name="ruff",
                    error_output="F401: unused import",
                ),
            ],
            gate_failures={"ruff": 2},
            failure_categories={"gate_failure": 2},
            stages_failed=2,
            total_fix_iterations=1,
        )
        section = summary.to_prompt_section()

        assert "## Problems Encountered" in section
        assert "Stages that failed: 2" in section
        assert "Gate failures: ruff=2" in section
        assert "**Problem 1:**" in section
        assert "Gate: ruff" in section
        assert "F401: unused import" in section

    def test_to_prompt_section_limits_problems(self) -> None:
        """Test that prompt section limits number of problems."""
        problems = [
            StageProblem(stage=f"stage{i}", category="error", message=f"Error {i}")
            for i in range(20)
        ]
        summary = ProblemsSummary(problems=problems)

        section = summary.to_prompt_section(max_problems=5)

        # Should only show 5 problems
        assert "**Problem 5:**" in section
        assert "**Problem 6:**" not in section
        assert "... and 15 more problems" in section

    def test_get_lessons_learned_gate_failures(self) -> None:
        """Test lessons learned from gate failures."""
        summary = ProblemsSummary(gate_failures={"ruff": 3, "pytest": 1})
        lessons = summary.get_lessons_learned()

        assert len(lessons) >= 1
        assert any("ruff" in lesson.lower() for lesson in lessons)

    def test_get_lessons_learned_parse_errors(self) -> None:
        """Test lessons learned from parse errors."""
        summary = ProblemsSummary(failure_categories={"parse_error": 2})
        lessons = summary.get_lessons_learned()

        assert any("parse error" in lesson.lower() for lesson in lessons)

    def test_get_lessons_learned_timeout(self) -> None:
        """Test lessons learned from timeouts."""
        summary = ProblemsSummary(failure_categories={"timeout": 1})
        lessons = summary.get_lessons_learned()

        assert any("timeout" in lesson.lower() for lesson in lessons)


class TestProblemsCollector:
    """Tests for ProblemsCollector."""

    @pytest.fixture
    def mock_paths(self, tmp_path: Path) -> MagicMock:
        """Create mock RunPaths with metrics dir."""
        paths = MagicMock()
        paths.run_id = "test_run_123"
        paths.metrics = tmp_path / "metrics"
        paths.metrics.mkdir()
        return paths

    def test_collect_empty(self, mock_paths: MagicMock) -> None:
        """Test collecting with no stages.jsonl."""
        collector = ProblemsCollector(mock_paths)
        summary = collector.collect()

        assert not summary.has_problems()
        assert summary.problems == []

    def test_collect_success_only(self, mock_paths: MagicMock) -> None:
        """Test collecting when all stages succeeded."""
        stages_jsonl = mock_paths.metrics / "stages.jsonl"
        stages_jsonl.write_text(
            '{"run_id": "test", "stage": "plan", "status": "success", "attempt": 1}\n'
            '{"run_id": "test", "stage": "spec", "status": "success", "attempt": 1}\n'
        )

        collector = ProblemsCollector(mock_paths)
        summary = collector.collect()

        assert not summary.has_problems()
        assert summary.stages_failed == 0

    def test_collect_with_failures(self, mock_paths: MagicMock) -> None:
        """Test collecting with stage failures."""
        stages_jsonl = mock_paths.metrics / "stages.jsonl"
        stages_jsonl.write_text(
            '{"run_id": "test", "stage": "implement", "item_id": "W001", '
            '"status": "fail", "attempt": 1, '
            '"failure_category": "gate_failure", "failure_message": "Ruff failed"}\n'
        )

        collector = ProblemsCollector(mock_paths)
        summary = collector.collect()

        assert summary.has_problems()
        assert summary.stages_failed == 1
        assert len(summary.problems) == 1
        assert summary.problems[0].stage == "implement"
        assert summary.problems[0].category == "gate_failure"
        assert summary.failure_categories["gate_failure"] == 1

    def test_collect_with_gate_metrics(self, mock_paths: MagicMock) -> None:
        """Test collecting gate failure details."""
        stages_jsonl = mock_paths.metrics / "stages.jsonl"
        stages_jsonl.write_text(
            '{"run_id": "test", "stage": "verify", "status": "fail", "attempt": 1, '
            '"failure_category": "gate_failure", "failure_message": "Gate failed", '
            '"gates": [{"name": "ruff", "passed": false, "error_output": "F401"}]}\n'
        )

        collector = ProblemsCollector(mock_paths)
        summary = collector.collect()

        assert summary.gate_failures["ruff"] == 1
        assert summary.problems[0].gate_name == "ruff"
        assert summary.problems[0].error_output == "F401"

    def test_collect_fix_iterations(self, mock_paths: MagicMock) -> None:
        """Test collecting fix iterations."""
        stages_jsonl = mock_paths.metrics / "stages.jsonl"
        stages_jsonl.write_text(
            '{"run_id": "test", "stage": "fix", "item_id": "W001", "status": "success", "attempt": 1}\n'
            '{"run_id": "test", "stage": "fix", "item_id": "W001", "status": "success", "attempt": 2}\n'
        )

        collector = ProblemsCollector(mock_paths)
        summary = collector.collect()

        assert summary.total_fix_iterations == 2
        assert len(summary.fix_attempts) == 2

    def test_collect_retries_detection(self, mock_paths: MagicMock) -> None:
        """Test detecting stages that were retried."""
        stages_jsonl = mock_paths.metrics / "stages.jsonl"
        stages_jsonl.write_text(
            '{"run_id": "test", "stage": "implement", "item_id": "W001", "status": "fail", "attempt": 1}\n'
            '{"run_id": "test", "stage": "implement", "item_id": "W001", "status": "success", "attempt": 2}\n'
        )

        collector = ProblemsCollector(mock_paths)
        summary = collector.collect()

        assert summary.stages_retried == 1

    def test_collect_invalid_json_line(self, mock_paths: MagicMock) -> None:
        """Test handling of invalid JSON lines."""
        stages_jsonl = mock_paths.metrics / "stages.jsonl"
        stages_jsonl.write_text(
            "not valid json\n"
            '{"run_id": "test", "stage": "plan", "status": "success", "attempt": 1}\n'
        )

        collector = ProblemsCollector(mock_paths)
        summary = collector.collect()

        # Should skip invalid line and process valid one
        assert summary.stages_failed == 0

    def test_collect_with_error_info(self, mock_paths: MagicMock) -> None:
        """Test extracting detailed error info."""
        stages_jsonl = mock_paths.metrics / "stages.jsonl"
        stages_jsonl.write_text(
            '{"run_id": "test", "stage": "decompose", "status": "fail", "attempt": 1, '
            '"failure_category": "parse_error", "failure_message": "Invalid YAML", '
            '"error_info": {"category": "parse_error", "message": "Details", '
            '"suggested_action": "Check YAML format"}}\n'
        )

        collector = ProblemsCollector(mock_paths)
        summary = collector.collect()

        assert len(summary.problems) == 1
        assert summary.problems[0].suggested_fix == "Check YAML format"


class TestFixAttempt:
    """Tests for FixAttempt dataclass."""

    def test_fix_attempt_creation(self) -> None:
        """Test creating a fix attempt."""
        attempt = FixAttempt(
            item_id="W001",
            attempt=1,
            trigger="ruff",
            succeeded=True,
            duration_ms=5000,
        )

        assert attempt.item_id == "W001"
        assert attempt.succeeded
        assert attempt.trigger == "ruff"

    def test_fix_attempt_with_error(self) -> None:
        """Test fix attempt with error info."""
        attempt = FixAttempt(
            item_id="W001",
            attempt=2,
            trigger="pytest",
            succeeded=False,
            duration_ms=30000,
            error_before="AssertionError in test_app",
        )

        assert not attempt.succeeded
        assert attempt.error_before is not None
