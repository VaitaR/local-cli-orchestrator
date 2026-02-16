"""Tests for Human-in-the-loop (interactive pause) feature."""

from __future__ import annotations

from orx.dashboard.store.models import RunStatus, RunSummary
from orx.paths import RunPaths
from orx.pipeline.definition import NodeDefinition, NodeType, PipelineDefinition
from orx.state import RunState, Stage, StateManager

# ---------------------------------------------------------------------------
# State: PAUSED enum and StateManager helpers
# ---------------------------------------------------------------------------


class TestPausedStage:
    """Test the PAUSED stage in the FSM."""

    def test_paused_stage_exists(self) -> None:
        """PAUSED should be a valid Stage value."""
        assert Stage.PAUSED == "paused"
        assert Stage("paused") is Stage.PAUSED

    def test_paused_stage_serialization(self) -> None:
        """PAUSED stage should round-trip through dict serialization."""
        state = RunState(run_id="test")
        state.current_stage = Stage.PAUSED
        state.paused_after_node = "plan"

        data = state.to_dict()
        assert data["current_stage"] == "paused"
        assert data["paused_after_node"] == "plan"

        restored = RunState.from_dict(data)
        assert restored.current_stage == Stage.PAUSED
        assert restored.paused_after_node == "plan"


class TestStateManagerPause:
    """Test pause/resume helpers on StateManager."""

    def test_mark_paused(self, run_paths: RunPaths) -> None:
        """mark_paused should set stage to PAUSED and record node id."""
        mgr = StateManager(run_paths)
        mgr.initialize()
        mgr.transition_to(Stage.PLAN)
        mgr.mark_stage_completed(Stage.PLAN)

        mgr.mark_paused(after_node="plan")

        assert mgr.current_stage == Stage.PAUSED
        assert mgr.state.paused_after_node == "plan"
        assert mgr.state.pid is None  # PID cleared on pause

    def test_mark_paused_persists(self, run_paths: RunPaths) -> None:
        """mark_paused should persist to disk."""
        mgr = StateManager(run_paths)
        mgr.initialize()
        mgr.mark_paused(after_node="spec")

        mgr2 = StateManager(run_paths)
        mgr2.load()

        assert mgr2.current_stage == Stage.PAUSED
        assert mgr2.state.paused_after_node == "spec"

    def test_is_paused(self, run_paths: RunPaths) -> None:
        """is_paused should return True only when PAUSED."""
        mgr = StateManager(run_paths)
        mgr.initialize()

        assert not mgr.is_paused()

        mgr.mark_paused(after_node="plan")
        assert mgr.is_paused()

    def test_paused_is_resumable(self, run_paths: RunPaths) -> None:
        """A paused run should be resumable."""
        mgr = StateManager(run_paths)
        mgr.initialize()
        mgr.mark_paused(after_node="plan")

        assert mgr.is_resumable()

    def test_done_not_resumable(self, run_paths: RunPaths) -> None:
        """DONE state should not be resumable."""
        mgr = StateManager(run_paths)
        mgr.initialize()
        mgr.transition_to(Stage.DONE)

        assert not mgr.is_resumable()

    def test_failed_not_resumable(self, run_paths: RunPaths) -> None:
        """FAILED state should not be resumable."""
        mgr = StateManager(run_paths)
        mgr.initialize()
        mgr.transition_to(Stage.FAILED)

        assert not mgr.is_resumable()


# ---------------------------------------------------------------------------
# Pipeline Definition: interactive flag
# ---------------------------------------------------------------------------


class TestNodeInteractiveFlag:
    """Test interactive flag on NodeDefinition."""

    def test_default_not_interactive(self) -> None:
        """Nodes should default to non-interactive."""
        node = NodeDefinition(
            id="plan",
            type=NodeType.LLM_TEXT,
            template="plan.md",
        )
        assert node.interactive is False

    def test_interactive_node(self) -> None:
        """Nodes can be marked as interactive."""
        node = NodeDefinition(
            id="plan",
            type=NodeType.LLM_TEXT,
            template="plan.md",
            interactive=True,
        )
        assert node.interactive is True

    def test_interactive_serialization(self) -> None:
        """Interactive flag should round-trip through dict."""
        node = NodeDefinition(
            id="plan",
            type=NodeType.LLM_TEXT,
            template="plan.md",
            interactive=True,
        )

        data = node.to_dict()
        assert data["interactive"] is True

        restored = NodeDefinition.model_validate(data)
        assert restored.interactive is True


