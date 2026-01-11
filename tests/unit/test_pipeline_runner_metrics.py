"""Unit tests for PipelineRunner metrics integration."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orx.config import EngineConfig, EngineType, OrxConfig
from orx.metrics.schema import StageStatus
from orx.metrics.writer import MetricsWriter
from orx.paths import RunPaths
from orx.pipeline.definition import NodeDefinition, NodeType
from orx.pipeline.runner import NodeMetrics, PipelineRunner

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_paths():
    """Create temporary run paths."""
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = RunPaths.create_new(Path(tmpdir))
        yield paths


@pytest.fixture
def mock_config():
    """Create mock ORX config."""
    return OrxConfig(
        engine=EngineConfig(type=EngineType.CODEX),
    )


@pytest.fixture
def mock_workspace():
    """Create mock workspace."""
    workspace = MagicMock()
    workspace.worktree_path = Path("/tmp/test")
    return workspace


@pytest.fixture
def mock_executor():
    """Create mock executor."""
    executor = MagicMock()
    return executor


@pytest.fixture
def mock_gates():
    """Create mock gates list."""
    return []


@pytest.fixture
def metrics_writer(temp_paths):
    """Create MetricsWriter instance."""
    return MetricsWriter(temp_paths)


@pytest.fixture
def pipeline_runner(mock_config, temp_paths, mock_workspace, mock_executor, mock_gates, metrics_writer):
    """Create PipelineRunner with metrics writer."""
    from orx.prompts.renderer import PromptRenderer

    renderer = PromptRenderer()
    return PipelineRunner(
        config=mock_config,
        paths=temp_paths,
        workspace=mock_workspace,
        executor=mock_executor,
        gates=mock_gates,
        renderer=renderer,
        metrics_writer=metrics_writer,
    )


# ============================================================================
# _convert_node_metrics Tests
# ============================================================================


class TestConvertNodeMetrics:
    """Tests for _convert_node_metrics method."""

    def test_convert_success_case(self, pipeline_runner):
        """Test converting successful node metrics."""
        node_metrics = NodeMetrics(
            node_id="plan",
            node_type="llm_text",
            duration_ms=1000,
            success=True,
            outputs=["plan"],
            extra={},
        )
        start_ts = datetime.now(tz=UTC)

        stage_metrics = pipeline_runner._convert_node_metrics(node_metrics, start_ts)

        assert stage_metrics.run_id == pipeline_runner.paths.run_id
        assert stage_metrics.stage == "plan"
        assert stage_metrics.status == StageStatus.SUCCESS
        assert stage_metrics.duration_ms == 1000
        assert stage_metrics.failure_message is None

    def test_convert_failure_case(self, pipeline_runner):
        """Test converting failed node metrics."""
        node_metrics = NodeMetrics(
            node_id="implement",
            node_type="llm_apply",
            duration_ms=5000,
            success=False,
            error="Test error message",
            outputs=[],
            extra={},
        )
        start_ts = datetime.now(tz=UTC)

        stage_metrics = pipeline_runner._convert_node_metrics(node_metrics, start_ts)

        assert stage_metrics.stage == "implement"
        assert stage_metrics.status == StageStatus.FAIL
        assert stage_metrics.failure_message == "Test error message"
        assert stage_metrics.duration_ms == 5000

    def test_convert_with_tokens(self, pipeline_runner):
        """Test converting metrics with token usage."""
        node_metrics = NodeMetrics(
            node_id="spec",
            node_type="llm_text",
            duration_ms=2000,
            success=True,
            extra={
                "tokens": {
                    "input": 1000,
                    "output": 500,
                    "total": 1500,
                    "tool_calls": 5,
                }
            },
        )
        start_ts = datetime.now(tz=UTC)

        stage_metrics = pipeline_runner._convert_node_metrics(node_metrics, start_ts)

        assert stage_metrics.tokens is not None
        assert stage_metrics.tokens.input == 1000
        assert stage_metrics.tokens.output == 500
        assert stage_metrics.tokens.total == 1500
        assert stage_metrics.tokens.tool_calls == 5

    def test_convert_with_gates(self, pipeline_runner):
        """Test converting metrics with gate results."""
        node_metrics = NodeMetrics(
            node_id="verify",
            node_type="gate",
            duration_ms=3000,
            success=True,
            extra={
                "gates": [
                    {
                        "name": "ruff",
                        "exit_code": 0,
                        "duration_ms": 500,
                        "passed": True,
                    },
                    {
                        "name": "pytest",
                        "exit_code": 1,
                        "duration_ms": 2000,
                        "passed": False,
                        "tests_failed": 2,
                        "tests_total": 10,
                    },
                ]
            },
        )
        start_ts = datetime.now(tz=UTC)

        stage_metrics = pipeline_runner._convert_node_metrics(node_metrics, start_ts)

        assert len(stage_metrics.gates) == 2
        assert stage_metrics.gates[0].name == "ruff"
        assert stage_metrics.gates[0].passed is True
        assert stage_metrics.gates[1].name == "pytest"
        assert stage_metrics.gates[1].passed is False
        assert stage_metrics.gates[1].tests_failed == 2

    def test_convert_with_both_tokens_and_gates(self, pipeline_runner):
        """Test converting metrics with both tokens and gates."""
        node_metrics = NodeMetrics(
            node_id="implement",
            node_type="llm_apply",
            duration_ms=10000,
            success=True,
            extra={
                "tokens": {
                    "input": 2000,
                    "output": 1000,
                    "total": 3000,
                },
                "gates": [
                    {
                        "name": "ruff",
                        "exit_code": 0,
                        "duration_ms": 300,
                        "passed": True,
                    }
                ],
            },
        )
        start_ts = datetime.now(tz=UTC)

        stage_metrics = pipeline_runner._convert_node_metrics(node_metrics, start_ts)

        assert stage_metrics.tokens is not None
        assert stage_metrics.tokens.total == 3000
        assert len(stage_metrics.gates) == 1
        assert stage_metrics.gates[0].name == "ruff"

    def test_convert_without_extra_data(self, pipeline_runner):
        """Test converting metrics without extra data."""
        node_metrics = NodeMetrics(
            node_id="review",
            node_type="llm_text",
            duration_ms=1500,
            success=True,
        )
        start_ts = datetime.now(tz=UTC)

        stage_metrics = pipeline_runner._convert_node_metrics(node_metrics, start_ts)

        assert stage_metrics.stage == "review"
        assert stage_metrics.status == StageStatus.SUCCESS
        assert stage_metrics.tokens is None
        assert len(stage_metrics.gates) == 0

    def test_convert_preserves_timestamps(self, pipeline_runner):
        """Test that timestamps are correctly converted."""
        node_metrics = NodeMetrics(
            node_id="plan",
            node_type="llm_text",
            duration_ms=1000,
            success=True,
        )
        start_ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

        stage_metrics = pipeline_runner._convert_node_metrics(node_metrics, start_ts)

        assert stage_metrics.start_ts == "2024-01-01T12:00:00+00:00"
        assert stage_metrics.end_ts == "2024-01-01T12:00:00+00:00"


# ============================================================================
# Metrics Writing Tests
# ============================================================================


class TestMetricsWriting:
    """Tests for metrics writing integration."""

    @patch("orx.pipeline.runner.PipelineRunner._execute_node")
    def test_metrics_writer_receives_data(self, mock_execute, pipeline_runner, temp_paths):
        """Test that metrics writer receives stage metrics after node execution."""
        from orx.pipeline.definition import PipelineDefinition
        from orx.pipeline.executors.base import NodeResult

        node = NodeDefinition(id="plan", type=NodeType.LLM_TEXT)
        pipeline = PipelineDefinition(id="test", name="Test", nodes=[node])

        # Mock the executor to return success
        mock_execute.return_value = NodeResult(
            success=True,
            outputs={"plan": "test plan"},
            metrics={},
        )

        # Run pipeline
        pipeline_runner.run(pipeline, "Test task")

        # Check that metrics were written
        writer = MetricsWriter(temp_paths)
        stage_metrics_list = writer.read_stages()

        assert len(stage_metrics_list) == 1
        stage_metrics = stage_metrics_list[0]
        assert stage_metrics.stage == "plan"
        assert stage_metrics.status == StageStatus.SUCCESS

    @patch("orx.pipeline.runner.PipelineRunner._execute_node")
    def test_metrics_writer_handles_failure(self, mock_execute, pipeline_runner, temp_paths):
        """Test that failed node metrics are written correctly."""
        from orx.pipeline.definition import PipelineDefinition
        from orx.pipeline.executors.base import NodeResult

        node = NodeDefinition(id="plan", type=NodeType.LLM_TEXT)
        pipeline = PipelineDefinition(id="test", name="Test", nodes=[node])

        # Mock executor to fail
        mock_execute.return_value = NodeResult(
            success=False,
            error="Simulated failure",
            outputs={},
            metrics={},
        )

        # Run pipeline
        pipeline_runner.run(pipeline, "Test task")

        # Check that failure metrics were written
        writer = MetricsWriter(temp_paths)
        stage_metrics_list = writer.read_stages()

        assert len(stage_metrics_list) == 1
        stage_metrics = stage_metrics_list[0]
        assert stage_metrics.status == StageStatus.FAIL
        assert stage_metrics.failure_message == "Simulated failure"

    @patch("orx.pipeline.runner.PipelineRunner._execute_node")
    def test_metrics_writer_without_writer_doesnt_crash(self, mock_execute, mock_config, temp_paths, mock_workspace, mock_executor, mock_gates):
        """Test that pipeline runs without metrics writer."""
        from orx.pipeline.definition import PipelineDefinition
        from orx.pipeline.executors.base import NodeResult
        from orx.prompts.renderer import PromptRenderer

        # Create runner without metrics writer
        renderer = PromptRenderer()
        runner = PipelineRunner(
            config=mock_config,
            paths=temp_paths,
            workspace=mock_workspace,
            executor=mock_executor,
            gates=mock_gates,
            renderer=renderer,
            metrics_writer=None,
        )

        node = NodeDefinition(id="plan", type=NodeType.LLM_TEXT)
        pipeline = PipelineDefinition(id="test", name="Test", nodes=[node])

        mock_execute.return_value = NodeResult(
            success=True,
            outputs={"plan": "test"},
            metrics={},
        )

        # Should not raise
        result = runner.run(pipeline, "Test task")
        assert result.success is True

    @patch("orx.pipeline.runner.PipelineRunner._execute_node")
    def test_metrics_writer_error_doesnt_crash_pipeline(self, mock_execute, pipeline_runner):
        """Test that metrics write errors don't crash the pipeline."""
        from orx.pipeline.definition import PipelineDefinition
        from orx.pipeline.executors.base import NodeResult

        node = NodeDefinition(id="plan", type=NodeType.LLM_TEXT)
        pipeline = PipelineDefinition(id="test", name="Test", nodes=[node])

        # Mock writer to raise exception
        failing_writer = MagicMock(spec=MetricsWriter)
        failing_writer.write_stage.side_effect = OSError("Disk full")

        pipeline_runner.metrics_writer = failing_writer

        mock_execute.return_value = NodeResult(
            success=True,
            outputs={"plan": "test"},
            metrics={},
        )

        # Should not raise despite metrics write failure
        result = pipeline_runner.run(pipeline, "Test task")
        assert result.success is True


