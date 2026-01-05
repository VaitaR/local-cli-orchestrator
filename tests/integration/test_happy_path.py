"""Integration test: Happy path scenario.

Scenario A from design doc:
- Task: "Add function add(a,b) + tests"
- FakeExecutor implements and produces passing code
- Expect: patch.diff not empty, gates pass, review produced, state ends at DONE
"""

from pathlib import Path

import pytest

from orx.metrics.writer import MetricsWriter
from orx.config import EngineType, OrxConfig
from orx.executors.fake import FakeAction, FakeExecutor, FakeScenario
from orx.runner import Runner
from orx.state import Stage


@pytest.fixture
def happy_path_executor() -> FakeExecutor:
    """Create executor with happy path scenarios."""
    scenarios = [
        FakeScenario(
            name="plan",
            text_output="""# Plan

## Overview
Implement add function with tests.

## Steps
1. Create add function in src/app.py
2. Add tests in tests/test_app.py

## Risks
None
""",
        ),
        FakeScenario(
            name="spec",
            text_output="""# Specification

## Acceptance Criteria
- add(a, b) returns a + b
- Function has type hints
- Tests cover basic cases

## Constraints
- Python 3.11+
- Use pytest
""",
        ),
        FakeScenario(
            name="decompose",
            text_output="""run_id: "test_run"
items:
  - id: "W001"
    title: "Implement add function"
    objective: "Create add function with type hints"
    acceptance:
      - "Function exists"
      - "Returns correct sum"
    files_hint:
      - "src/app.py"
      - "tests/test_app.py"
    depends_on: []
    status: "todo"
    attempts: 0
    notes: ""
""",
        ),
        FakeScenario(
            name="implement",
            actions=[
                FakeAction(
                    "src/app.py",
                    '''"""App module."""


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
''',
                ),
                FakeAction(
                    "tests/test_app.py",
                    '''"""Tests for app."""

import sys
sys.path.insert(0, "src")
from app import add


def test_add() -> None:
    """Test add function."""
    assert add(1, 2) == 3
    assert add(0, 0) == 0
''',
                ),
            ],
        ),
        FakeScenario(
            name="review",
            text_output="""# Code Review

## Summary
Implementation complete and correct.

## Verdict
APPROVED

### pr_body.md

## Summary
Added add function with tests.

## Changes
- Added add function to src/app.py
- Added tests to tests/test_app.py
""",
        ),
    ]
    return FakeExecutor(scenarios=scenarios)


@pytest.mark.integration
def test_happy_path(
    tmp_git_repo: Path,
    happy_path_executor: FakeExecutor,
) -> None:
    """Test happy path execution."""
    # Setup config
    config = OrxConfig.default(EngineType.FAKE)
    config.git.base_branch = "main"
    config.git.auto_commit = False  # Don't commit in test
    config.git.auto_push = False

    # Create runner with fake executor
    runner = Runner(config, base_dir=tmp_git_repo, dry_run=False)
    runner.executor = happy_path_executor

    # Run
    success = runner.run("Add function add(a,b) that returns the sum of two integers")

    # Assertions
    assert success, "Run should succeed"

    # Check state
    assert runner.state.current_stage == Stage.DONE

    # Check artifacts exist
    assert runner.paths.task_md.exists()
    assert runner.paths.plan_md.exists()
    assert runner.paths.spec_md.exists()
    assert runner.paths.backlog_yaml.exists()
    assert runner.paths.patch_diff.exists()
    assert runner.paths.review_md.exists()

    # Check patch.diff is not empty
    diff_content = runner.paths.patch_diff.read_text()
    assert len(diff_content) > 0, "patch.diff should not be empty"

    # Check logs exist
    assert runner.paths.logs_dir.exists()
    log_files = list(runner.paths.logs_dir.glob("*.log"))
    assert len(log_files) > 0, "Should have log files"

    # Check meta.json
    assert runner.paths.meta_json.exists()

    # Check events timeline exists
    assert runner.paths.events_jsonl.exists()
    events = runner.paths.events_jsonl.read_text().splitlines()
    assert any('"event": "run_start"' in line for line in events)

    # Check metrics include implement attempts (regression for nested stage timer bug)
    metrics_writer = MetricsWriter(runner.paths)
    stage_metrics = metrics_writer.read_stages()
    stages = [m.stage for m in stage_metrics]
    assert "implement" in stages
    assert "verify" in stages


@pytest.mark.integration
def test_happy_path_artifacts_content(
    tmp_git_repo: Path,
    happy_path_executor: FakeExecutor,
) -> None:
    """Test that artifacts have expected content."""
    config = OrxConfig.default(EngineType.FAKE)
    config.git.base_branch = "main"
    config.git.auto_commit = False

    runner = Runner(config, base_dir=tmp_git_repo, dry_run=False)
    runner.executor = happy_path_executor

    success = runner.run("Add function add(a,b)")
    assert success

    # Check task was saved
    task_content = runner.pack.read_task()
    assert task_content is not None
    assert "add" in task_content.lower()

    # Check plan was generated
    plan_content = runner.pack.read_plan()
    assert plan_content is not None
    assert "Plan" in plan_content or "plan" in plan_content

    # Check spec was generated
    spec_content = runner.pack.read_spec()
    assert spec_content is not None
    assert "Specification" in spec_content or "Criteria" in spec_content

    # Check review was generated
    review_content = runner.pack.read_review()
    assert review_content is not None


@pytest.mark.integration
def test_happy_path_state_transitions(
    tmp_git_repo: Path,
    happy_path_executor: FakeExecutor,
) -> None:
    """Test that state transitions are tracked correctly."""
    config = OrxConfig.default(EngineType.FAKE)
    config.git.base_branch = "main"
    config.git.auto_commit = False

    runner = Runner(config, base_dir=tmp_git_repo, dry_run=False)
    runner.executor = happy_path_executor

    success = runner.run("Add function")
    assert success

    # Reload state
    runner.state.load()

    # Check stage statuses were tracked
    statuses = runner.state.state.stage_statuses
    assert len(statuses) > 0

    # All executed stages should be completed
    for stage_key, status in statuses.items():
        if stage_key != "done":  # DONE is terminal
            assert status.status in (
                "completed",
                "running",
            ), f"Stage {stage_key} has unexpected status: {status.status}"
