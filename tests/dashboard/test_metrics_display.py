"""Integration tests for metrics display with real data scenarios.

Tests the complete flow from filesystem -> FileSystemRunStore -> _build_metrics_context()
to verify that metrics tab renders correctly with various data scenarios including null
values, partial data, and valid metrics.

This addresses the issue where model, tokens, and other columns were not displaying
in the frontend for certain runs (e.g., run 20260111_134427_f0c6d2e8).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orx.dashboard.handlers.partials import _build_metrics_context
from orx.dashboard.store.filesystem import FileSystemRunStore


@pytest.fixture
def temp_run_dir(tmp_path: Path) -> Path:
    """Create a temporary run directory with metrics subdirectory.

    Args:
        tmp_path: Pytest temporary directory fixture.

    Returns:
        Path to the temporary run directory.
    """
    run_dir = tmp_path / "test_run_20260111_134427"
    run_dir.mkdir()
    (run_dir / "metrics").mkdir()
    (run_dir / "logs").mkdir()
    (run_dir / "artifacts").mkdir()
    (run_dir / "context").mkdir()

    # Create minimal meta.json and state.json for run detection
    (run_dir / "meta.json").write_text(
        json.dumps(
            {
                "created_at": "2026-01-11T13:44:27Z",
                "repo_path": "/fake/repo",
                "engine": "fake",
            }
        )
    )
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "current_stage": "done",
                "stage_statuses": {},
                "created_at": "2026-01-11T13:44:27Z",
                "updated_at": "2026-01-11T13:50:00Z",
            }
        )
    )

    return run_dir


class TestFileSystemRunStoreReadsMetrics:
    """Tests for FileSystemRunStore reading metrics from filesystem."""

    def test_get_run_metrics_returns_valid_data(self, temp_run_dir: Path) -> None:
        """Test that get_run_metrics returns valid metrics data."""
        # Create run.json with valid metrics
        run_json = temp_run_dir / "metrics" / "run.json"
        run_json.write_text(
            json.dumps(
                {
                    "run_id": "test_run",
                    "start_ts": "2026-01-11T13:44:27Z",
                    "end_ts": "2026-01-11T13:50:00Z",
                    "total_duration_ms": 330000,
                    "model": "gpt-4",
                    "engine": "codex",
                    "stages_executed": 5,
                    "stages_failed": 0,
                    "tokens": {
                        "input": 1000,
                        "output": 500,
                        "total": 1500,
                        "tool_calls": 10,
                    },
                }
            )
        )

        store = FileSystemRunStore(temp_run_dir.parent)
        metrics = store.get_run_metrics("test_run_20260111_134427")

        assert metrics is not None
        assert metrics["model"] == "gpt-4"
        assert metrics["engine"] == "codex"
        assert metrics["tokens"]["total"] == 1500

    def test_get_run_metrics_returns_none_when_missing(
        self, temp_run_dir: Path
    ) -> None:
        """Test that get_run_metrics returns None when run.json doesn't exist."""
        store = FileSystemRunStore(temp_run_dir.parent)
        metrics = store.get_run_metrics("test_run_20260111_134427")

        assert metrics is None

    def test_get_stage_metrics_returns_list(self, temp_run_dir: Path) -> None:
        """Test that get_stage_metrics returns list of stage metrics."""
        stages_jsonl = temp_run_dir / "metrics" / "stages.jsonl"
        stages_jsonl.write_text(
            json.dumps(
                {
                    "run_id": "test_run",
                    "stage": "plan",
                    "attempt": 1,
                    "start_ts": "2026-01-11T13:44:27Z",
                    "end_ts": "2026-01-11T13:45:00Z",
                    "duration_ms": 33000,
                    "status": "success",
                    "model": "gpt-4",
                    "executor": "codex",
                    "tokens": {
                        "input": 500,
                        "output": 200,
                        "total": 700,
                    },
                }
            )
            + "\n"
            + json.dumps(
                {
                    "run_id": "test_run",
                    "stage": "implement",
                    "attempt": 1,
                    "start_ts": "2026-01-11T13:45:00Z",
                    "end_ts": "2026-01-11T13:48:00Z",
                    "duration_ms": 180000,
                    "status": "success",
                    "model": None,
                    "executor": "fake",
                    "tokens": {
                        "input": 300,
                        "output": 200,
                        "total": 500,
                    },
                }
            )
            + "\n"
        )

        store = FileSystemRunStore(temp_run_dir.parent)
        stage_metrics = store.get_stage_metrics("test_run_20260111_134427")

        assert len(stage_metrics) == 2
        assert stage_metrics[0]["stage"] == "plan"
        assert stage_metrics[0]["model"] == "gpt-4"
        assert stage_metrics[1]["stage"] == "implement"
        assert stage_metrics[1]["model"] is None

    def test_get_stage_metrics_returns_empty_list_when_missing(
        self, temp_run_dir: Path
    ) -> None:
        """Test that get_stage_metrics returns empty list when stages.jsonl doesn't exist."""
        store = FileSystemRunStore(temp_run_dir.parent)
        stage_metrics = store.get_stage_metrics("test_run_20260111_134427")

        assert stage_metrics == []


