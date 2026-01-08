"""Metrics aggregation and analysis."""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from orx.metrics.schema import RunMetrics, StageMetrics, StageStatus

logger = structlog.get_logger()


@dataclass
class StageStats:
    """Aggregated statistics for a stage across runs.

    Attributes:
        stage: Stage name.
        total_executions: Total number of executions.
        success_count: Number of successful executions.
        fail_count: Number of failed executions.
        duration_p50: Median duration in ms.
        duration_p95: 95th percentile duration in ms.
        duration_avg: Average duration in ms.
        failure_categories: Count by failure category.
    """

    stage: str
    total_executions: int = 0
    success_count: int = 0
    fail_count: int = 0
    duration_p50: int = 0
    duration_p95: int = 0
    duration_avg: int = 0
    failure_categories: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "stage": self.stage,
            "total_executions": self.total_executions,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "success_rate": (
                round(self.success_count / self.total_executions, 2)
                if self.total_executions > 0
                else 0
            ),
            "duration_p50_ms": self.duration_p50,
            "duration_p95_ms": self.duration_p95,
            "duration_avg_ms": self.duration_avg,
            "failure_categories": self.failure_categories,
        }


@dataclass
class GateStats:
    """Aggregated statistics for a gate across runs.

    Attributes:
        name: Gate name.
        total_runs: Total number of gate runs.
        pass_count: Number of passes.
        fail_count: Number of failures.
        duration_p50: Median duration in ms.
        duration_avg: Average duration in ms.
    """

    name: str
    total_runs: int = 0
    pass_count: int = 0
    fail_count: int = 0
    duration_p50: int = 0
    duration_avg: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "total_runs": self.total_runs,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "pass_rate": (
                round(self.pass_count / self.total_runs, 2)
                if self.total_runs > 0
                else 0
            ),
            "duration_p50_ms": self.duration_p50,
            "duration_avg_ms": self.duration_avg,
        }


@dataclass
class AggregatedMetrics:
    """Aggregated metrics across all runs.

    Attributes:
        total_runs: Total number of runs analyzed.
        success_rate: Overall success rate.
        avg_duration_ms: Average run duration.
        avg_fix_attempts: Average fix attempts per run.
        stage_stats: Statistics per stage.
        gate_stats: Statistics per gate.
        time_breakdown: Average time breakdown by stage.
        top_failure_reasons: Most common failure reasons.
        model_stats: Statistics per model.
    """

    total_runs: int = 0
    success_rate: float = 0.0
    avg_duration_ms: int = 0
    avg_fix_attempts: float = 0.0
    stage_stats: dict[str, StageStats] = field(default_factory=dict)
    gate_stats: dict[str, GateStats] = field(default_factory=dict)
    time_breakdown: dict[str, int] = field(default_factory=dict)
    top_failure_reasons: list[tuple[str, int]] = field(default_factory=list)
    model_stats: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_runs": self.total_runs,
            "success_rate": self.success_rate,
            "avg_duration_ms": self.avg_duration_ms,
            "avg_fix_attempts": self.avg_fix_attempts,
            "stage_stats": {k: v.to_dict() for k, v in self.stage_stats.items()},
            "gate_stats": {k: v.to_dict() for k, v in self.gate_stats.items()},
            "time_breakdown": self.time_breakdown,
            "top_failure_reasons": self.top_failure_reasons,
            "model_stats": self.model_stats,
        }


