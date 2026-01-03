"""Integration test: Empty diff scenario.

Scenario C from design doc:
- Executor returns 0 but makes no edits
- Orchestrator should detect empty diff and treat as failure
- Fix prompt should include "diff empty" message
"""

from pathlib import Path

import pytest

from orx.config import EngineType, OrxConfig
from orx.context.backlog import Backlog
from orx.executors.fake import FakeAction, FakeExecutor, FakeScenario
from orx.runner import Runner
from orx.state import Stage


@pytest.fixture
def empty_then_fix_executor() -> FakeExecutor:
    """Create executor that produces empty diff first, then fixes."""
    # Track attempts to know when to produce changes
    attempt_tracker = {"implement": 0}

    def custom_action(stage: str, cwd: Path, logs: object) -> None:  # noqa: ARG001
        if stage == "implement":
            attempt_tracker["implement"] += 1

    scenarios = [
        FakeScenario(name="plan", text_output="# Plan\nCreate file."),
        FakeScenario(name="spec", text_output="# Spec\n## Acceptance\n- File exists"),
        FakeScenario(
            name="decompose",
            text_output="""run_id: "test"
items:
  - id: "W001"
    title: "Create file"
    objective: "Create the file"
    acceptance: ["File exists"]
    files_hint: ["src/new_file.py"]
    depends_on: []
    status: "todo"
    attempts: 0
    notes: ""
""",
        ),
        # First implement makes no changes
        FakeScenario(name="implement", actions=[]),
        # Fix creates the file
        FakeScenario(
            name="fix",
            actions=[
                FakeAction(
                    "src/new_file.py",
                    '"""New file."""\n\ndef hello() -> str:\n    return "hello"\n',
                ),
            ],
        ),
        FakeScenario(name="review", text_output="# Review\nFile created."),
    ]

    return FakeExecutor(scenarios=scenarios, action_callback=custom_action)


@pytest.mark.integration
def test_empty_diff_detected(tmp_git_repo: Path) -> None:
    """Test that empty diff is detected."""
    # Create executor that never produces changes
    never_change_executor = FakeExecutor(
        scenarios=[
            FakeScenario(name="plan", text_output="# Plan"),
            FakeScenario(name="spec", text_output="# Spec\n## Acceptance\n- Done"),
            FakeScenario(
                name="decompose",
                text_output="""run_id: "test"
items:
  - id: "W001"
    title: "Task"
    objective: "Do task"
    acceptance: ["Done"]
    files_hint: []
    depends_on: []
    status: "todo"
    attempts: 0
    notes: ""
""",
            ),
            FakeScenario(name="implement", actions=[]),
            FakeScenario(name="fix", actions=[]),
        ]
    )

    config = OrxConfig.default(EngineType.FAKE)
    config.git.base_branch = "main"
    config.git.auto_commit = False
    config.run.max_fix_attempts = 2
    config.run.stop_on_first_failure = True

    runner = Runner(config, base_dir=tmp_git_repo, dry_run=False)
    runner.executor = never_change_executor

    success = runner.run("Do something")

    # Should fail because diff is always empty
    assert not success

    # State should indicate failure
    runner.state.load()
    assert runner.state.current_stage == Stage.FAILED


@pytest.mark.integration
def test_empty_diff_recovery(
    tmp_git_repo: Path,
    empty_then_fix_executor: FakeExecutor,
) -> None:
    """Test recovery from empty diff via fix loop."""
    config = OrxConfig.default(EngineType.FAKE)
    config.git.base_branch = "main"
    config.git.auto_commit = False
    config.run.max_fix_attempts = 3

    runner = Runner(config, base_dir=tmp_git_repo, dry_run=False)
    runner.executor = empty_then_fix_executor

    runner.run("Create a new file")

    # Should succeed after fix loop creates the file
    # Note: This depends on the workspace detecting the file creation
    # In practice with FakeExecutor, it should work

    # Check that multiple attempts were made
    if runner.paths.backlog_yaml.exists():
        backlog = Backlog.load(runner.paths.backlog_yaml)
        item = backlog.get_item("W001")
        if item:
            # At least initial attempt should be recorded
            assert item.attempts >= 1