class TestBuildMetricsContextValidModel:
    """Tests for _build_metrics_context with valid model data."""

    def test_valid_model_in_stages(self, temp_run_dir: Path) -> None:
        """Test that valid model in stages is displayed correctly."""
        stages_jsonl = temp_run_dir / "metrics" / "stages.jsonl"
        stages_jsonl.write_text(
            json.dumps(
                {
                    "run_id": "test_run",
                    "stage": "plan",
                    "status": "success",
                    "duration_ms": 1000,
                    "model": "gpt-4",
                    "executor": "codex",
                    "tokens": {"input": 100, "output": 50, "total": 150},
                }
            )
            + "\n"
        )

        store = FileSystemRunStore(temp_run_dir.parent)
        stage_metrics = store.get_stage_metrics("test_run_20260111_134427")

        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )

        assert len(result["stages"]) == 1
        stage = result["stages"][0]
        assert stage["model"] == "gpt-4"
        assert stage["executor"] == "codex"
        assert stage["tokens"] == 150
        assert stage["tokens_in"] == 100
        assert stage["tokens_out"] == 50


class TestBuildMetricsContextNullModelWithExecutor:
    """Tests for _build_metrics_context with null model but valid executor."""

    def test_null_model_with_executor_shows_executor(self, temp_run_dir: Path) -> None:
        """Test that null model with executor shows executor in display."""
        stages_jsonl = temp_run_dir / "metrics" / "stages.jsonl"
        stages_jsonl.write_text(
            json.dumps(
                {
                    "run_id": "test_run",
                    "stage": "implement",
                    "status": "success",
                    "duration_ms": 5000,
                    "model": None,
                    "executor": "fake",
                    "tokens": {"input": 200, "output": 100, "total": 300},
                }
            )
            + "\n"
        )

        store = FileSystemRunStore(temp_run_dir.parent)
        stage_metrics = store.get_stage_metrics("test_run_20260111_134427")

        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fallback-model",
        )

        assert len(result["stages"]) == 1
        stage = result["stages"][0]
        assert stage["model"] is None
        assert stage["executor"] == "fake"
        assert stage["tokens"] == 300


class TestBuildMetricsContextAllNull:
    """Tests for _build_metrics_context with all null model/executor."""

    def test_all_null_model_executor(self, temp_run_dir: Path) -> None:
        """Test that all null model/executor renders correctly."""
        stages_jsonl = temp_run_dir / "metrics" / "stages.jsonl"
        stages_jsonl.write_text(
            json.dumps(
                {
                    "run_id": "test_run",
                    "stage": "spec",
                    "status": "success",
                    "duration_ms": 2000,
                    "model": None,
                    "executor": None,
                    "tokens": {"input": 150, "output": 50, "total": 200},
                }
            )
            + "\n"
        )

        store = FileSystemRunStore(temp_run_dir.parent)
        stage_metrics = store.get_stage_metrics("test_run_20260111_134427")

        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fallback",
        )

        assert len(result["stages"]) == 1
        stage = result["stages"][0]
        assert stage["model"] is None
        assert stage["executor"] is None
        # Stage should still have tokens
        assert stage["tokens"] == 200


