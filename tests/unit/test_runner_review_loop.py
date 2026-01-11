from unittest.mock import MagicMock, patch

import pytest

from orx.runner import Runner, Stage
from orx.stages.base import StageResult


class MockState:
    def __init__(self):
        self.current_stage = Stage.PLAN

    def transition_to(self, stage):
        self.current_stage = stage

    def mark_stage_completed(self, stage=None):
        pass

    def mark_stage_failed(self, msg):
        pass


class MockPaths:
    def __init__(self):
        self.run_id = "test_run"
        self.backlog_yaml = MagicMock()


@pytest.fixture
def mock_runner():
    with patch("orx.runner.Runner.__init__", return_value=None):
        runner = Runner(None, base_dir=None)
        runner.state = MockState()
        runner.paths = MockPaths()
        runner.events = MagicMock()
        runner.metrics = MagicMock()
        runner.config = MagicMock()
        # Mock methods
        runner._run_stage_with_metrics = MagicMock()
        runner._run_implement_loop = MagicMock(return_value=StageResult(success=True))
        runner._save_meta = MagicMock()
        runner._run_plan = MagicMock()
        runner._run_spec = MagicMock()
        runner._run_decompose = MagicMock()
        runner._run_review = MagicMock()
        runner._run_ship = MagicMock()
        runner._run_knowledge_update = MagicMock()

        # Mock Backlog loading
        runner._add_backlog_item_for_review = MagicMock()

        return runner


def test_runner_review_loop(mock_runner):
    # Setup - first pass review fails, second pass review passes

    # Mock stage execution results
    # Plan, Spec, Decompose, Implement, Review(Fail), Implement, Review(Pass), Ship, Knowledge

    # We need to control the side effects of _run_stage_with_metrics based on calls

    def side_effect(stage_name, _run_fn):
        if stage_name == "review":
            # Use a mutable counter on the mock to track review attempts
            if not hasattr(mock_runner, "review_attempts"):
                mock_runner.review_attempts = 0
            mock_runner.review_attempts += 1

            if mock_runner.review_attempts == 1:
                return StageResult(
                    success=True,
                    data={"verdict": "changes_requested", "feedback": "Fix typos"},
                )
            else:
                return StageResult(success=True, data={"verdict": "approved"})

        return StageResult(success=True)

    mock_runner._run_stage_with_metrics.side_effect = side_effect

    # Run
    mock_runner._execute_stages()

    # Assert
    assert mock_runner.review_attempts == 2
    mock_runner._add_backlog_item_for_review.assert_called_once_with("Fix typos")
    assert mock_runner._run_implement_loop.call_count == 2

    # Check that ship was called via _run_stage_with_metrics
    calls = [args[0] for args, _ in mock_runner._run_stage_with_metrics.call_args_list]
    assert "ship" in calls
    assert "knowledge_update" in calls
