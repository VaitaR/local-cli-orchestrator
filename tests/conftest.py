"""Pytest fixtures for orx tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest

from orx.config import EngineType, OrxConfig
from orx.context.backlog import Backlog, WorkItem
from orx.executors.fake import FakeExecutor, create_happy_path_scenarios
from orx.infra.command import CommandRunner
from orx.paths import RunPaths


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory."""
    project = tmp_path / "project"
    project.mkdir()
    return project


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository.

    Creates a basic git repo with:
    - Initial commit
    - main branch
    - Basic Python structure
    """
    repo = tmp_path / "repo"
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
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # Create basic structure
    src = repo / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")
    (repo / "pyproject.toml").write_text(
        """
[project]
name = "test-project"
version = "0.1.0"
"""
    )

    # Initial commit
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # Ensure we're on main branch
    subprocess.run(
        ["git", "branch", "-M", "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    return repo


@pytest.fixture
def run_paths(tmp_project: Path) -> RunPaths:
    """Create RunPaths for a test run."""
    return RunPaths.create_new(tmp_project, "test_run")


@pytest.fixture
def command_runner() -> CommandRunner:
    """Create a CommandRunner instance."""
    return CommandRunner()


@pytest.fixture
def dry_run_command_runner() -> CommandRunner:
    """Create a dry-run CommandRunner instance."""
    return CommandRunner(dry_run=True)


@pytest.fixture
def fake_executor() -> FakeExecutor:
    """Create a FakeExecutor with happy path scenarios."""
    scenarios = create_happy_path_scenarios()
    return FakeExecutor(scenarios=scenarios)


@pytest.fixture
def default_config() -> OrxConfig:
    """Create a default OrxConfig."""
    return OrxConfig.default(EngineType.FAKE)


@pytest.fixture
def sample_backlog() -> Backlog:
    """Create a sample backlog for testing."""
    backlog = Backlog(run_id="test_run", items=[])

    backlog.add_item(
        WorkItem(
            id="W001",
            title="Create main module",
            objective="Create the main application module",
            acceptance=["Module exists", "Has proper docstring"],
            files_hint=["src/app.py"],
            depends_on=[],
        )
    )

    backlog.add_item(
        WorkItem(
            id="W002",
            title="Add tests",
            objective="Create tests for the main module",
            acceptance=["Tests exist", "All tests pass"],
            files_hint=["tests/test_app.py"],
            depends_on=["W001"],
        )
    )

    return backlog


@pytest.fixture
def sample_work_item() -> WorkItem:
    """Create a sample work item."""
    return WorkItem(
        id="W001",
        title="Implement feature",
        objective="Implement the feature as specified",
        acceptance=["Feature works", "Tests pass"],
        files_hint=["src/feature.py"],
    )
