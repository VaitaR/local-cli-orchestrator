"""Metrics writer for persisting metrics data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from orx.metrics.schema import RunMetrics, StageMetrics
    from orx.paths import RunPaths

logger = structlog.get_logger()


class MetricsWriter:
    """Writes metrics to files in the run directory.

    Files written:
    - runs/<id>/metrics/stages.jsonl - One line per stage attempt
    - runs/<id>/metrics/run.json - Aggregated run metrics

    Example:
        >>> writer = MetricsWriter(paths)
        >>> writer.write_stage(stage_metrics)
        >>> writer.write_run(run_metrics)
    """

    def __init__(self, paths: RunPaths) -> None:
        """Initialize the metrics writer.

        Args:
            paths: RunPaths for the current run.
        """
        self.paths = paths
        self._metrics_dir = paths.run_dir / "metrics"
        self._log = logger.bind(run_id=paths.run_id)

    @property
    def metrics_dir(self) -> Path:
        """Get the metrics directory path."""
        return self._metrics_dir

    @property
    def stages_jsonl(self) -> Path:
        """Path to stages.jsonl file."""
        return self._metrics_dir / "stages.jsonl"

    @property
    def run_json(self) -> Path:
        """Path to run.json file."""
        return self._metrics_dir / "run.json"

    def _ensure_dir(self) -> None:
        """Ensure the metrics directory exists."""
        self._metrics_dir.mkdir(parents=True, exist_ok=True)

    def write_stage(self, metrics: StageMetrics) -> None:
        """Write a single stage metrics record.

        Appends to stages.jsonl (one JSON object per line).

        Args:
            metrics: StageMetrics to write.
        """
        self._ensure_dir()

        with self.stages_jsonl.open("a") as f:
            f.write(json.dumps(metrics.to_dict()) + "\n")

        self._log.debug(
            "Wrote stage metrics",
            stage=metrics.stage,
            attempt=metrics.attempt,
        )

    def write_stages(self, metrics_list: list[StageMetrics]) -> None:
        """Write multiple stage metrics records.

        Args:
            metrics_list: List of StageMetrics to write.
        """
        self._ensure_dir()

        with self.stages_jsonl.open("a") as f:
            for metrics in metrics_list:
                f.write(json.dumps(metrics.to_dict()) + "\n")

        self._log.debug("Wrote stage metrics", count=len(metrics_list))

    def write_run(self, metrics: RunMetrics) -> None:
        """Write run-level metrics.

        Writes to run.json (overwrites if exists).

        Args:
            metrics: RunMetrics to write.
        """
        self._ensure_dir()

        self.run_json.write_text(json.dumps(metrics.to_dict(), indent=2))

        self._log.debug(
            "Wrote run metrics",
            status=metrics.final_status.value,
            duration_ms=metrics.total_duration_ms,
        )

    def read_stages(self) -> list[StageMetrics]:
        """Read all stage metrics from stages.jsonl.

        Returns:
            List of StageMetrics objects.
        """
        from orx.metrics.schema import StageMetrics

        if not self.stages_jsonl.exists():
            return []

        metrics = []
        for line in self.stages_jsonl.read_text().splitlines():
            if line.strip():
                data = json.loads(line)
                metrics.append(StageMetrics.from_dict(data))

        return metrics

    def read_run(self) -> RunMetrics | None:
        """Read run metrics from run.json.

        Returns:
            RunMetrics object or None if not found.
        """
        from orx.metrics.schema import RunMetrics

        if not self.run_json.exists():
            return None

        data = json.loads(self.run_json.read_text())
        return RunMetrics.from_dict(data)


def append_to_index(base_dir: Path, run_id: str, summary: dict) -> None:
    """Append a run summary to the global index file.

    Args:
        base_dir: Base directory containing runs/.
        run_id: Run identifier.
        summary: Summary dict to append.
    """
    index_path = base_dir / "runs" / "index.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)

    # Add run_id if not present
    summary.setdefault("run_id", run_id)

    with index_path.open("a") as f:
        f.write(json.dumps(summary) + "\n")


def read_index(base_dir: Path) -> list[dict]:
    """Read the global index file.

    Args:
        base_dir: Base directory containing runs/.

    Returns:
        List of run summary dicts.
    """
    index_path = base_dir / "runs" / "index.jsonl"

    if not index_path.exists():
        return []

    summaries = []
    for line in index_path.read_text().splitlines():
        if line.strip():
            summaries.append(json.loads(line))

    return summaries
