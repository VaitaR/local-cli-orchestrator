"""Unit tests for pipeline executors."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orx.pipeline.definition import NodeConfig, NodeDefinition, NodeType
from orx.pipeline.executors.base import ExecutionContext, NodeResult

# ============================================================================
# NodeResult Tests
# ============================================================================


class TestNodeResult:
    """Tests for NodeResult dataclass."""

    def test_success_result(self):
        """Test successful result."""
        result = NodeResult(success=True)
        assert result.success
        assert bool(result) is True
        assert result.error is None
        assert result.outputs == {}

    def test_failure_result(self):
        """Test failure result."""
        result = NodeResult(success=False, error="Something went wrong")
        assert not result.success
        assert bool(result) is False
        assert result.error == "Something went wrong"

    def test_result_with_outputs(self):
        """Test result with outputs."""
        result = NodeResult(
            success=True,
            outputs={"plan": "My plan content"},
        )
        assert result.outputs["plan"] == "My plan content"

    def test_result_with_metrics(self):
        """Test result with metrics."""
        result = NodeResult(
            success=True,
            metrics={"duration_ms": 1500, "gates": []},
        )
        assert result.metrics["duration_ms"] == 1500


# ============================================================================
# Gate Executor Tests
# ============================================================================


class TestGateNodeExecutor:
    """Tests for GateNodeExecutor."""

    @pytest.fixture
    def temp_paths(self):
        """Create temporary run paths."""
        from orx.paths import RunPaths

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = RunPaths.create_new(Path(tmpdir))
            yield paths

    @pytest.fixture
    def mock_exec_ctx(self, temp_paths):
        """Create mock execution context."""
        from orx.gates.base import GateResult

        # Mock gate
        mock_gate = MagicMock()
        mock_gate.name = "ruff"
        mock_gate.run.return_value = GateResult(
            ok=True,
            returncode=0,
            log_path=temp_paths.logs_dir / "ruff.log",
            message="OK",
        )

        # Create log file
        (temp_paths.logs_dir / "ruff.log").write_text("Ruff passed")

        # Mock workspace
        mock_workspace = MagicMock()
        mock_workspace.worktree_path = temp_paths.run_dir

        return ExecutionContext(
            config=MagicMock(),
            paths=temp_paths,
            store=MagicMock(),
            workspace=mock_workspace,
            executor=MagicMock(),
            gates=[mock_gate],
            renderer=MagicMock(),
        )

    def test_gate_passes(self, mock_exec_ctx):
        """Test gate node when gate passes."""
        from orx.pipeline.executors.gate import GateNodeExecutor

        executor = GateNodeExecutor()
        node = NodeDefinition(
            id="verify",
            type=NodeType.GATE,
            config=NodeConfig(gates=["ruff"]),
        )

        result = executor.execute(node, {}, mock_exec_ctx)
        assert result.success

    def test_gate_fails(self, mock_exec_ctx, temp_paths):
        """Test gate node when gate fails."""
        from orx.gates.base import GateResult
        from orx.pipeline.executors.gate import GateNodeExecutor

        # Make gate fail
        mock_exec_ctx.gates[0].run.return_value = GateResult(
            ok=False,
            returncode=1,
            log_path=temp_paths.logs_dir / "ruff.log",
            message="Lint errors found",
        )

        executor = GateNodeExecutor()
        node = NodeDefinition(
            id="verify",
            type=NodeType.GATE,
            config=NodeConfig(gates=["ruff"]),
        )

        result = executor.execute(node, {}, mock_exec_ctx)
        assert not result.success
        assert "ruff" in result.error

    def test_no_gates_configured(self, mock_exec_ctx):
        """Test gate node with no gates configured."""
        from orx.pipeline.executors.gate import GateNodeExecutor

        executor = GateNodeExecutor()
        node = NodeDefinition(
            id="verify",
            type=NodeType.GATE,
            config=NodeConfig(gates=[]),
        )

        result = executor.execute(node, {}, mock_exec_ctx)
        assert result.success


# ============================================================================
# Custom Executor Tests
# ============================================================================


class TestCustomNodeExecutor:
    """Tests for CustomNodeExecutor."""

    @pytest.fixture
    def mock_exec_ctx(self):
        """Create mock execution context."""
        from orx.paths import RunPaths

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = RunPaths.create_new(Path(tmpdir))

            mock_workspace = MagicMock()
            mock_workspace.worktree_path = paths.run_dir
            mock_workspace.diff_empty.return_value = True

            yield ExecutionContext(
                config=MagicMock(),
                paths=paths,
                store=MagicMock(),
                workspace=mock_workspace,
                executor=MagicMock(),
                gates=[],
                renderer=MagicMock(),
            )

    def test_no_callable_path(self, mock_exec_ctx):
        """Test custom node without callable path or builtin handler."""
        from orx.pipeline.executors.custom import CustomNodeExecutor

        executor = CustomNodeExecutor()
        node = NodeDefinition(
            id="unknown_custom",
            type=NodeType.CUSTOM,
        )

        result = executor.execute(node, {}, mock_exec_ctx)
        assert not result.success
        assert "callable_path" in result.error

    def test_ship_builtin_handler(self, mock_exec_ctx):
        """Test ship builtin handler."""
        from orx.pipeline.executors.custom import CustomNodeExecutor

        # Configure mock
        mock_exec_ctx.config.git = MagicMock()
        mock_exec_ctx.config.git.auto_commit = False
        mock_exec_ctx.config.git.auto_push = False

        executor = CustomNodeExecutor()
        node = NodeDefinition(
            id="ship",
            type=NodeType.CUSTOM,
        )

        result = executor.execute(node, {}, mock_exec_ctx)
        # Ship succeeds even with empty diff
        assert result.success
        assert "pr_body" in result.outputs


# ============================================================================
# Integration-style Tests
# ============================================================================


class TestNodeExecutorRegistry:
    """Tests to verify all node types have executors."""

    def test_all_node_types_have_executors(self):
        """Test that all node types can be executed."""
        from orx.pipeline.executors import (
            CustomNodeExecutor,
            GateNodeExecutor,
            LLMApplyNodeExecutor,
            LLMTextNodeExecutor,
            MapNodeExecutor,
        )

        executors = {
            NodeType.LLM_TEXT: LLMTextNodeExecutor,
            NodeType.LLM_APPLY: LLMApplyNodeExecutor,
            NodeType.MAP: MapNodeExecutor,
            NodeType.GATE: GateNodeExecutor,
            NodeType.CUSTOM: CustomNodeExecutor,
        }

        for node_type in NodeType:
            assert node_type in executors, f"Missing executor for {node_type}"
            assert executors[node_type] is not None
