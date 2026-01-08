"""Unit tests for metrics schema."""

from __future__ import annotations

import json

from orx.metrics.schema import (
    DiffStats,
    FailureCategory,
    GateMetrics,
    QualityMetrics,
    RunMetrics,
    StageMetrics,
    StageStatus,
    compute_fingerprint,
)


class TestComputeFingerprint:
    """Tests for compute_fingerprint function."""

    def test_deterministic(self) -> None:
        """Same input produces same output."""
        fp1 = compute_fingerprint("hello", "world")
        fp2 = compute_fingerprint("hello", "world")
        assert fp1 == fp2

    def test_different_input_different_output(self) -> None:
        """Different input produces different output."""
        fp1 = compute_fingerprint("hello")
        fp2 = compute_fingerprint("world")
        assert fp1 != fp2

    def test_length(self) -> None:
        """Fingerprint is 16 characters."""
        fp = compute_fingerprint("test")
        assert len(fp) == 16

    def test_empty_input(self) -> None:
        """Empty input produces valid fingerprint."""
        fp = compute_fingerprint()
        assert len(fp) == 16

    def test_order_matters(self) -> None:
        """Order of arguments matters."""
        fp1 = compute_fingerprint("a", "b")
        fp2 = compute_fingerprint("b", "a")
        assert fp1 != fp2


class TestStageStatus:
    """Tests for StageStatus enum."""

    def test_values(self) -> None:
        """All expected values exist."""
        assert StageStatus.SUCCESS.value == "success"
        assert StageStatus.FAIL.value == "fail"
        assert StageStatus.SKIP.value == "skip"
        assert StageStatus.CANCEL.value == "cancel"
        assert StageStatus.TIMEOUT.value == "timeout"


class TestFailureCategory:
    """Tests for FailureCategory enum."""

    def test_values(self) -> None:
        """All expected values exist."""
        assert FailureCategory.EXECUTOR_ERROR.value == "executor_error"
        assert FailureCategory.GATE_FAILURE.value == "gate_failure"
        assert FailureCategory.TIMEOUT.value == "timeout"
        assert FailureCategory.PARSE_ERROR.value == "parse_error"
        assert FailureCategory.GUARDRAIL_VIOLATION.value == "guardrail_violation"
        assert FailureCategory.EMPTY_DIFF.value == "empty_diff"
        assert FailureCategory.MAX_ATTEMPTS.value == "max_attempts"
        assert FailureCategory.UNKNOWN.value == "unknown"


class TestGateMetrics:
    """Tests for GateMetrics model."""

    def test_create(self) -> None:
        """Create a GateMetrics instance."""
        gm = GateMetrics(
            name="pytest",
            exit_code=0,
            passed=True,
            duration_ms=1234,
            tests_total=10,
            tests_failed=0,
        )
        assert gm.name == "pytest"
        assert gm.passed is True
        assert gm.duration_ms == 1234
        assert gm.tests_total == 10

    def test_to_dict(self) -> None:
        """Convert to dictionary."""
        gm = GateMetrics(
            name="ruff",
            exit_code=1,
            passed=False,
            duration_ms=500,
            error_output="Some error",
        )
        d = gm.to_dict()
        assert d["name"] == "ruff"
        assert d["passed"] is False
        assert d["duration_ms"] == 500
        assert d["error_output"] == "Some error"


class TestDiffStats:
    """Tests for DiffStats model."""

    def test_create(self) -> None:
        """Create a DiffStats instance."""
        ds = DiffStats(
            files_changed=5,
            lines_added=100,
            lines_removed=50,
        )
        assert ds.files_changed == 5
        assert ds.lines_added == 100
        assert ds.lines_removed == 50

    def test_from_diff_basic(self) -> None:
        """Parse a basic diff."""
        diff = """\
diff --git a/file1.py b/file1.py
index abc123..def456 100644
--- a/file1.py
+++ b/file1.py
@@ -1,3 +1,5 @@
+# Added comment
 def foo():
-    pass
+    return 42
+# End
"""
        ds = DiffStats.from_diff(diff)
        assert ds.files_changed == 1
        assert ds.lines_added == 3
        assert ds.lines_removed == 1

    def test_from_diff_multiple_files(self) -> None:
        """Parse diff with multiple files."""
        diff = """\
diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1 +1,2 @@
+new line
diff --git a/b.py b/b.py
--- a/b.py
+++ b/b.py
@@ -1 +1,3 @@
+line 1
+line 2
"""
        ds = DiffStats.from_diff(diff)
        assert ds.files_changed == 2
        assert ds.lines_added == 3
        assert ds.lines_removed == 0

    def test_from_diff_empty(self) -> None:
        """Parse empty diff."""
        ds = DiffStats.from_diff("")
        assert ds.files_changed == 0
        assert ds.lines_added == 0
        assert ds.lines_removed == 0


