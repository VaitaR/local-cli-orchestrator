"""Unit tests for metrics collector."""

from __future__ import annotations

import time

from orx.metrics.collector import MetricsCollector, StageTimer
from orx.metrics.schema import (
    FailureCategory,
    StageStatus,
)


class FakeGateResult:
    """Fake gate result for testing."""

    def __init__(
        self,
        *,
        ok: bool = True,
        failed: bool = False,
        returncode: int = 0,
        log_tail: str = "",
    ) -> None:
        self.ok = ok
        self.failed = failed
        self.returncode = returncode
        self._log_tail = log_tail

    def get_log_tail(self, lines: int = 20) -> str:  # noqa: ARG002
        return self._log_tail


class TestStageTimer:
    """Tests for StageTimer dataclass."""

    def test_create(self) -> None:
        """Create a StageTimer."""
        timer = StageTimer(stage="plan")
        assert timer.stage == "plan"
        assert timer.start_time is not None
        assert timer.end_time is None
        assert timer._llm_start is None

    def test_stop(self) -> None:
        """Stop the timer."""
        timer = StageTimer(stage="plan")
        time.sleep(0.01)
        timer.stop()
        assert timer.end_time is not None
        assert timer.end_time > timer.start_time

    def test_duration_ms(self) -> None:
        """Calculate duration in milliseconds."""
        timer = StageTimer(stage="plan")
        time.sleep(0.05)
        timer.stop()
        duration = timer.duration_ms
        assert duration >= 50
        assert duration < 200  # Should not be too long

    def test_llm_timing(self) -> None:
        """Track LLM timing."""
        timer = StageTimer(stage="plan")
        timer.start_llm()
        time.sleep(0.02)
        timer.end_llm()
        assert timer.llm_duration_ms >= 20

    def test_verify_timing(self) -> None:
        """Track verify timing."""
        timer = StageTimer(stage="verify")
        timer.start_verify()
        time.sleep(0.02)
        timer.end_verify()
        assert timer.verify_duration_ms >= 20


