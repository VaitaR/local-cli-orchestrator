"""Unit tests for metrics aggregator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orx.metrics.aggregator import (
    AggregatedMetrics,
    GateStats,
    MetricsAggregator,
    StageStats,
    rebuild_metrics,
)
from orx.metrics.schema import (
    GateMetrics,
    RunMetrics,
    StageMetrics,
    StageStatus,
)


class TestStageStats:
    """Tests for StageStats dataclass."""

    def test_to_dict(self) -> None:
        """Convert to dictionary."""
        stats = StageStats(
            stage="implement",
            total_executions=10,
            success_count=8,
            fail_count=2,
            duration_p50=5000,
            duration_p95=8000,
            duration_avg=5500,
            failure_categories={"gate_failure": 2},
        )
        d = stats.to_dict()
        assert d["stage"] == "implement"
        assert d["success_rate"] == 0.8
        assert d["failure_categories"] == {"gate_failure": 2}


class TestGateStats:
    """Tests for GateStats dataclass."""

    def test_to_dict(self) -> None:
        """Convert to dictionary."""
        stats = GateStats(
            name="pytest",
            total_runs=20,
            pass_count=18,
            fail_count=2,
            duration_p50=3000,
            duration_avg=3200,
        )
        d = stats.to_dict()
        assert d["name"] == "pytest"
        assert d["pass_rate"] == 0.9


class TestAggregatedMetrics:
    """Tests for AggregatedMetrics dataclass."""

    def test_to_dict(self) -> None:
        """Convert to dictionary."""
        metrics = AggregatedMetrics(
            total_runs=5,
            success_rate=0.8,
            avg_duration_ms=30000,
            avg_fix_attempts=1.5,
        )
        d = metrics.to_dict()
        assert d["total_runs"] == 5
        assert d["success_rate"] == 0.8


class TestMetricsAggregator:
    """Tests for MetricsAggregator class."""

    def _create_run_data(
        self,
        tmp_path: Path,
        run_id: str,
        status: StageStatus = StageStatus.SUCCESS,
        stages: list[tuple[str, StageStatus]] | None = None,
    ) -> None:
        """Helper to create test run data."""
        run_dir = tmp_path / "runs" / run_id
        metrics_dir = run_dir / "metrics"
        metrics_dir.mkdir(parents=True)

        if stages is None:
            stages = [("plan", StageStatus.SUCCESS), ("implement", StageStatus.SUCCESS)]

        # Write stage metrics
        stage_lines = []
        for stage_name, stage_status in stages:
            sm = StageMetrics(
                run_id=run_id,
                stage=stage_name,
                attempt=1,
                start_ts="2024-01-01T00:00:00",
                end_ts="2024-01-01T00:01:00",
                duration_ms=1000,
                status=stage_status,
                gates=[
                    GateMetrics(name="ruff", exit_code=0, passed=True, duration_ms=100),
                ],
            )
            stage_lines.append(json.dumps(sm.to_dict()))
        (metrics_dir / "stages.jsonl").write_text("\n".join(stage_lines))

        # Write run metrics
        rm = RunMetrics(
            run_id=run_id,
            start_ts="2024-01-01T00:00:00",
            final_status=status,
            total_duration_ms=5000,
            stages_executed=len(stages),
            fix_attempts_total=0,
            stage_breakdown={s[0]: 1000 for s in stages},
        )
        (metrics_dir / "run.json").write_text(json.dumps(rm.to_dict()))

    def test_scan_runs_empty(self, tmp_path: Path) -> None:
        """Scan empty runs directory."""
        aggregator = MetricsAggregator(tmp_path)
        count = aggregator.scan_runs()
        assert count == 0

    def test_scan_runs_with_data(self, tmp_path: Path) -> None:
        """Scan runs with data."""
        self._create_run_data(tmp_path, "run1")
        self._create_run_data(tmp_path, "run2")

        aggregator = MetricsAggregator(tmp_path)
        count = aggregator.scan_runs()
        assert count == 2

    def test_build_report_empty(self, tmp_path: Path) -> None:
        """Build report with no data."""
        aggregator = MetricsAggregator(tmp_path)
        aggregator.scan_runs()
        report = aggregator.build_report()

        assert report.total_runs == 0

    def test_build_report_basic(self, tmp_path: Path) -> None:
        """Build report with basic data."""
        self._create_run_data(tmp_path, "run1", StageStatus.SUCCESS)
        self._create_run_data(tmp_path, "run2", StageStatus.SUCCESS)
        self._create_run_data(tmp_path, "run3", StageStatus.FAIL)

        aggregator = MetricsAggregator(tmp_path)
        aggregator.scan_runs()
        report = aggregator.build_report()

        assert report.total_runs == 3
        assert report.success_rate == pytest.approx(0.67, abs=0.01)

    def test_stage_stats(self, tmp_path: Path) -> None:
        """Report includes stage statistics."""
        self._create_run_data(
            tmp_path,
            "run1",
            stages=[
                ("plan", StageStatus.SUCCESS),
                ("implement", StageStatus.SUCCESS),
            ],
        )
        self._create_run_data(
            tmp_path,
            "run2",
            stages=[
                ("plan", StageStatus.SUCCESS),
                ("implement", StageStatus.FAIL),
            ],
        )

        aggregator = MetricsAggregator(tmp_path)
        aggregator.scan_runs()
        report = aggregator.build_report()

        assert "plan" in report.stage_stats
        assert report.stage_stats["plan"].success_count == 2
        assert "implement" in report.stage_stats
        assert report.stage_stats["implement"].success_count == 1
        assert report.stage_stats["implement"].fail_count == 1

    def test_gate_stats(self, tmp_path: Path) -> None:
        """Report includes gate statistics."""
        self._create_run_data(tmp_path, "run1")
        self._create_run_data(tmp_path, "run2")

        aggregator = MetricsAggregator(tmp_path)
        aggregator.scan_runs()
        report = aggregator.build_report()

        assert "ruff" in report.gate_stats
        assert report.gate_stats["ruff"].total_runs == 4  # 2 runs * 2 stages

    def test_time_breakdown(self, tmp_path: Path) -> None:
        """Report includes time breakdown."""
        self._create_run_data(tmp_path, "run1")

        aggregator = MetricsAggregator(tmp_path)
        aggregator.scan_runs()
        report = aggregator.build_report()

        assert "plan" in report.time_breakdown
        assert "implement" in report.time_breakdown

    def test_save_report(self, tmp_path: Path) -> None:
        """Save report to file."""
        self._create_run_data(tmp_path, "run1")

        aggregator = MetricsAggregator(tmp_path)
        aggregator.output_dir = tmp_path / "output"
        aggregator.scan_runs()

        report_path = aggregator.save_report()
        assert report_path.exists()

        data = json.loads(report_path.read_text())
        assert "total_runs" in data
        assert data["total_runs"] == 1

    def test_generate_summary_report(self, tmp_path: Path) -> None:
        """Generate human-readable summary."""
        self._create_run_data(tmp_path, "run1")
        self._create_run_data(tmp_path, "run2", StageStatus.FAIL)

        aggregator = MetricsAggregator(tmp_path)
        aggregator.scan_runs()

        summary = aggregator.generate_summary_report()
        assert "ORX Metrics Summary" in summary
        assert "Total Runs: 2" in summary
        assert "Success Rate:" in summary
        assert "Stage Performance:" in summary


class TestRebuildMetrics:
    """Tests for rebuild_metrics function."""

    def test_rebuild(self, tmp_path: Path) -> None:
        """Rebuild metrics from runs."""
        # Create a run
        run_dir = tmp_path / "runs" / "test-run"
        metrics_dir = run_dir / "metrics"
        metrics_dir.mkdir(parents=True)

        sm = StageMetrics(
            run_id="test-run",
            stage="plan",
            attempt=1,
            start_ts="2024-01-01T00:00:00",
            end_ts="2024-01-01T00:01:00",
            duration_ms=1000,
            status=StageStatus.SUCCESS,
        )
        (metrics_dir / "stages.jsonl").write_text(json.dumps(sm.to_dict()))

        rm = RunMetrics(
            run_id="test-run",
            start_ts="2024-01-01T00:00:00",
            final_status=StageStatus.SUCCESS,
            total_duration_ms=5000,
            stages_executed=1,
            fix_attempts_total=0,
        )
        (metrics_dir / "run.json").write_text(json.dumps(rm.to_dict()))

        # Rebuild
        output_dir = tmp_path / "output"
        report_path = rebuild_metrics(tmp_path, output_dir)

        assert report_path.exists()
        assert report_path.parent == output_dir