class TestBuildMetricsContextPartialTokens:
    """Tests for _build_metrics_context with partial token data."""

    def test_partial_tokens_missing_input_output(self, temp_run_dir: Path) -> None:
        """Test that partial tokens (only total) are handled correctly."""
        stages_jsonl = temp_run_dir / "metrics" / "stages.jsonl"
        stages_jsonl.write_text(
            json.dumps(
                {
                    "run_id": "test_run",
                    "stage": "decompose",
                    "status": "success",
                    "duration_ms": 3000,
                    "model": "gpt-4",
                    "executor": "codex",
                    "tokens": {"total": 500},  # Missing input/output
                }
            )
            + "\n"
        )

        store = FileSystemRunStore(temp_run_dir.parent)
        stage_metrics = store.get_stage_metrics("test_run_20260111_134427")

        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )

        stage = result["stages"][0]
        # _build_metrics_context extracts available token fields
        assert stage["tokens"] == 500
        # When tokens dict exists but fields are missing, they are None
        assert stage["tokens_in"] is None
        assert stage["tokens_out"] is None


class TestBuildMetricsContextZeroTokens:
    """Tests for _build_metrics_context with zero token counts."""

    def test_zero_tokens(self, temp_run_dir: Path) -> None:
        """Test that zero tokens are handled (e.g., for stages without LLM calls)."""
        stages_jsonl = temp_run_dir / "metrics" / "stages.jsonl"
        stages_jsonl.write_text(
            json.dumps(
                {
                    "run_id": "test_run",
                    "stage": "ship",
                    "status": "success",
                    "duration_ms": 1000,
                    "model": None,
                    "executor": None,
                    "tokens": {"input": 0, "output": 0, "total": 0},
                }
            )
            + "\n"
        )

        store = FileSystemRunStore(temp_run_dir.parent)
        stage_metrics = store.get_stage_metrics("test_run_20260111_134427")

        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )

        # Run-level tokens should be None when total is 0
        assert result["tokens"] is None
        # But stage should still be present
        assert len(result["stages"]) == 1


class TestBuildMetricsContextMixedScenarios:
    """Tests for _build_metrics_context with mixed data scenarios."""

    def test_mixed_valid_and_null_models(self, temp_run_dir: Path) -> None:
        """Test run with mix of valid models and null models."""
        stages_jsonl = temp_run_dir / "metrics" / "stages.jsonl"
        stages_jsonl.write_text(
            json.dumps(
                {
                    "run_id": "test_run",
                    "stage": "plan",
                    "status": "success",
                    "duration_ms": 1000,
                    "model": "gpt-4",
                    "executor": "codex",
                    "tokens": {"input": 100, "output": 50, "total": 150},
                }
            )
            + "\n"
            + json.dumps(
                {
                    "run_id": "test_run",
                    "stage": "implement",
                    "status": "success",
                    "duration_ms": 5000,
                    "model": None,
                    "executor": "fake",
                    "tokens": {"input": 200, "output": 100, "total": 300},
                }
            )
            + "\n"
            + json.dumps(
                {
                    "run_id": "test_run",
                    "stage": "verify",
                    "status": "success",
                    "duration_ms": 2000,
                    "model": None,
                    "executor": None,
                    "tokens": None,  # No tokens for this stage
                }
            )
            + "\n"
        )

        store = FileSystemRunStore(temp_run_dir.parent)
        stage_metrics = store.get_stage_metrics("test_run_20260111_134427")

        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=8000,
            fallback_model="fallback",
        )

        assert len(result["stages"]) == 3
        assert result["stages"][0]["model"] == "gpt-4"
        assert result["stages"][1]["model"] is None
        assert result["stages"][1]["executor"] == "fake"
        assert result["stages"][2]["model"] is None
        assert result["stages"][2]["executor"] is None

        # Tokens should aggregate only from stages with valid tokens
        assert result["tokens"]["total"] == 450