# ---------------------------------------------------------------------------
# PipelineResult: paused field
# ---------------------------------------------------------------------------


class TestPipelineResultPaused:
    """Test paused field on PipelineResult."""

    def test_default_not_paused(self) -> None:
        from orx.pipeline.runner import PipelineResult

        result = PipelineResult(success=True)
        assert result.paused is False
        assert result.paused_after_node is None

    def test_paused_result(self) -> None:
        from orx.pipeline.runner import PipelineResult

        result = PipelineResult(
            success=True,
            paused=True,
            paused_after_node="plan",
            completed_nodes=["plan"],
        )
        assert result.paused is True
        assert result.paused_after_node == "plan"
        # A paused result is still considered truthy (not a failure)
        assert bool(result) is True


# ---------------------------------------------------------------------------
# Dashboard: RunStatus.PAUSED
# ---------------------------------------------------------------------------


class TestDashboardPausedStatus:
    """Test PAUSED status in dashboard models."""

    def test_paused_status_exists(self) -> None:
        """PAUSED should be a valid RunStatus."""
        assert RunStatus.PAUSED == "paused"

    def test_from_state_paused(self) -> None:
        """from_state should return PAUSED when stage is 'paused'."""
        status = RunStatus.from_state(state_status=None, stage="paused")
        assert status == RunStatus.PAUSED

    def test_from_state_running(self) -> None:
        """from_state should still return RUNNING for regular stages."""
        status = RunStatus.from_state(state_status="running", stage="plan")
        assert status == RunStatus.RUNNING

    def test_can_resume_when_paused(self) -> None:
        """RunSummary.can_resume should be True when paused."""
        run = RunSummary(run_id="test", status=RunStatus.PAUSED)
        assert run.can_resume is True
        assert run.is_paused is True

    def test_cannot_resume_when_running(self) -> None:
        """RunSummary.can_resume should be False when running."""
        run = RunSummary(run_id="test", status=RunStatus.RUNNING)
        assert run.can_resume is False

    def test_cannot_resume_when_done(self) -> None:
        """RunSummary.can_resume should be False when success."""
        run = RunSummary(run_id="test", status=RunStatus.SUCCESS)
        assert run.can_resume is False

    def test_is_active_when_paused(self) -> None:
        """Paused runs are NOT active (pipeline isn't executing)."""
        run = RunSummary(run_id="test", status=RunStatus.PAUSED)
        assert run.is_active is False


# ---------------------------------------------------------------------------
# Pipeline with interactive nodes (integration-like unit test)
# ---------------------------------------------------------------------------


class TestPipelineDefinitionInteractive:
    """Test pipeline with interactive nodes."""

    def test_interactive_pipeline(self) -> None:
        """Create a pipeline with interactive plan and spec nodes."""
        pipeline = PipelineDefinition(
            id="interactive_test",
            name="Interactive Test",
            nodes=[
                NodeDefinition(
                    id="plan",
                    type=NodeType.LLM_TEXT,
                    template="plan.md",
                    inputs=["task"],
                    outputs=["plan"],
                    interactive=True,
                ),
                NodeDefinition(
                    id="spec",
                    type=NodeType.LLM_TEXT,
                    template="spec.md",
                    inputs=["plan"],
                    outputs=["spec"],
                    interactive=True,
                ),
                NodeDefinition(
                    id="implement",
                    type=NodeType.LLM_APPLY,
                    template="implement.md",
                    inputs=["spec"],
                    outputs=["patch_diff"],
                ),
            ],
        )

        # Plan is interactive
        assert pipeline.nodes[0].interactive is True
        # Spec is interactive
        assert pipeline.nodes[1].interactive is True
        # Implement is not interactive
        assert pipeline.nodes[2].interactive is False

    def test_interactive_yaml_round_trip(self) -> None:
        """Interactive flag should survive YAML serialization."""
        pipeline = PipelineDefinition(
            id="test_yaml",
            name="YAML test",
            nodes=[
                NodeDefinition(
                    id="plan",
                    type=NodeType.LLM_TEXT,
                    template="plan.md",
                    interactive=True,
                ),
            ],
        )

        yaml_str = pipeline.to_yaml()
        assert "interactive: true" in yaml_str

        import yaml

        data = yaml.safe_load(yaml_str)
        restored = PipelineDefinition.model_validate(data)
        assert restored.nodes[0].interactive is True
