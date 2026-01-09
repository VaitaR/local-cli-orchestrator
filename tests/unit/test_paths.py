"""Tests for RunPaths."""

from pathlib import Path

import pytest

from orx.paths import RunPaths, generate_run_id


def test_generate_run_id() -> None:
    """Test run ID generation."""
    run_id = generate_run_id()

    # Should have timestamp prefix
    assert "_" in run_id
    parts = run_id.split("_")
    assert len(parts) == 3

    # Date part should be 8 chars (YYYYMMDD)
    assert len(parts[0]) == 8
    assert parts[0].isdigit()

    # Time part should be 6 chars (HHMMSS)
    assert len(parts[1]) == 6
    assert parts[1].isdigit()

    # UUID part should be 8 chars
    assert len(parts[2]) == 8


def test_run_paths_properties(tmp_path: Path) -> None:
    """Test RunPaths property accessors."""
    paths = RunPaths(base_dir=tmp_path, run_id="test_run")

    assert paths.run_dir == tmp_path / "runs" / "test_run"
    assert paths.context_dir == tmp_path / "runs" / "test_run" / "context"
    assert paths.prompts_dir == tmp_path / "runs" / "test_run" / "prompts"
    assert paths.artifacts_dir == tmp_path / "runs" / "test_run" / "artifacts"
    assert paths.logs_dir == tmp_path / "runs" / "test_run" / "logs"
    assert paths.metrics_dir == tmp_path / "runs" / "test_run" / "metrics"
    assert paths.worktree_path == tmp_path / ".worktrees" / "test_run"


def test_run_paths_context_files(tmp_path: Path) -> None:
    """Test context file paths."""
    paths = RunPaths(base_dir=tmp_path, run_id="test_run")

    assert paths.task_md == paths.context_dir / "task.md"
    assert paths.plan_md == paths.context_dir / "plan.md"
    assert paths.spec_md == paths.context_dir / "spec.md"
    assert paths.backlog_yaml == paths.context_dir / "backlog.yaml"


def test_run_paths_artifact_files(tmp_path: Path) -> None:
    """Test artifact file paths."""
    paths = RunPaths(base_dir=tmp_path, run_id="test_run")

    assert paths.patch_diff == paths.artifacts_dir / "patch.diff"
    assert paths.review_md == paths.artifacts_dir / "review.md"
    assert paths.pr_body_md == paths.artifacts_dir / "pr_body.md"


def test_run_paths_state_files(tmp_path: Path) -> None:
    """Test state file paths."""
    paths = RunPaths(base_dir=tmp_path, run_id="test_run")

    assert paths.meta_json == paths.run_dir / "meta.json"
    assert paths.state_json == paths.run_dir / "state.json"
    assert paths.events_jsonl == paths.run_dir / "events.jsonl"


def test_prompt_path(tmp_path: Path) -> None:
    """Test prompt path generation."""
    paths = RunPaths(base_dir=tmp_path, run_id="test_run")

    assert paths.prompt_path("plan") == paths.prompts_dir / "plan.md"
    assert paths.prompt_path("implement") == paths.prompts_dir / "implement.md"


def test_log_path(tmp_path: Path) -> None:
    """Test log path generation."""
    paths = RunPaths(base_dir=tmp_path, run_id="test_run")

    assert paths.log_path("ruff") == paths.logs_dir / "ruff.log"
    assert paths.log_path("pytest") == paths.logs_dir / "pytest.log"
    assert paths.log_path("custom", ".txt") == paths.logs_dir / "custom.txt"


def test_agent_log_paths(tmp_path: Path) -> None:
    """Test agent log path generation."""
    paths = RunPaths(base_dir=tmp_path, run_id="test_run")

    # Basic stage
    stdout, stderr = paths.agent_log_paths("plan")
    assert stdout == paths.logs_dir / "agent_plan.stdout.log"
    assert stderr == paths.logs_dir / "agent_plan.stderr.log"

    # With item ID
    stdout, stderr = paths.agent_log_paths("implement", item_id="W001")
    assert stdout == paths.logs_dir / "agent_implement_item_W001.stdout.log"
    assert stderr == paths.logs_dir / "agent_implement_item_W001.stderr.log"

    # With iteration
    stdout, stderr = paths.agent_log_paths("implement", item_id="W001", iteration=2)
    assert stdout == paths.logs_dir / "agent_implement_item_W001_iter_2.stdout.log"
    assert stderr == paths.logs_dir / "agent_implement_item_W001_iter_2.stderr.log"


