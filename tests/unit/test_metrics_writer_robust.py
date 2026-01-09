"""Unit tests for robust metrics writer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orx.metrics.schema import RunMetrics, StageMetrics, StageStatus
from orx.metrics.writer import MetricsWriter


@pytest.fixture
def mock_paths(tmp_path: Path) -> MagicMock:
    """Create mock RunPaths."""
    paths = MagicMock()
    paths.run_id = "test_run_123"
    paths.run_dir = tmp_path / "runs" / "test_run_123"
    paths.run_dir.mkdir(parents=True)
    return paths


@pytest.fixture
def writer(mock_paths: MagicMock) -> MetricsWriter:
    """Create MetricsWriter with mock paths."""
    return MetricsWriter(mock_paths)


@pytest.fixture
def sample_stage_metrics() -> StageMetrics:
    """Create sample stage metrics."""
    return StageMetrics(
        run_id="test_run_123",
        stage="plan",
        attempt=1,
        start_ts="2026-01-09T08:00:00+00:00",
        end_ts="2026-01-09T08:05:00+00:00",
        duration_ms=300000,
        status=StageStatus.SUCCESS,
        executor="codex",
        model="gpt-4.1",
    )


@pytest.fixture
def sample_run_metrics() -> RunMetrics:
    """Create sample run metrics."""
    return RunMetrics(
        run_id="test_run_123",
        start_ts="2026-01-09T08:00:00+00:00",
        end_ts="2026-01-09T08:30:00+00:00",
        total_duration_ms=1800000,
        final_status=StageStatus.SUCCESS,
        engine="codex",
        stages_executed=3,
    )


class TestMetricsWriterRobustness:
    """Test that metrics writer handles errors gracefully."""

    def test_write_stage_creates_dir(
        self, writer: MetricsWriter, sample_stage_metrics: StageMetrics
    ) -> None:
        """write_stage creates metrics directory if missing."""
        writer.write_stage(sample_stage_metrics)
        assert writer.metrics_dir.exists()
        assert writer.stages_jsonl.exists()

    def test_write_stage_appends(
        self, writer: MetricsWriter, sample_stage_metrics: StageMetrics
    ) -> None:
        """write_stage appends to existing file."""
        writer.write_stage(sample_stage_metrics)
        writer.write_stage(sample_stage_metrics)

        lines = writer.stages_jsonl.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_write_stages_batch(
        self, writer: MetricsWriter, sample_stage_metrics: StageMetrics
    ) -> None:
        """write_stages writes multiple records."""
        metrics_list = [sample_stage_metrics, sample_stage_metrics]
        writer.write_stages(metrics_list)

        lines = writer.stages_jsonl.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_write_stages_empty_list(self, writer: MetricsWriter) -> None:
        """write_stages handles empty list gracefully."""
        writer.write_stages([])
        # Should not create file for empty list
        assert not writer.stages_jsonl.exists()

    def test_write_run_creates_file(
        self, writer: MetricsWriter, sample_run_metrics: RunMetrics
    ) -> None:
        """write_run creates run.json file."""
        writer.write_run(sample_run_metrics)
        assert writer.run_json.exists()

    def test_write_stage_error_logged_not_raised(
        self, writer: MetricsWriter, sample_stage_metrics: StageMetrics
    ) -> None:
        """Errors in write_stage are logged but not raised."""
        # Make the metrics dir read-only to trigger error
        writer._metrics_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(writer, "_ensure_dir", side_effect=PermissionError("denied")):
            # Should not raise
            writer.write_stage(sample_stage_metrics)

    def test_write_run_error_logged_not_raised(
        self, writer: MetricsWriter, sample_run_metrics: RunMetrics
    ) -> None:
        """Errors in write_run are logged but not raised."""
        with patch.object(writer, "_ensure_dir", side_effect=PermissionError("denied")):
            # Should not raise
            writer.write_run(sample_run_metrics)

    def test_write_stages_partial_failure(self, writer: MetricsWriter) -> None:
        """write_stages continues writing even if one record fails serialization."""
        good_metrics = StageMetrics(
            run_id="test",
            stage="plan",
            attempt=1,
            start_ts="2026-01-09T08:00:00+00:00",
            end_ts="2026-01-09T08:05:00+00:00",
            duration_ms=300000,
            status=StageStatus.SUCCESS,
        )

        # Create a metrics that will fail to serialize
        bad_metrics = MagicMock()
        bad_metrics.to_dict.side_effect = ValueError("Cannot serialize")

        metrics_list = [good_metrics, bad_metrics, good_metrics]

        # Should not raise
        writer.write_stages(metrics_list)

        # Should have written the good records
        lines = writer.stages_jsonl.read_text().strip().split("\n")
        assert len(lines) == 2  # Two good records written

    def test_read_stages_returns_empty_if_missing(self, writer: MetricsWriter) -> None:
        """read_stages returns empty list if file doesn't exist."""
        assert writer.read_stages() == []

    def test_read_run_returns_none_if_missing(self, writer: MetricsWriter) -> None:
        """read_run returns None if file doesn't exist."""
        assert writer.read_run() is None


class TestMetricsWriterFlush:
    """Test that metrics are flushed properly."""

    def test_write_stage_flushes_immediately(
        self, writer: MetricsWriter, sample_stage_metrics: StageMetrics
    ) -> None:
        """write_stage flushes to disk immediately."""
        writer.write_stage(sample_stage_metrics)

        # Read directly from disk to verify flush
        content = writer.stages_jsonl.read_text()
        assert "plan" in content
        assert "test_run_123" in content

    def test_write_stages_flushes_after_batch(
        self, writer: MetricsWriter, sample_stage_metrics: StageMetrics
    ) -> None:
        """write_stages flushes after writing all records."""
        writer.write_stages([sample_stage_metrics] * 5)

        # Verify all records are on disk
        lines = writer.stages_jsonl.read_text().strip().split("\n")
        assert len(lines) == 5
