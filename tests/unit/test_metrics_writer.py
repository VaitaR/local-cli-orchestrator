"""Unit tests for metrics writer."""

from __future__ import annotations

import json
from pathlib import Path

from orx.metrics.schema import (
    GateMetrics,
    RunMetrics,
    StageMetrics,
    StageStatus,
)
from orx.metrics.writer import MetricsWriter, append_to_index, read_index


class FakePaths:
    """Fake paths for testing."""

    def __init__(self, tmp_path: Path, run_id: str = "test-run") -> None:
        self.run_id = run_id
        self.run_dir = tmp_path / "runs" / run_id
        self.run_dir.mkdir(parents=True)


class TestMetricsWriter:
    """Tests for MetricsWriter class."""

    def test_write_stage(self, tmp_path: Path) -> None:
        """Write a single stage metric."""
        paths = FakePaths(tmp_path)
        writer = MetricsWriter(paths)  # type: ignore

        sm = StageMetrics(
            run_id=paths.run_id,
            stage="plan",
            attempt=1,
            start_ts="2024-01-01T00:00:00",
            end_ts="2024-01-01T00:01:00",
            duration_ms=60000,
            status=StageStatus.SUCCESS,
        )
        writer.write_stage(sm)

        stages_file = paths.run_dir / "metrics" / "stages.jsonl"
        assert stages_file.exists()

        lines = stages_file.read_text().strip().split("\n")
        assert len(lines) == 1

        data = json.loads(lines[0])
        assert data["stage"] == "plan"
        assert data["status"] == "success"

    def test_write_multiple_stages(self, tmp_path: Path) -> None:
        """Write multiple stage metrics."""
        paths = FakePaths(tmp_path)
        writer = MetricsWriter(paths)  # type: ignore

        for stage in ["plan", "spec", "implement"]:
            sm = StageMetrics(
                run_id=paths.run_id,
                stage=stage,
                attempt=1,
                start_ts="2024-01-01T00:00:00",
                end_ts="2024-01-01T00:01:00",
                duration_ms=1000,
                status=StageStatus.SUCCESS,
            )
            writer.write_stage(sm)

        stages_file = paths.run_dir / "metrics" / "stages.jsonl"
        lines = stages_file.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_write_stages_batch(self, tmp_path: Path) -> None:
        """Write batch of stage metrics."""
        paths = FakePaths(tmp_path)
        writer = MetricsWriter(paths)  # type: ignore

        stages = [
            StageMetrics(
                run_id=paths.run_id,
                stage=f"stage{i}",
                attempt=1,
                start_ts="2024-01-01T00:00:00",
                end_ts="2024-01-01T00:01:00",
                duration_ms=1000 * i,
                status=StageStatus.SUCCESS,
            )
            for i in range(3)
        ]
        writer.write_stages(stages)

        stages_file = paths.run_dir / "metrics" / "stages.jsonl"
        lines = stages_file.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_write_run(self, tmp_path: Path) -> None:
        """Write run-level metrics."""
        paths = FakePaths(tmp_path)
        writer = MetricsWriter(paths)  # type: ignore

        rm = RunMetrics(
            run_id=paths.run_id,
            start_ts="2024-01-01T00:00:00",
            final_status=StageStatus.SUCCESS,
            total_duration_ms=60000,
            stages_executed=5,
            fix_attempts_total=2,
        )
        writer.write_run(rm)

        run_file = paths.run_dir / "metrics" / "run.json"
        assert run_file.exists()

        data = json.loads(run_file.read_text())
        assert data["run_id"] == paths.run_id
        assert data["final_status"] == "success"
        assert data["stages_executed"] == 5

    def test_read_stages(self, tmp_path: Path) -> None:
        """Read stage metrics from file."""
        paths = FakePaths(tmp_path)
        writer = MetricsWriter(paths)  # type: ignore

        # Write some stages
        stages = [
            StageMetrics(
                run_id=paths.run_id,
                stage="plan",
                attempt=1,
                start_ts="2024-01-01T00:00:00",
                end_ts="2024-01-01T00:01:00",
                duration_ms=1000,
                status=StageStatus.SUCCESS,
            ),
            StageMetrics(
                run_id=paths.run_id,
                stage="implement",
                attempt=1,
                start_ts="2024-01-01T00:01:00",
                end_ts="2024-01-01T00:02:00",
                duration_ms=2000,
                status=StageStatus.FAIL,
            ),
        ]
        writer.write_stages(stages)

        # Read them back
        loaded = writer.read_stages()
        assert len(loaded) == 2
        assert loaded[0].stage == "plan"
        assert loaded[1].stage == "implement"
        assert loaded[1].status == StageStatus.FAIL

    def test_read_stages_empty(self, tmp_path: Path) -> None:
        """Read from non-existent file returns empty list."""
        paths = FakePaths(tmp_path)
        writer = MetricsWriter(paths)  # type: ignore

        loaded = writer.read_stages()
        assert loaded == []

    def test_read_run(self, tmp_path: Path) -> None:
        """Read run metrics from file."""
        paths = FakePaths(tmp_path)
        writer = MetricsWriter(paths)  # type: ignore

        rm = RunMetrics(
            run_id=paths.run_id,
            start_ts="2024-01-01T00:00:00",
            final_status=StageStatus.SUCCESS,
            total_duration_ms=30000,
            stages_executed=3,
            fix_attempts_total=0,
        )
        writer.write_run(rm)

        loaded = writer.read_run()
        assert loaded is not None
        assert loaded.run_id == paths.run_id
        assert loaded.final_status == StageStatus.SUCCESS

    def test_read_run_missing(self, tmp_path: Path) -> None:
        """Read from non-existent file returns None."""
        paths = FakePaths(tmp_path)
        writer = MetricsWriter(paths)  # type: ignore

        loaded = writer.read_run()
        assert loaded is None

    def test_complex_stage_with_gates(self, tmp_path: Path) -> None:
        """Write and read stage with gate metrics."""
        paths = FakePaths(tmp_path)
        writer = MetricsWriter(paths)  # type: ignore

        sm = StageMetrics(
            run_id=paths.run_id,
            stage="verify",
            attempt=1,
            start_ts="2024-01-01T00:00:00",
            end_ts="2024-01-01T00:01:00",
            duration_ms=5000,
            status=StageStatus.SUCCESS,
            gates=[
                GateMetrics(
                    name="ruff",
                    exit_code=0,
                    passed=True,
                    duration_ms=200,
                ),
                GateMetrics(
                    name="pytest",
                    exit_code=0,
                    passed=True,
                    duration_ms=4000,
                    tests_total=25,
                    tests_failed=0,
                ),
            ],
        )
        writer.write_stage(sm)

        loaded = writer.read_stages()
        assert len(loaded) == 1
        assert len(loaded[0].gates) == 2
        assert loaded[0].gates[0].name == "ruff"
        assert loaded[0].gates[1].tests_total == 25