# ============================================================================
# Edge Case Handling Tests
# ============================================================================


class TestEdgeCaseHandling:
    """Tests for edge case handling in metrics conversion."""

    def test_convert_with_missing_tokens_field(self, pipeline_runner):
        """Test converting metrics when tokens field is missing."""
        node_metrics = NodeMetrics(
            node_id="plan",
            node_type="llm_text",
            duration_ms=1000,
            success=True,
            extra={},  # No tokens field
        )
        start_ts = datetime.now(tz=UTC)

        stage_metrics = pipeline_runner._convert_node_metrics(node_metrics, start_ts)

        assert stage_metrics.tokens is None
        assert stage_metrics.status == StageStatus.SUCCESS

    def test_convert_with_none_tokens(self, pipeline_runner):
        """Test converting metrics when tokens field is explicitly None."""
        node_metrics = NodeMetrics(
            node_id="spec",
            node_type="llm_text",
            duration_ms=2000,
            success=True,
            extra={"tokens": None},
        )
        start_ts = datetime.now(tz=UTC)

        stage_metrics = pipeline_runner._convert_node_metrics(node_metrics, start_ts)

        assert stage_metrics.tokens is None

    def test_convert_with_malformed_tokens_dict(self, pipeline_runner):
        """Test converting metrics with malformed token data (missing required fields)."""
        node_metrics = NodeMetrics(
            node_id="implement",
            node_type="llm_apply",
            duration_ms=5000,
            success=True,
            extra={
                "tokens": {
                    "input": "not_a_number",  # Invalid type
                    "output": 100,
                }
            },
        )
        start_ts = datetime.now(tz=UTC)

        # Should not crash, should log error and return None for tokens
        stage_metrics = pipeline_runner._convert_node_metrics(node_metrics, start_ts)

        assert stage_metrics.tokens is None
        assert stage_metrics.status == StageStatus.SUCCESS

    def test_convert_with_non_dict_tokens(self, pipeline_runner):
        """Test converting metrics when tokens field is not a dict."""
        node_metrics = NodeMetrics(
            node_id="review",
            node_type="llm_text",
            duration_ms=1500,
            success=True,
            extra={"tokens": "invalid"},  # String instead of dict
        )
        start_ts = datetime.now(tz=UTC)

        stage_metrics = pipeline_runner._convert_node_metrics(node_metrics, start_ts)

        assert stage_metrics.tokens is None

    def test_convert_with_missing_gates_field(self, pipeline_runner):
        """Test converting metrics when gates field is missing."""
        node_metrics = NodeMetrics(
            node_id="plan",
            node_type="llm_text",
            duration_ms=1000,
            success=True,
            extra={},  # No gates field
        )
        start_ts = datetime.now(tz=UTC)

        stage_metrics = pipeline_runner._convert_node_metrics(node_metrics, start_ts)

        assert len(stage_metrics.gates) == 0

    def test_convert_with_non_list_gates(self, pipeline_runner):
        """Test converting metrics when gates field is not a list."""
        node_metrics = NodeMetrics(
            node_id="verify",
            node_type="gate",
            duration_ms=3000,
            success=True,
            extra={"gates": "not_a_list"},  # Invalid type
        )
        start_ts = datetime.now(tz=UTC)

        stage_metrics = pipeline_runner._convert_node_metrics(node_metrics, start_ts)

        assert len(stage_metrics.gates) == 0

    def test_convert_with_malformed_gate_item(self, pipeline_runner):
        """Test converting metrics with a malformed gate item in the list."""
        node_metrics = NodeMetrics(
            node_id="verify",
            node_type="gate",
            duration_ms=3000,
            success=True,
            extra={
                "gates": [
                    {
                        "name": "ruff",
                        "exit_code": 0,
                        "duration_ms": 500,
                        "passed": True,
                    },
                    {
                        # Missing required fields
                        "name": "pytest",
                    },
                ]
            },
        )
        start_ts = datetime.now(tz=UTC)

        # Should not crash, should skip the malformed gate
        stage_metrics = pipeline_runner._convert_node_metrics(node_metrics, start_ts)

        # Should have 1 valid gate, malformed one skipped
        assert len(stage_metrics.gates) == 1
        assert stage_metrics.gates[0].name == "ruff"

    def test_convert_with_non_dict_gate_item(self, pipeline_runner):
        """Test converting metrics when a gate item is not a dict."""
        node_metrics = NodeMetrics(
            node_id="verify",
            node_type="gate",
            duration_ms=3000,
            success=True,
            extra={
                "gates": [
                    {
                        "name": "ruff",
                        "exit_code": 0,
                        "duration_ms": 500,
                        "passed": True,
                    },
                    "not_a_dict",  # Invalid item
                ]
            },
        )
        start_ts = datetime.now(tz=UTC)

        stage_metrics = pipeline_runner._convert_node_metrics(node_metrics, start_ts)

        # Should have 1 valid gate, invalid one skipped
        assert len(stage_metrics.gates) == 1
        assert stage_metrics.gates[0].name == "ruff"

    def test_convert_with_empty_gates_list(self, pipeline_runner):
        """Test converting metrics with empty gates list."""
        node_metrics = NodeMetrics(
            node_id="verify",
            node_type="gate",
            duration_ms=3000,
            success=True,
            extra={"gates": []},
        )
        start_ts = datetime.now(tz=UTC)

        stage_metrics = pipeline_runner._convert_node_metrics(node_metrics, start_ts)

        assert len(stage_metrics.gates) == 0

    def test_convert_with_malformed_tokens_missing_total(self, pipeline_runner):
        """Test converting metrics with token data missing total field."""
        node_metrics = NodeMetrics(
            node_id="implement",
            node_type="llm_apply",
            duration_ms=5000,
            success=True,
            extra={
                "tokens": {
                    "input": 1000,
                    "output": 500,
                    # Missing "total" field - Pydantic should use default
                }
            },
        )
        start_ts = datetime.now(tz=UTC)

        stage_metrics = pipeline_runner._convert_node_metrics(node_metrics, start_ts)

        # Pydantic should use default value of 0 for total
        assert stage_metrics.tokens is not None
        assert stage_metrics.tokens.input == 1000
        assert stage_metrics.tokens.output == 500
        assert stage_metrics.tokens.total == 0

    def test_convert_with_both_malformed_tokens_and_gates(self, pipeline_runner):
        """Test converting metrics with both malformed tokens and gates."""
        node_metrics = NodeMetrics(
            node_id="verify",
            node_type="gate",
            duration_ms=3000,
            success=True,
            extra={
                "tokens": "invalid",
                "gates": ["also_invalid"],
            },
        )
        start_ts = datetime.now(tz=UTC)

        stage_metrics = pipeline_runner._convert_node_metrics(node_metrics, start_ts)

        # Both should be gracefully handled
        assert stage_metrics.tokens is None
        assert len(stage_metrics.gates) == 0
        assert stage_metrics.status == StageStatus.SUCCESS