class MetricsAggregator:
    """Aggregates metrics across multiple runs.

    Scans runs directory and builds aggregate statistics useful
    for identifying bottlenecks and improvement opportunities.

    Example:
        >>> aggregator = MetricsAggregator(base_dir)
        >>> aggregator.scan_runs()
        >>> report = aggregator.build_report()
        >>> aggregator.save_report()
    """

    def __init__(self, base_dir: Path) -> None:
        """Initialize the aggregator.

        Args:
            base_dir: Base directory containing runs/.
        """
        self.base_dir = base_dir
        self.runs_dir = base_dir / "runs"
        self.output_dir = Path.home() / ".orx" / "metrics"
        self._run_metrics: list[RunMetrics] = []
        self._stage_metrics: list[StageMetrics] = []
        self._log = logger.bind(component="aggregator")

    def scan_runs(self) -> int:
        """Scan all runs and collect metrics.

        Returns:
            Number of runs scanned.
        """
        if not self.runs_dir.exists():
            self._log.warning("Runs directory not found", path=str(self.runs_dir))
            return 0

        count = 0
        for run_dir in sorted(self.runs_dir.iterdir()):
            if not run_dir.is_dir() or run_dir.name.startswith("."):
                continue

            metrics_dir = run_dir / "metrics"
            if not metrics_dir.exists():
                continue

            try:
                # Load run metrics
                run_json = metrics_dir / "run.json"
                if run_json.exists():
                    data = json.loads(run_json.read_text())
                    self._run_metrics.append(RunMetrics.from_dict(data))

                # Load stage metrics
                stages_jsonl = metrics_dir / "stages.jsonl"
                if stages_jsonl.exists():
                    for line in stages_jsonl.read_text().splitlines():
                        if line.strip():
                            data = json.loads(line)
                            self._stage_metrics.append(StageMetrics.from_dict(data))

                count += 1

            except Exception as e:
                self._log.warning(
                    "Failed to load metrics from run",
                    run_id=run_dir.name,
                    error=str(e),
                )

        self._log.info("Scanned runs", count=count)
        return count

    def build_report(self) -> AggregatedMetrics:
        """Build aggregated metrics report.

        Returns:
            AggregatedMetrics with all statistics.
        """
        if not self._run_metrics:
            return AggregatedMetrics()

        # Basic run stats
        total_runs = len(self._run_metrics)
        success_count = sum(
            1 for r in self._run_metrics if r.final_status == StageStatus.SUCCESS
        )
        success_rate = round(success_count / total_runs, 2) if total_runs > 0 else 0.0

        # Duration stats
        durations = [r.total_duration_ms or 0 for r in self._run_metrics]
        avg_duration = int(statistics.mean(durations)) if durations else 0

        # Fix attempts
        fix_attempts = [r.fix_attempts_total for r in self._run_metrics]
        avg_fix = round(statistics.mean(fix_attempts), 2) if fix_attempts else 0.0

        # Stage stats
        stage_stats = self._compute_stage_stats()

        # Gate stats
        gate_stats = self._compute_gate_stats()

        # Time breakdown (average across runs)
        time_breakdown = self._compute_time_breakdown()

        # Top failure reasons
        top_failures = self._compute_top_failures()

        # Model stats
        model_stats = self._compute_model_stats()

        return AggregatedMetrics(
            total_runs=total_runs,
            success_rate=success_rate,
            avg_duration_ms=avg_duration,
            avg_fix_attempts=avg_fix,
            stage_stats=stage_stats,
            gate_stats=gate_stats,
            time_breakdown=time_breakdown,
            top_failure_reasons=top_failures,
            model_stats=model_stats,
        )

    def _compute_stage_stats(self) -> dict[str, StageStats]:
        """Compute per-stage statistics."""
        stages: dict[str, list[StageMetrics]] = defaultdict(list)
        for m in self._stage_metrics:
            stages[m.stage].append(m)

        result: dict[str, StageStats] = {}
        for stage, metrics in stages.items():
            durations = [m.duration_ms for m in metrics]

            success_count = sum(1 for m in metrics if m.status == StageStatus.SUCCESS)
            fail_count = sum(1 for m in metrics if m.status == StageStatus.FAIL)

            # Failure categories
            categories: dict[str, int] = defaultdict(int)
            for m in metrics:
                if m.failure_category:
                    categories[m.failure_category.value] += 1

            result[stage] = StageStats(
                stage=stage,
                total_executions=len(metrics),
                success_count=success_count,
                fail_count=fail_count,
                duration_p50=int(statistics.median(durations)) if durations else 0,
                duration_p95=(
                    int(statistics.quantiles(durations, n=20)[18])
                    if len(durations) >= 20
                    else (int(max(durations)) if durations else 0)
                ),
                duration_avg=int(statistics.mean(durations)) if durations else 0,
                failure_categories=dict(categories),
            )

        return result

    def _compute_gate_stats(self) -> dict[str, GateStats]:
        """Compute per-gate statistics."""
        gates: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for m in self._stage_metrics:
            for g in m.gates:
                gates[g.name].append(
                    {
                        "passed": g.passed,
                        "duration_ms": g.duration_ms,
                    }
                )

        result: dict[str, GateStats] = {}
        for name, runs in gates.items():
            durations = [r["duration_ms"] for r in runs]
            pass_count = sum(1 for r in runs if r["passed"])

            result[name] = GateStats(
                name=name,
                total_runs=len(runs),
                pass_count=pass_count,
                fail_count=len(runs) - pass_count,
                duration_p50=int(statistics.median(durations)) if durations else 0,
                duration_avg=int(statistics.mean(durations)) if durations else 0,
            )

        return result

    def _compute_time_breakdown(self) -> dict[str, int]:
        """Compute average time breakdown by stage."""
        stage_times: dict[str, list[int]] = defaultdict(list)

        for r in self._run_metrics:
            for stage, duration in r.stage_breakdown.items():
                stage_times[stage].append(duration)

        return {
            stage: int(statistics.mean(times)) if times else 0
            for stage, times in stage_times.items()
        }

    def _compute_top_failures(self, limit: int = 10) -> list[tuple[str, int]]:
        """Compute top failure reasons."""
        reasons: dict[str, int] = defaultdict(int)

        for m in self._stage_metrics:
            if m.failure_message:
                # Normalize message (truncate long ones)
                msg = m.failure_message[:100]
                reasons[msg] += 1

        sorted_reasons = sorted(reasons.items(), key=lambda x: x[1], reverse=True)
        return sorted_reasons[:limit]

    def _compute_model_stats(self) -> dict[str, dict[str, Any]]:
        """Compute per-model statistics."""
        models: dict[str, list[StageMetrics]] = defaultdict(list)

        for m in self._stage_metrics:
            model_key = m.model or m.profile or "default"
            models[model_key].append(m)

        result: dict[str, dict[str, Any]] = {}
        for model, metrics in models.items():
            durations = [m.duration_ms for m in metrics]
            success_count = sum(1 for m in metrics if m.status == StageStatus.SUCCESS)

            result[model] = {
                "total_executions": len(metrics),
                "success_count": success_count,
                "success_rate": (
                    round(success_count / len(metrics), 2) if metrics else 0
                ),
                "avg_duration_ms": (
                    int(statistics.mean(durations)) if durations else 0
                ),
            }

        return result

    def save_report(self, report: AggregatedMetrics | None = None) -> Path:
        """Save aggregated report to file.

        Args:
            report: Optional pre-built report. If None, builds a new one.

        Returns:
            Path to the saved report file.
        """
        if report is None:
            report = self.build_report()

        self.output_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.output_dir / "aggregate.json"
        report_path.write_text(json.dumps(report.to_dict(), indent=2))

        self._log.info("Saved aggregate report", path=str(report_path))
        return report_path

    def generate_summary_report(self) -> str:
        """Generate a human-readable summary report.

        Returns:
            Formatted summary string.
        """
        report = self.build_report()

        lines = [
            "=" * 60,
            "ORX Metrics Summary",
            "=" * 60,
            "",
            f"Total Runs: {report.total_runs}",
            f"Success Rate: {report.success_rate * 100:.1f}%",
            f"Avg Duration: {report.avg_duration_ms / 1000:.1f}s",
            f"Avg Fix Attempts: {report.avg_fix_attempts:.1f}",
            "",
            "Stage Performance:",
            "-" * 40,
        ]

        for stage, stats in sorted(report.stage_stats.items()):
            success_pct = (
                stats.success_count / stats.total_executions * 100
                if stats.total_executions > 0
                else 0
            )
            lines.append(
                f"  {stage:20} | "
                f"P50: {stats.duration_p50:>6}ms | "
                f"Success: {success_pct:>5.1f}%"
            )

        if report.gate_stats:
            lines.extend(
                [
                    "",
                    "Gate Performance:",
                    "-" * 40,
                ]
            )
            for name, stats in sorted(report.gate_stats.items()):
                pass_pct = (
                    stats.pass_count / stats.total_runs * 100
                    if stats.total_runs > 0
                    else 0
                )
                lines.append(
                    f"  {name:20} | "
                    f"P50: {stats.duration_p50:>6}ms | "
                    f"Pass: {pass_pct:>5.1f}%"
                )

        if report.top_failure_reasons:
            lines.extend(
                [
                    "",
                    "Top Failure Reasons:",
                    "-" * 40,
                ]
            )
            for reason, count in report.top_failure_reasons[:5]:
                lines.append(f"  [{count:>3}x] {reason[:50]}")

        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)


def rebuild_metrics(base_dir: Path, output_dir: Path | None = None) -> Path:
    """Rebuild aggregate metrics from all runs.

    Args:
        base_dir: Base directory containing runs/.
        output_dir: Optional output directory override.

    Returns:
        Path to the saved report file.
    """
    aggregator = MetricsAggregator(base_dir)
    if output_dir:
        aggregator.output_dir = output_dir

    aggregator.scan_runs()
    report = aggregator.build_report()
    return aggregator.save_report(report)
