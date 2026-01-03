"""Integration test: Base branch override.

Scenario E from design doc:
- Repo has 'dev' as base
- Run with --base-branch dev
- Worktree created from dev, baseline SHA matches dev HEAD
"""

import subprocess
from pathlib import Path

import pytest

from orx.config import EngineType, OrxConfig
from orx.executors.fake import FakeExecutor, FakeScenario
from orx.runner import Runner


@pytest.fixture
def repo_with_dev_branch(tmp_path: Path) -> Path:
    """Create a git repo with a dev branch."""
    repo = tmp_path / "repo_dev"
    repo.mkdir()

    # Initialize git
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # Create initial structure on main
    src = repo / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")
    (repo / "README.md").write_text("# Main branch")

    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "branch", "-M", "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # Create dev branch with different content
    subprocess.run(
        ["git", "checkout", "-b", "dev"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("# Dev branch")
    (repo / "dev_only.txt").write_text("This file only exists on dev")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Dev changes"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # Go back to main
    subprocess.run(
        ["git", "checkout", "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    return repo


@pytest.fixture
def simple_executor() -> FakeExecutor:
    """Create a simple executor for branch testing."""
    return FakeExecutor(
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
            FakeScenario(name="review", text_output="# Review"),
        ]
    )


def get_branch_sha(repo: Path, branch: str) -> str:
    """Get the SHA of a branch."""
    result = subprocess.run(
        ["git", "rev-parse", branch],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.mark.integration
def test_base_branch_override(
    repo_with_dev_branch: Path,
    simple_executor: FakeExecutor,
) -> None:
    """Test that base branch override works."""
    # Get dev branch SHA
    dev_sha = get_branch_sha(repo_with_dev_branch, "dev")

    # Configure with dev as base branch
    config = OrxConfig.default(EngineType.FAKE)
    config.git.base_branch = "dev"
    config.git.auto_commit = False

    runner = Runner(config, base_dir=repo_with_dev_branch, dry_run=False)
    runner.executor = simple_executor

    # Initialize workspace
    runner.state.initialize()
    runner.pack.write_task("Test task")
    runner.workspace.create("dev")
    runner.state.set_baseline_sha(runner.workspace.baseline_sha())

    # Verify baseline SHA matches dev
    assert runner.state.state.baseline_sha == dev_sha

    # Verify worktree has dev content
    worktree = runner.workspace.worktree_path
    assert (worktree / "dev_only.txt").exists(), "Dev branch file should exist"

    readme_content = (worktree / "README.md").read_text()
    assert "Dev branch" in readme_content


@pytest.mark.integration
def test_main_branch_default(
    repo_with_dev_branch: Path,
    simple_executor: FakeExecutor,
) -> None:
    """Test that main is used by default."""
    # Get main branch SHA
    main_sha = get_branch_sha(repo_with_dev_branch, "main")

    # Use default config (main branch)
    config = OrxConfig.default(EngineType.FAKE)
    config.git.auto_commit = False

    runner = Runner(config, base_dir=repo_with_dev_branch, dry_run=False)
    runner.executor = simple_executor

    # Initialize workspace
    runner.state.initialize()
    runner.pack.write_task("Test task")
    runner.workspace.create("main")
    runner.state.set_baseline_sha(runner.workspace.baseline_sha())

    # Verify baseline SHA matches main
    assert runner.state.state.baseline_sha == main_sha

    # Verify worktree has main content
    worktree = runner.workspace.worktree_path
    assert not (worktree / "dev_only.txt").exists(), "Dev file should not exist"

    readme_content = (worktree / "README.md").read_text()
    assert "Main branch" in readme_content


@pytest.mark.integration
def test_invalid_base_branch(
    repo_with_dev_branch: Path,
    simple_executor: FakeExecutor,
) -> None:
    """Test error handling for invalid base branch."""
    config = OrxConfig.default(EngineType.FAKE)
    config.git.base_branch = "nonexistent_branch"
    config.git.auto_commit = False

    runner = Runner(config, base_dir=repo_with_dev_branch, dry_run=False)
    runner.executor = simple_executor

    # Should fail when trying to create workspace
    runner.state.initialize()
    runner.pack.write_task("Test task")

    from orx.exceptions import WorkspaceError

    with pytest.raises(WorkspaceError):
        runner.workspace.create("nonexistent_branch")
