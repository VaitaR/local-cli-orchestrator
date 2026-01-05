"""Unit tests for fast verify helpers."""

from __future__ import annotations

from pathlib import Path

from orx.config import EngineType, OrxConfig
from orx.context.backlog import WorkItem
from orx.runner import Runner


def test_collect_pytest_targets_from_files_hint(
    tmp_path: Path, tmp_git_repo: Path
) -> None:
    worktree = tmp_path / "worktree"
    (worktree / "tests").mkdir(parents=True)
    (worktree / "tests" / "test_widget.py").write_text("def test_ok():\n    assert True\n")

    item = WorkItem(
        id="W001",
        title="Add widget",
        objective="Implement widget",
        acceptance=["Widget works"],
        files_hint=["src/widget.py"],
    )

    config = OrxConfig.default(EngineType.FAKE)
    runner = Runner(config, base_dir=tmp_git_repo, dry_run=True)

    targets = runner._collect_pytest_targets(item, worktree)
    assert "tests/test_widget.py" in targets


def test_collect_pytest_targets_skips_missing_tests(
    tmp_path: Path, tmp_git_repo: Path
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    item = WorkItem(
        id="W001",
        title="Add widget",
        objective="Implement widget",
        acceptance=["Widget works"],
        files_hint=["tests/test_missing.py"],
    )

    config = OrxConfig.default(EngineType.FAKE)
    runner = Runner(config, base_dir=tmp_git_repo, dry_run=True)

    targets = runner._collect_pytest_targets(item, worktree)
    assert targets == []


def test_collect_pytest_targets_skips_deleted_changed_files(
    tmp_path: Path, tmp_git_repo: Path
) -> None:
    worktree = tmp_path / "worktree"
    (worktree / "tests").mkdir(parents=True)
    (worktree / "tests" / "test_present.py").write_text(
        "def test_ok():\n    assert True\n"
    )

    item = WorkItem(
        id="W001",
        title="Add widget",
        objective="Implement widget",
        acceptance=["Widget works"],
        files_hint=["src/widget.py"],
    )

    config = OrxConfig.default(EngineType.FAKE)
    runner = Runner(config, base_dir=tmp_git_repo, dry_run=True)

    class StubWorkspace:
        def __init__(self, changed: list[str]) -> None:
            self._changed = changed

        def get_changed_files(self) -> list[str]:
            return self._changed

    runner.workspace = StubWorkspace(
        ["tests/test_missing.py", "tests/test_present.py"]
    )

    targets = runner._collect_pytest_targets(item, worktree)
    assert targets == ["tests/test_present.py"]
