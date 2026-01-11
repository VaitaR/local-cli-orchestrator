"""Unit tests for dashboard partials helpers.

Tests the _build_metrics_context function which handles null/missing
model, executor, and token data for the metrics display.
"""

from __future__ import annotations

from orx.dashboard.handlers.partials import _build_metrics_context


class TestBuildMetricsContextModelPriority:
    """Tests for model priority (model > executor > fallback)."""

    def test_uses_run_model_when_present(self) -> None:
        """Test that run_metrics.model is used when present."""
        result = _build_metrics_context(
            run_metrics={"model": "gpt-4"},
            stage_metrics=[],
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        assert result["model"] == "gpt-4"
        # engine uses run_metrics.engine or fallback, not model
        assert result["engine"] == "fake"

    def test_uses_fallback_model_when_run_model_missing(self) -> None:
        """Test that fallback_model is used when run_metrics.model is missing."""
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=[],
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        assert result["model"] == "fake"
        assert result["engine"] == "fake"

    def test_uses_fallback_model_when_run_model_null(self) -> None:
        """Test that fallback_model is used when run_metrics.model is None."""
        result = _build_metrics_context(
            run_metrics={"model": None},
            stage_metrics=[],
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        assert result["model"] == "fake"
        assert result["engine"] == "fake"


class TestBuildMetricsContextTokenDataExtraction:
    """Tests for token data extraction with null handling."""

    def test_uses_run_tokens_when_present(self) -> None:
        """Test that run_metrics.tokens is used when present."""
        run_tokens = {"input": 100, "output": 50, "total": 150, "tool_calls": 5}
        result = _build_metrics_context(
            run_metrics={"tokens": run_tokens},
            stage_metrics=[],
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        assert result["tokens"] == run_tokens

    def test_aggregates_tokens_from_stages_when_run_tokens_missing(
        self,
    ) -> None:
        """Test that tokens are aggregated from stage_metrics when run_tokens is missing."""
        stage_metrics = [
            {
                "tokens": {
                    "input": 100,
                    "output": 50,
                    "total": 150,
                    "tool_calls": 2,
                },
                "duration_ms": 1000,
                "stage": "plan",
                "status": "success",
            },
            {
                "tokens": {
                    "input": 200,
                    "output": 100,
                    "total": 300,
                    "tool_calls": 3,
                },
                "duration_ms": 2000,
                "stage": "implement",
                "status": "success",
            },
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        assert result["tokens"] == {
            "input": 300,
            "output": 150,
            "total": 450,
            "tool_calls": 5,
        }

    def test_handles_null_values_in_stage_tokens(self) -> None:
        """Test that null values in stage tokens are handled as zero."""
        stage_metrics = [
            {
                "tokens": {
                    "input": None,
                    "output": None,
                    "total": 100,
                    "tool_calls": None,
                },
                "duration_ms": 1000,
                "stage": "plan",
                "status": "success",
            },
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        assert result["tokens"]["input"] == 0
        assert result["tokens"]["output"] == 0
        assert result["tokens"]["total"] == 100
        # tool_calls should not be included if 0
        assert "tool_calls" not in result["tokens"]

    def test_omits_tool_calls_when_zero(self) -> None:
        """Test that tool_calls is omitted when total is zero."""
        stage_metrics = [
            {
                "tokens": {"input": 100, "output": 50, "total": 150, "tool_calls": 0},
                "duration_ms": 1000,
                "stage": "plan",
                "status": "success",
            },
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        assert result["tokens"]["input"] == 100
        assert result["tokens"]["output"] == 50
        assert result["tokens"]["total"] == 150
        assert "tool_calls" not in result["tokens"]

    def test_skips_non_dict_tokens_in_stages(self) -> None:
        """Test that non-dict tokens in stage_metrics are skipped."""
        stage_metrics = [
            {
                "tokens": {"input": 100, "output": 50, "total": 150},
                "duration_ms": 1000,
                "stage": "plan",
                "status": "success",
            },
            {
                "tokens": None,  # Should be skipped
                "duration_ms": 2000,
                "stage": "implement",
                "status": "success",
            },
            {
                "tokens": "invalid",  # Should be skipped
                "duration_ms": 3000,
                "stage": "verify",
                "status": "success",
            },
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        assert result["tokens"]["total"] == 150

    def test_returns_none_tokens_when_no_tokens_available(self) -> None:
        """Test that tokens is None when no tokens are available."""
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=[],
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        assert result["tokens"] is None


class TestBuildMetricsContextStageModelInfo:
    """Tests for stage-level model and executor information."""

    def test_stage_includes_model_executor_original_model(self) -> None:
        """Test that stage includes model, executor, and original_model."""
        stage_metrics = [
            {
                "model": "gpt-4",
                "executor": "codex",
                "original_model": "gpt-4-turbo",
                "fallback_applied": True,
                "duration_ms": 1000,
                "stage": "plan",
                "status": "success",
            }
        ]
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
        assert stage["original_model"] == "gpt-4-turbo"
        assert stage["fallback_applied"] is True

    def test_stage_handles_null_model_executor(self) -> None:
        """Test that stage handles null model and executor."""
        stage_metrics = [
            {
                "model": None,
                "executor": None,
                "fallback_applied": False,
                "duration_ms": 1000,
                "stage": "plan",
                "status": "success",
            }
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fallback-model",  # Has fallback but keys are present
        )
        stage = result["stages"][0]
        # Keys are present with None values - respect explicit None
        assert stage["model"] is None
        assert stage["executor"] is None
        assert stage["fallback_applied"] is False

    def test_stage_uses_fallback_model_when_both_missing(
        self,
    ) -> None:
        """Test that stage uses fallback_model when both model and executor are missing."""
        stage_metrics = [
            {
                # Missing model and executor fields entirely
                "duration_ms": 1000,
                "stage": "plan",
                "status": "success",
            }
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="codex",  # Should be used as fallback
        )
        stage = result["stages"][0]
        # Keys are NOT present - use fallback
        assert stage["model"] == "codex"
        assert stage["executor"] is None
        assert stage["fallback_applied"] is False

    def test_stage_uses_executor_when_model_missing(self) -> None:
        """Test that stage displays executor when model is missing."""
        stage_metrics = [
            {
                "executor": "fake",
                "duration_ms": 1000,
                "stage": "plan",
                "status": "success",
            }
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="codex",
        )
        stage = result["stages"][0]
        # model should be None so template uses executor
        assert stage["model"] is None
        assert stage["executor"] == "fake"


class TestBuildMetricsContextToolCallsExtraction:
    """Tests for tool_calls extraction with missing/null cases."""

    def test_includes_tool_calls_when_present(self) -> None:
        """Test that tool_calls is included when present."""
        stage_metrics = [
            {
                "tokens": {
                    "input": 100,
                    "output": 50,
                    "total": 150,
                    "tool_calls": 5,
                },
                "duration_ms": 1000,
                "stage": "plan",
                "status": "success",
            }
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        assert result["tokens"]["tool_calls"] == 5

    def test_handles_missing_tool_calls_key(self) -> None:
        """Test that missing tool_calls key is handled."""
        stage_metrics = [
            {
                "tokens": {"input": 100, "output": 50, "total": 150},
                "duration_ms": 1000,
                "stage": "plan",
                "status": "success",
            }
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        # tool_calls should not be in result when missing
        assert "tool_calls" not in result["tokens"]


class TestBuildMetricsContextAllNullScenario:
    """Tests for all-null scenario showing fallback behavior."""

    def test_all_null_returns_fallback_values(self) -> None:
        """Test that all-null scenario returns fallback values."""
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=[],
            fallback_duration_ms=10000,
            fallback_model="fallback-model",
        )
        assert result["model"] == "fallback-model"
        assert result["engine"] == "fallback-model"
        assert result["tokens"] is None
        assert result["duration"] == 10.0  # 10000ms / 1000


class TestBuildMetricsContextEdgeCases:
    """Tests for edge cases: zero tokens, missing subfields, empty dict."""

    def test_zero_tokens_in_stage(self) -> None:
        """Test that zero tokens are handled correctly."""
        stage_metrics = [
            {
                "tokens": {"input": 0, "output": 0, "total": 0, "tool_calls": 0},
                "duration_ms": 1000,
                "stage": "plan",
                "status": "success",
            }
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        # Should not include tokens dict when total is 0
        assert result["tokens"] is None

    def test_missing_subfields_in_tokens(self) -> None:
        """Test that missing subfields in tokens are handled."""
        stage_metrics = [
            {
                "tokens": {"total": 100},  # Missing input, output
                "duration_ms": 1000,
                "stage": "plan",
                "status": "success",
            }
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        assert result["tokens"]["total"] == 100
        assert result["tokens"]["input"] == 0
        assert result["tokens"]["output"] == 0

    def test_empty_stage_metrics_list(self) -> None:
        """Test that empty stage_metrics list is handled."""
        result = _build_metrics_context(
            run_metrics={"model": "test-model"},
            stage_metrics=[],
            fallback_duration_ms=5000,
            fallback_model="fallback",
        )
        assert result["model"] == "test-model"
        assert result["stages"] == []
        assert result["tokens"] is None

    def test_stage_with_null_tokens_dict(self) -> None:
        """Test that stage with null tokens dict is handled."""
        stage_metrics = [
            {
                "tokens": None,
                "duration_ms": 1000,
                "stage": "plan",
                "status": "success",
            }
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        stage = result["stages"][0]
        assert stage["tokens"] is None
        assert stage["tokens_in"] is None
        assert stage["tokens_out"] is None
        assert stage["tool_calls"] is None


class TestBuildMetricsContextErrorHandling:
    """Tests for error handling in stages."""

    def test_stage_error_display_from_error_info(self) -> None:
        """Test that error display uses error_info.message when available."""
        stage_metrics = [
            {
                "error_info": {"message": "Test error message"},
                "failure_message": "Fallback message",
                "duration_ms": 1000,
                "stage": "plan",
                "status": "fail",
            }
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        stage = result["stages"][0]
        assert stage["error"] == "Test error message"

    def test_stage_error_display_from_failure_message(self) -> None:
        """Test that error display uses failure_message when error_info missing."""
        stage_metrics = [
            {
                "failure_message": "Fallback message",
                "duration_ms": 1000,
                "stage": "plan",
                "status": "fail",
            }
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        stage = result["stages"][0]
        assert stage["error"] == "Fallback message"

    def test_stage_no_error_when_both_missing(self) -> None:
        """Test that error is None when both error_info and failure_message missing."""
        stage_metrics = [
            {
                "duration_ms": 1000,
                "stage": "plan",
                "status": "success",
            }
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        stage = result["stages"][0]
        assert stage["error"] is None


class TestBuildMetricsContextDurationAndTiming:
    """Tests for duration and timing calculations."""

    def test_duration_from_run_metrics(self) -> None:
        """Test that duration is calculated from run_metrics.total_duration_ms."""
        result = _build_metrics_context(
            run_metrics={"total_duration_ms": 15000},
            stage_metrics=[],
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        assert result["duration"] == 15.0  # 15000ms / 1000

    def test_duration_uses_fallback_when_missing(self) -> None:
        """Test that duration uses fallback when total_duration_ms missing."""
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=[],
            fallback_duration_ms=8000,
            fallback_model="fake",
        )
        assert result["duration"] == 8.0  # 8000ms / 1000

    def test_llm_duration_summed_from_stages(self) -> None:
        """Test that llm_duration is summed from all stages."""
        stage_metrics = [
            {
                "llm_duration_ms": 2000,
                "duration_ms": 3000,
                "stage": "plan",
                "status": "success",
            },
            {
                "llm_duration_ms": 3000,
                "duration_ms": 5000,
                "stage": "implement",
                "status": "success",
            },
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        assert result["llm_duration"] == 5.0  # (2000 + 3000)ms / 1000

    def test_stage_duration_in_seconds(self) -> None:
        """Test that stage duration is converted to seconds."""
        stage_metrics = [
            {
                "duration_ms": 3500,
                "stage": "plan",
                "status": "success",
            }
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        stage = result["stages"][0]
        assert stage["duration"] == 3.5  # 3500ms / 1000

    def test_stage_llm_duration_in_seconds(self) -> None:
        """Test that stage llm_duration is converted to seconds."""
        stage_metrics = [
            {
                "llm_duration_ms": 2500,
                "duration_ms": 3000,
                "stage": "plan",
                "status": "success",
            }
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        stage = result["stages"][0]
        assert stage["llm_duration"] == 2.5  # 2500ms / 1000


class TestBuildMetricsContextRunMetrics:
    """Tests for run-level metrics fields."""

    def test_fix_loops_from_run_metrics(self) -> None:
        """Test that fix_loops is extracted from run_metrics."""
        result = _build_metrics_context(
            run_metrics={"fix_attempts_total": 3},
            stage_metrics=[],
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        assert result["fix_loops"] == 3

    def test_items_counts_from_run_metrics(self) -> None:
        """Test that items counts are extracted from run_metrics."""
        result = _build_metrics_context(
            run_metrics={
                "items_total": 10,
                "items_completed": 8,
                "items_failed": 2,
                "stages_failed": 1,
            },
            stage_metrics=[],
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        assert result["items_total"] == 10
        assert result["items_completed"] == 8
        assert result["items_failed"] == 2
        assert result["stages_failed"] == 1

    def test_default_values_for_missing_run_metrics(self) -> None:
        """Test that defaults are used for missing run_metrics fields."""
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=[],
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        assert result["fix_loops"] is None
        assert result["items_total"] == 0
        assert result["items_completed"] == 0
        assert result["items_failed"] == 0
        assert result["stages_failed"] == 0


class TestBuildMetricsContextStageFields:
    """Tests for stage field extraction and formatting."""

    def test_stage_basic_fields(self) -> None:
        """Test that basic stage fields are extracted."""
        stage_metrics = [
            {
                "stage": "implement",
                "item_id": "W001",
                "attempt": 2,
                "status": "success",
                "duration_ms": 5000,
                "failure_category": "test_failure",
            }
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        stage = result["stages"][0]
        assert stage["name"] == "implement"
        assert stage["item_id"] == "W001"
        assert stage["attempt"] == 2
        assert stage["status"] == "success"
        assert stage["failure_category"] == "test_failure"

    def test_stage_default_attempt(self) -> None:
        """Test that stage defaults to attempt 1 when missing."""
        stage_metrics = [
            {
                "stage": "plan",
                "status": "success",
                "duration_ms": 1000,
            }
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        stage = result["stages"][0]
        assert stage["attempt"] == 1

    def test_stage_gates_list(self) -> None:
        """Test that stage gates list is extracted."""
        stage_metrics = [
            {
                "stage": "verify",
                "status": "success",
                "duration_ms": 1000,
                "gates": [
                    {"name": "ruff", "passed": True},
                    {"name": "pytest", "passed": True},
                ],
            }
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        stage = result["stages"][0]
        assert len(stage["gates"]) == 2
        assert stage["gates"][0]["name"] == "ruff"
        assert stage["gates"][1]["name"] == "pytest"

    def test_stage_default_gates_to_empty_list(self) -> None:
        """Test that stage gates defaults to empty list."""
        stage_metrics = [
            {
                "stage": "plan",
                "status": "success",
                "duration_ms": 1000,
            }
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        stage = result["stages"][0]
        assert stage["gates"] == []

    def test_stage_tokens_fields_when_tokens_is_dict(self) -> None:
        """Test that stage token fields are extracted when tokens is dict."""
        stage_metrics = [
            {
                "tokens": {
                    "total": 150,
                    "input": 100,
                    "output": 50,
                    "tool_calls": 3,
                },
                "duration_ms": 1000,
                "stage": "plan",
                "status": "success",
            }
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        stage = result["stages"][0]
        assert stage["tokens"] == 150
        assert stage["tokens_in"] == 100
        assert stage["tokens_out"] == 50
        assert stage["tool_calls"] == 3

    def test_stage_tokens_fields_when_tokens_not_dict(self) -> None:
        """Test that stage token fields are None when tokens is not dict."""
        stage_metrics = [
            {
                "tokens": None,
                "duration_ms": 1000,
                "stage": "plan",
                "status": "success",
            }
        ]
        result = _build_metrics_context(
            run_metrics={},
            stage_metrics=stage_metrics,
            fallback_duration_ms=5000,
            fallback_model="fake",
        )
        stage = result["stages"][0]
        assert stage["tokens"] is None
        assert stage["tokens_in"] is None
        assert stage["tokens_out"] is None
        assert stage["tool_calls"] is None
