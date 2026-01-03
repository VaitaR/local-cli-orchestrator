"""Integration test: Resume from checkpoint.

Scenario D from design doc:
- Run until after SPEC, then simulate crash
- Resume continues from DECOMPOSE
- Previous artifacts preserved, stages not re-run unnecessarily
"""

from pathlib import Path

import pytest

from orx.config import EngineType, OrxConfig
from orx.executors.fake import FakeExecutor, FakeScenario
from orx.paths import RunPaths
from orx.runner import Runner
from orx.state import Stage, StateManager


@pytest.fixture
def resume_test_executor() -> FakeExecutor:
    """Create executor for resume testing."""
    return FakeExecutor(
        scenarios=[
            FakeScenario(name="plan", text_output="# Plan\nResume test plan."),
            FakeScenario(
                name="spec", text_output="# Spec\n## Acceptance\n- Works after resume"
            ),
            FakeScenario(
                name="decompose",
                text_output="""run_id: "test"
items:
  - id: "W001"
    title: "Resume task"
    objective: "Test resume"
    acceptance: ["Works"]
    files_hint: []
    depends_on: []
    status: "todo"
    attempts: 0
    notes: ""
""",
            ),
            FakeScenario(name="implement", actions=[]),
            FakeScenario(name="review", text_output="# Review\nResumed and completed."),
        ]
    )


@pytest.mark.integration
def test_resume_preserves_artifacts(
    tmp_git_repo: Path,
    resume_test_executor: FakeExecutor,
) -> None:
    """Test that resume preserves existing artifacts."""
    config = OrxConfig.default(EngineType.FAKE)
    config.git.base_branch = "main"
    config.git.auto_commit = False

    # First run - create state and some artifacts
    runner1 = Runner(config, base_dir=tmp_git_repo, dry_run=False)
    runner1.executor = resume_test_executor

    # Initialize and run just plan stage
    runner1.state.initialize()
    runner1.pack.write_task("Resume test task")

    # Create workspace
    runner1.workspace.create("main")
    runner1.state.set_baseline_sha(runner1.workspace.baseline_sha())

    # Simulate running through PLAN
    runner1.state.transition_to(Stage.PLAN)
    runner1.pack.write_plan("# Simulated Plan\n\nThis was written before crash.")
    runner1.state.mark_stage_completed()

    # Simulate running through SPEC
    runner1.state.transition_to(Stage.SPEC)
    runner1.pack.write_spec("# Simulated Spec\n\nThis was written before crash.")
    runner1.state.mark_stage_completed()

    # "Crash" at DECOMPOSE
    runner1.state.transition_to(Stage.DECOMPOSE)

    run_id = runner1.paths.run_id

    # Verify pre-resume state
    assert runner1.paths.plan_md.exists()
    assert runner1.paths.spec_md.exists()
    original_plan = runner1.paths.plan_md.read_text()

    # Resume with new runner instance
    runner2 = Runner(config, base_dir=tmp_git_repo, run_id=run_id, dry_run=False)
    runner2.executor = resume_test_executor

    # Check that artifacts are still there
    assert runner2.paths.plan_md.exists()
    assert runner2.paths.spec_md.exists()

    # Plan content should be preserved
    resumed_plan = runner2.paths.plan_md.read_text()
    assert resumed_plan == original_plan


@pytest.mark.integration
def test_resume_continues_from_checkpoint(
    tmp_git_repo: Path,
    resume_test_executor: FakeExecutor,  # noqa: ARG001
) -> None:
    """Test that resume continues from the correct checkpoint."""
    config = OrxConfig.default(EngineType.FAKE)
    config.git.base_branch = "main"
    config.git.auto_commit = False

    # Setup initial state
    paths = RunPaths.create_new(tmp_git_repo, "resume_test")
    state_mgr = StateManager(paths)
    state_mgr.initialize()

    # Simulate completed stages
    state_mgr.transition_to(Stage.PLAN)
    state_mgr.mark_stage_completed()
    state_mgr.transition_to(Stage.SPEC)
    state_mgr.mark_stage_completed()
    state_mgr.transition_to(Stage.DECOMPOSE)
    # Left in DECOMPOSE (not completed)

    # Verify state
    loaded = state_mgr.load()
    assert loaded.current_stage == Stage.DECOMPOSE

    # Resume should start from DECOMPOSE
    resume_point = state_mgr.get_resume_point()
    assert resume_point == Stage.DECOMPOSE


@pytest.mark.integration
def test_resume_not_possible_when_done(
    tmp_git_repo: Path,
) -> None:
    """Test that completed runs cannot be resumed."""
    config = OrxConfig.default(EngineType.FAKE)
    config.git.base_branch = "main"

    # Setup completed state
    paths = RunPaths.create_new(tmp_git_repo, "done_test")
    state_mgr = StateManager(paths)
    state_mgr.initialize()
    state_mgr.transition_to(Stage.DONE)
    state_mgr.mark_stage_completed()

    # Check resumability
    assert not state_mgr.is_resumable()


@pytest.mark.integration
def test_resume_not_possible_when_failed(
    tmp_git_repo: Path,
) -> None:
    """Test that failed runs cannot be resumed."""
    config = OrxConfig.default(EngineType.FAKE)
    config.git.base_branch = "main"

    # Setup failed state
    paths = RunPaths.create_new(tmp_git_repo, "failed_test")
    state_mgr = StateManager(paths)
    state_mgr.initialize()
    state_mgr.transition_to(Stage.FAILED)

    # Check resumability
    assert not state_mgr.is_resumable()