class TestBuildMetricsContextRunLevelFallback:
    """Tests for run-level model/engine fallback behavior."""

    def test_run_level_model_with_stages_null(self, temp_run_dir: Path) -> None:
        """Test run-level model is used when stages have null models."""
        # Create run.json with model
        run_json = temp_run_dir / "metrics" / "run.json"
        run_json.write_text(
            json.dumps(
                {
                    "run_id": "test_run",
                    "start_ts": "2026-01-11T13:44:27Z",
                    "model": "gpt-4-turbo",
                    "engine": "codex",
                    "total_duration_ms": 10000,
                }
            )
        )

        # Create stages.jsonl with null models
        stages_jsonl = temp_run_dir / "metrics" / "stages.jsonl"
        stages_jsonl.write_text(
            json.dumps(
                {
                    "run_id": "test_run",
                    "stage": "plan",
                    "status": "success",
                    "duration_ms": 1000,
                    "model": None,
                    "executor": None,
                }
            )
            + "\n"
        )

        store = FileSystemRunStore(temp_run_dir.parent)
        run_metrics = store.get_run_metrics("test_run_20260111_134427")
        stage_metrics = store.get_stage_metrics("test_run_20260111_134427")

        result = _build_metrics_context(
            run_metrics=run_metrics or {},
            stage_metrics=stage_metrics,
            fallback_duration_ms=10000,
            fallback_model="fallback",
        )

        # Run-level model should be used
        assert result["model"] == "gpt-4-turbo"
        assert result["engine"] == "codex"


class TestBuildMetricsContextStructure:
    """Tests for correct structure of returned context dict."""

    def test_context_dict_has_all_required_fields(self, temp_run_dir: Path) -> None:
        """Test that context dict contains all required fields."""
        stages_jsonl = temp_run_dir / "metrics" / "stages.jsonl"
        stages_jsonl.write_text(
            json.dumps(
                {
                    "run_id": "test_run",
                    "stage": "plan",
                    "status": "success",
                    "duration_ms": 5000,
                    "model": "gpt-4",
                    "executor": "codex",
                    "tokens": {"input": 100, "output": 50, "total": 150},
                }
            )
            + "\n"
        )

        store = FileSystemRunStore(temp_run_dir.parent)
        stage_metrics = store.get_stage_metrics("test_run_20260111_134427")

        result = _build_metrics_context(
            run_metrics={
                "total_duration_ms": 10000,
                "model": "gpt-4",
                "engine": "codex",
            },
            stage_metrics=stage_metrics,
            fallback_duration_ms=10000,
            fallback_model="fallback",
        )

        # Check run-level fields
        assert "tokens" in result
        assert "duration" in result
        assert "llm_duration" in result
        assert "model" in result
        assert "engine" in result
        assert "stages" in result
        assert "fix_loops" in result
        assert "items_total" in result
        assert "items_completed" in result
        assert "items_failed" in result
        assert "stages_failed" in result

        # Check stage-level fields
        stage = result["stages"][0]
        assert "name" in stage
        assert "item_id" in stage
        assert "attempt" in stage
        assert "duration" in stage
        assert "status" in stage
        assert "tokens" in stage
        assert "tokens_in" in stage
        assert "tokens_out" in stage
        assert "tool_calls" in stage
        assert "model" in stage
        assert "executor" in stage
        assert "fallback_applied" in stage
        assert "original_model" in stage
        assert "error" in stage
        assert "failure_category" in stage
        assert "llm_duration" in stage
        assert "gates" in stage