class TestIndexFunctions:
    """Tests for index file functions."""

    def test_append_to_index(self, tmp_path: Path) -> None:
        """Append entries to index."""
        append_to_index(
            tmp_path,
            run_id="run1",
            summary={"status": "success", "duration_ms": 10000},
        )
        append_to_index(
            tmp_path,
            run_id="run2",
            summary={"status": "fail", "duration_ms": 5000},
        )

        index_path = tmp_path / "runs" / "index.jsonl"
        lines = index_path.read_text().strip().split("\n")
        assert len(lines) == 2

        d1 = json.loads(lines[0])
        assert d1["run_id"] == "run1"
        assert d1["status"] == "success"

        d2 = json.loads(lines[1])
        assert d2["run_id"] == "run2"
        assert d2["status"] == "fail"

    def test_read_index(self, tmp_path: Path) -> None:
        """Read entries from index."""
        # Write some entries
        for i in range(3):
            append_to_index(
                tmp_path,
                run_id=f"run{i}",
                summary={"status": "success", "duration_ms": 1000 * (i + 1)},
            )

        entries = read_index(tmp_path)
        assert len(entries) == 3
        assert entries[0]["run_id"] == "run0"
        assert entries[2]["duration_ms"] == 3000

    def test_read_index_missing(self, tmp_path: Path) -> None:
        """Read from missing index returns empty list."""
        entries = read_index(tmp_path)
        assert entries == []