def test_create_directories(tmp_path: Path) -> None:
    """Test directory creation."""
    paths = RunPaths(base_dir=tmp_path, run_id="test_run")

    # Directories shouldn't exist yet
    assert not paths.run_dir.exists()

    # Create them
    paths.create_directories()

    # Now they should exist
    assert paths.run_dir.exists()
    assert paths.context_dir.exists()
    assert paths.prompts_dir.exists()
    assert paths.artifacts_dir.exists()
    assert paths.logs_dir.exists()
    assert paths.metrics_dir.exists()
    assert paths.worktrees_dir.exists()


def test_create_directories_idempotent(tmp_path: Path) -> None:
    """Test that create_directories is idempotent."""
    paths = RunPaths(base_dir=tmp_path, run_id="test_run")

    paths.create_directories()
    paths.create_directories()  # Should not raise

    assert paths.validate()


def test_validate(tmp_path: Path) -> None:
    """Test directory validation."""
    paths = RunPaths(base_dir=tmp_path, run_id="test_run")

    # Should fail before creation
    assert not paths.validate()

    # Should pass after creation
    paths.create_directories()
    assert paths.validate()


def test_create_new(tmp_path: Path) -> None:
    """Test create_new factory method."""
    paths = RunPaths.create_new(tmp_path)

    assert paths.run_id is not None
    assert len(paths.run_id) > 0
    assert paths.validate()


def test_create_new_with_id(tmp_path: Path) -> None:
    """Test create_new with explicit run ID."""
    paths = RunPaths.create_new(tmp_path, run_id="my_custom_id")

    assert paths.run_id == "my_custom_id"
    assert paths.validate()


def test_from_existing(tmp_path: Path) -> None:
    """Test from_existing factory method."""
    # Create a run first
    original = RunPaths.create_new(tmp_path, run_id="existing_run")

    # Load it
    loaded = RunPaths.from_existing(tmp_path, "existing_run")

    assert loaded.run_id == "existing_run"
    assert loaded.run_dir == original.run_dir


def test_from_existing_not_found(tmp_path: Path) -> None:
    """Test from_existing with missing run."""
    with pytest.raises(ValueError, match="does not exist"):
        RunPaths.from_existing(tmp_path, "nonexistent")


def test_from_existing_incomplete(tmp_path: Path) -> None:
    """Test from_existing with incomplete directory."""
    # Create only the run dir, not subdirectories
    run_dir = tmp_path / "runs" / "incomplete_run"
    run_dir.mkdir(parents=True)

    with pytest.raises(ValueError, match="incomplete"):
        RunPaths.from_existing(tmp_path, "incomplete_run")


def test_worktree_prompt_paths(tmp_path: Path) -> None:
    """Test worktree prompt path helpers."""
    paths = RunPaths(base_dir=tmp_path, run_id="test_run")

    # worktree_prompt_dir should be inside worktree
    assert paths.worktree_prompt_dir() == paths.worktree_path / ".orx-prompts"

    # worktree_prompt_path should be inside worktree_prompt_dir
    assert (
        paths.worktree_prompt_path("plan")
        == paths.worktree_path / ".orx-prompts" / "plan.md"
    )


def test_copy_prompt_to_worktree(tmp_path: Path) -> None:
    """Test copying prompt to worktree for sandboxed executors."""
    paths = RunPaths.create_new(tmp_path, run_id="test_copy")

    # Create worktree directory (normally done by git_worktree)
    paths.worktree_path.mkdir(parents=True, exist_ok=True)

    # Create a prompt file in prompts_dir
    prompt_content = "# Test Prompt\n\nThis is a test."
    paths.prompt_path("test_stage").parent.mkdir(parents=True, exist_ok=True)
    paths.prompt_path("test_stage").write_text(prompt_content)

    # Copy to worktree
    copied_path = paths.copy_prompt_to_worktree("test_stage")

    # Verify
    assert copied_path.exists()
    assert copied_path == paths.worktree_prompt_path("test_stage")
    assert copied_path.read_text() == prompt_content

    # Original should still exist
    assert paths.prompt_path("test_stage").exists()