class TestMetricsCollector:
    """Tests for MetricsCollector class."""

    def test_create(self) -> None:
        """Create a MetricsCollector."""
        collector = MetricsCollector("test-run-id")
        assert collector.run_id == "test-run-id"

    def test_stage_context_manager(self) -> None:
        """Stage context manager works."""
        collector = MetricsCollector("run1")

        with collector.stage("plan") as timer:
            time.sleep(0.01)
            timer.start_llm()
            time.sleep(0.01)
            timer.end_llm()
            collector.record_success()

        stages = collector.get_stage_metrics()
        assert len(stages) == 1
        assert stages[0].stage == "plan"
        assert stages[0].status == StageStatus.SUCCESS

    def test_record_failure(self) -> None:
        """Record stage failure."""
        collector = MetricsCollector("run2")

        with collector.stage("implement"):
            collector.record_failure(
                category=FailureCategory.EXECUTOR_ERROR,
                message="timeout after 60s",
            )

        stages = collector.get_stage_metrics()
        assert len(stages) == 1
        assert stages[0].status == StageStatus.FAIL
        assert stages[0].failure_category == FailureCategory.EXECUTOR_ERROR

    def test_record_gate(self) -> None:
        """Record gate results."""
        collector = MetricsCollector("run3")

        with collector.stage("verify"):
            result = FakeGateResult(ok=True, returncode=0)
            collector.record_gate(
                "pytest",
                result=result,
                duration_ms=500,
                tests_total=10,
                tests_failed=0,
            )
            collector.record_success()

        stages = collector.get_stage_metrics()
        assert len(stages[0].gates) == 1
        assert stages[0].gates[0].name == "pytest"
        assert stages[0].gates[0].passed is True

    def test_record_quality(self) -> None:
        """Record quality metrics."""
        collector = MetricsCollector("run4")

        with collector.stage("spec"):
            collector.record_quality(spec_quality=0.85)
            collector.record_success()

        stages = collector.get_stage_metrics()
        assert stages[0].quality is not None
        assert stages[0].quality.spec_quality == 0.85

    def test_record_model_selection(self) -> None:
        """Record model/profile selection."""
        collector = MetricsCollector("run5")

        with collector.stage("implement"):
            collector.record_model_selection(
                executor="codex", profile="pro", model="claude-3"
            )
            collector.record_success()

        stages = collector.get_stage_metrics()
        assert stages[0].profile == "pro"
        assert stages[0].model == "claude-3"

    def test_multiple_stages(self) -> None:
        """Track multiple stages."""
        collector = MetricsCollector("run6")

        with collector.stage("plan"):
            collector.record_success()

        with collector.stage("spec"):
            collector.record_success()

        with collector.stage("implement"):
            collector.record_failure(FailureCategory.GATE_FAILURE)

        stages = collector.get_stage_metrics()
        assert len(stages) == 3
        assert stages[0].stage == "plan"
        assert stages[1].stage == "spec"
        assert stages[2].stage == "implement"
        assert stages[2].status == StageStatus.FAIL

    def test_attempt_tracking(self) -> None:
        """Track attempt numbers."""
        collector = MetricsCollector("run7")

        # First attempt
        with collector.stage("implement", attempt=1):
            collector.record_failure(FailureCategory.GATE_FAILURE)

        # Second attempt
        with collector.stage("implement", attempt=2):
            collector.record_success()

        stages = collector.get_stage_metrics()
        assert len(stages) == 2
        assert stages[0].attempt == 1
        assert stages[0].status == StageStatus.FAIL
        assert stages[1].attempt == 2
        assert stages[1].status == StageStatus.SUCCESS

    def test_build_run_metrics(self) -> None:
        """Build aggregated run metrics."""
        collector = MetricsCollector("run8")

        with collector.stage("plan"):
            time.sleep(0.01)
            collector.record_success()

        with collector.stage("implement", attempt=1):
            time.sleep(0.01)
            result = FakeGateResult(ok=False, failed=True, returncode=1)
            collector.record_gate("ruff", result=result, duration_ms=100)
            collector.record_failure(FailureCategory.GATE_FAILURE)

        with collector.stage("implement", attempt=2):
            time.sleep(0.01)
            result = FakeGateResult(ok=True, returncode=0)
            collector.record_gate("ruff", result=result, duration_ms=80)
            collector.record_success()

        run_metrics = collector.build_run_metrics(final_status=StageStatus.SUCCESS)

        assert run_metrics.run_id == "run8"
        assert run_metrics.final_status == StageStatus.SUCCESS
        assert run_metrics.stages_executed == 3
        assert run_metrics.stages_failed == 1

    def test_build_run_metrics_stage_breakdown(self) -> None:
        """Run metrics include stage breakdown."""
        collector = MetricsCollector("run9")

        with collector.stage("plan"):
            time.sleep(0.02)
            collector.record_success()

        with collector.stage("spec"):
            time.sleep(0.02)
            collector.record_success()

        run_metrics = collector.build_run_metrics(final_status=StageStatus.SUCCESS)

        assert "plan" in run_metrics.stage_breakdown
        assert "spec" in run_metrics.stage_breakdown
        assert run_metrics.stage_breakdown["plan"] >= 20
        assert run_metrics.stage_breakdown["spec"] >= 20

    def test_record_fingerprints(self) -> None:
        """Record input/output fingerprints."""
        collector = MetricsCollector("run10")

        with collector.stage("plan"):
            collector.record_inputs_fingerprint("input content")
            collector.record_outputs_fingerprint("output content")
            collector.record_success()

        stages = collector.get_stage_metrics()
        assert stages[0].inputs_fingerprint is not None
        assert stages[0].outputs_fingerprint is not None
        assert len(stages[0].inputs_fingerprint) == 16
        assert len(stages[0].outputs_fingerprint) == 16