# ============================================================================
# Failed Nodes Metrics Tests
# ============================================================================


class TestFailedNodesMetrics:
    """Tests for metrics being written for failed nodes."""

    @patch("orx.pipeline.runner.PipelineRunner._execute_node")
    def test_metrics_written_for_failed_node(self, mock_execute, pipeline_runner, temp_paths):
        """Test that metrics are written even when a node fails."""
        from orx.pipeline.definition import PipelineDefinition
        from orx.pipeline.executors.base import NodeResult

        node = NodeDefinition(id="plan", type=NodeType.LLM_TEXT)
        pipeline = PipelineDefinition(id="test", name="Test", nodes=[node])

        # Mock executor to fail
        mock_execute.return_value = NodeResult(
            success=False,
            error="Simulated failure",
            outputs={},
            metrics={},
        )

        # Run pipeline (should fail)
        result = pipeline_runner.run(pipeline, "Test task")
        assert result.success is False

        # Check that failure metrics were still written
        writer = MetricsWriter(temp_paths)
        stage_metrics_list = writer.read_stages()

        assert len(stage_metrics_list) == 1
        stage_metrics = stage_metrics_list[0]
        assert stage_metrics.status == StageStatus.FAIL
        assert stage_metrics.failure_message == "Simulated failure"

    @patch("orx.pipeline.runner.PipelineRunner._execute_node")
    def test_metrics_written_for_failed_node_with_extra_data(self, mock_execute, pipeline_runner, temp_paths):
        """Test that metrics including extra data are written for failed nodes."""
        from orx.pipeline.definition import PipelineDefinition
        from orx.pipeline.executors.base import NodeResult

        node = NodeDefinition(id="implement", type=NodeType.LLM_APPLY)
        pipeline = PipelineDefinition(id="test", name="Test", nodes=[node])

        # Mock executor to fail but with metrics data
        mock_execute.return_value = NodeResult(
            success=False,
            error="Gate failure",
            outputs={},
            metrics={
                "tokens": {
                    "input": 2000,
                    "output": 1000,
                    "total": 3000,
                },
                "gates": [
                    {
                        "name": "pytest",
                        "exit_code": 1,
                        "duration_ms": 5000,
                        "passed": False,
                        "tests_failed": 3,
                        "tests_total": 10,
                    }
                ],
            },
        )

        # Run pipeline (should fail)
        result = pipeline_runner.run(pipeline, "Test task")
        assert result.success is False

        # Check that all metrics were written despite failure
        writer = MetricsWriter(temp_paths)
        stage_metrics_list = writer.read_stages()

        assert len(stage_metrics_list) == 1
        stage_metrics = stage_metrics_list[0]
        assert stage_metrics.status == StageStatus.FAIL
        assert stage_metrics.failure_message == "Gate failure"

        # Extra data should be preserved
        assert stage_metrics.tokens is not None
        assert stage_metrics.tokens.total == 3000
        assert len(stage_metrics.gates) == 1
        assert stage_metrics.gates[0].name == "pytest"
        assert stage_metrics.gates[0].passed is False

    @patch("orx.pipeline.runner.PipelineRunner._execute_node")
    def test_metrics_written_for_multiple_failures(self, mock_execute, pipeline_runner, temp_paths):
        """Test that metrics are written for multiple node failures."""
        from orx.pipeline.definition import PipelineDefinition
        from orx.pipeline.executors.base import NodeResult

        nodes = [
            NodeDefinition(id="plan", type=NodeType.LLM_TEXT),
            NodeDefinition(id="implement", type=NodeType.LLM_APPLY),
        ]
        pipeline = PipelineDefinition(id="test", name="Test", nodes=nodes)

        # First succeeds, second fails
        execute_results = [
            NodeResult(success=True, outputs={"plan": "test"}, metrics={}),
            NodeResult(success=False, error="Second node failed", outputs={}, metrics={}),
        ]
        mock_execute.side_effect = execute_results

        # Run pipeline (should fail on second node)
        result = pipeline_runner.run(pipeline, "Test task")
        assert result.success is False
        assert result.failed_node == "implement"

        # Check that metrics for both nodes were written
        writer = MetricsWriter(temp_paths)
        stage_metrics_list = writer.read_stages()

        assert len(stage_metrics_list) == 2

        # First node should be success
        assert stage_metrics_list[0].stage == "plan"
        assert stage_metrics_list[0].status == StageStatus.SUCCESS

        # Second node should be failure
        assert stage_metrics_list[1].stage == "implement"
        assert stage_metrics_list[1].status == StageStatus.FAIL