class TestQualityMetrics:
    """Tests for QualityMetrics model."""

    def test_create(self) -> None:
        """Create a QualityMetrics instance."""
        qm = QualityMetrics(
            spec_quality=0.8,
            diff_within_limits=True,
        )
        assert qm.spec_quality == 0.8
        assert qm.diff_within_limits is True

    def test_to_dict_sparse(self) -> None:
        """Only non-None values in dict."""
        qm = QualityMetrics(spec_quality=0.5)
        d = qm.to_dict()
        assert "spec_quality" in d
        assert d["spec_quality"] == 0.5


class TestStageMetrics:
    """Tests for StageMetrics model."""

    def test_create(self) -> None:
        """Create a StageMetrics instance."""
        sm = StageMetrics(
            run_id="test-run-123",
            stage="implement",
            attempt=1,
            start_ts="2024-01-01T00:00:00",
            end_ts="2024-01-01T00:01:00",
            duration_ms=60000,
            status=StageStatus.SUCCESS,
            llm_duration_ms=40000,
        )
        assert sm.run_id == "test-run-123"
        assert sm.stage == "implement"
        assert sm.status == StageStatus.SUCCESS

    def test_to_dict(self) -> None:
        """Convert to dictionary."""
        sm = StageMetrics(
            run_id="r1",
            stage="plan",
            attempt=1,
            start_ts="2024-01-01T00:00:00",
            end_ts="2024-01-01T00:01:00",
            duration_ms=1000,
            status=StageStatus.SUCCESS,
        )
        d = sm.to_dict()
        assert d["run_id"] == "r1"
        assert d["stage"] == "plan"
        assert d["status"] == "success"  # enum value

    def test_from_dict(self) -> None:
        """Create from dictionary."""
        d = {
            "run_id": "r2",
            "stage": "spec",
            "attempt": 2,
            "start_ts": "2024-01-01T00:00:00",
            "end_ts": "2024-01-01T00:01:00",
            "duration_ms": 2000,
            "status": "fail",
            "failure_category": "executor_error",
            "failure_message": "timeout",
        }
        sm = StageMetrics.from_dict(d)
        assert sm.run_id == "r2"
        assert sm.status == StageStatus.FAIL
        assert sm.failure_category == FailureCategory.EXECUTOR_ERROR

    def test_roundtrip(self) -> None:
        """to_dict and from_dict are inverses."""
        original = StageMetrics(
            run_id="test",
            stage="review",
            attempt=1,
            start_ts="2024-01-01T00:00:00",
            end_ts="2024-01-01T00:01:00",
            duration_ms=3000,
            status=StageStatus.SUCCESS,
            llm_duration_ms=2500,
            verify_duration_ms=500,
            gates=[
                GateMetrics(name="pytest", exit_code=0, passed=True, duration_ms=400)
            ],
        )
        d = original.to_dict()
        restored = StageMetrics.from_dict(d)
        assert restored.run_id == original.run_id
        assert restored.status == original.status
        assert len(restored.gates) == 1
        assert restored.gates[0].name == "pytest"


class TestRunMetrics:
    """Tests for RunMetrics model."""

    def test_create(self) -> None:
        """Create a RunMetrics instance."""
        rm = RunMetrics(
            run_id="run-456",
            start_ts="2024-01-01T00:00:00",
            final_status=StageStatus.SUCCESS,
            total_duration_ms=60000,
            stages_executed=5,
            fix_attempts_total=2,
        )
        assert rm.run_id == "run-456"
        assert rm.final_status == StageStatus.SUCCESS
        assert rm.stages_executed == 5

    def test_to_dict(self) -> None:
        """Convert to dictionary."""
        rm = RunMetrics(
            run_id="r",
            start_ts="2024-01-01T00:00:00",
            final_status=StageStatus.FAIL,
            total_duration_ms=1000,
            stages_executed=2,
            fix_attempts_total=0,
            stage_breakdown={"plan": 500, "implement": 500},
        )
        d = rm.to_dict()
        assert d["final_status"] == "fail"
        assert d["stage_breakdown"] == {"plan": 500, "implement": 500}

    def test_from_dict(self) -> None:
        """Create from dictionary."""
        d = {
            "run_id": "r3",
            "start_ts": "2024-01-01T00:00:00",
            "final_status": "success",
            "total_duration_ms": 5000,
            "stages_executed": 3,
            "fix_attempts_total": 1,
        }
        rm = RunMetrics.from_dict(d)
        assert rm.run_id == "r3"
        assert rm.final_status == StageStatus.SUCCESS

    def test_jsonl_format(self) -> None:
        """StageMetrics can be serialized to JSONL."""
        sm = StageMetrics(
            run_id="test",
            stage="impl",
            attempt=1,
            start_ts="2024-01-01T00:00:00",
            end_ts="2024-01-01T00:01:00",
            duration_ms=1000,
            status=StageStatus.SUCCESS,
        )
        line = json.dumps(sm.to_dict())
        parsed = json.loads(line)
        assert parsed["stage"] == "impl"
