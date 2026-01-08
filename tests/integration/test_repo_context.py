"""Integration tests for repo context pack."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest

from orx.config import EngineType, OrxConfig
from orx.context.pack import ContextPack
from orx.context.repo_context import RepoContextBuilder
from orx.paths import RunPaths
from orx.runner import Runner


@pytest.fixture
def python_project(tmp_path: Path) -> Path:
    """Create a minimal Python project structure."""
    project = tmp_path / "project"
    project.mkdir()

    # pyproject.toml with various tools
    pyproject = dedent("""
        [project]
        name = "test-project"
        version = "0.1.0"
        requires-python = ">=3.11"

        [tool.ruff]
        line-length = 100
        target-version = "py311"

        [tool.ruff.lint]
        select = ["E", "F", "I", "W"]

        [tool.mypy]
        strict = true

        [tool.pytest.ini_options]
        testpaths = ["tests"]
        addopts = "-q --tb=short"
    """)
    (project / "pyproject.toml").write_text(pyproject)

    # Source directory
    src = project / "src" / "mypackage"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("")
    (src / "main.py").write_text("def main(): pass\n")

    # Tests directory
    tests = project / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    (tests / "test_main.py").write_text("def test_main(): pass\n")

    return project


@pytest.fixture
def ts_project(tmp_path: Path) -> Path:
    """Create a minimal TypeScript project structure."""
    project = tmp_path / "project"
    project.mkdir()

    # package.json
    package = {
        "name": "test-project",
        "type": "module",
        "scripts": {
            "lint": "eslint .",
            "test": "vitest",
            "typecheck": "tsc --noEmit",
            "build": "tsc",
        },
        "devDependencies": {
            "typescript": "^5.0.0",
            "eslint": "^8.0.0",
        },
    }
    (project / "package.json").write_text(json.dumps(package, indent=2))

    # tsconfig.json
    tsconfig = {
        "compilerOptions": {
            "strict": True,
            "target": "ES2022",
            "module": "ESNext",
            "moduleResolution": "bundler",
        },
        "include": ["src/**/*"],
    }
    (project / "tsconfig.json").write_text(json.dumps(tsconfig, indent=2))
    (project / "pnpm-lock.yaml").write_text("")

    # Source
    src = project / "src"
    src.mkdir()
    (src / "index.ts").write_text("export const hello = () => 'Hello';\n")

    return project


class TestRepoContextIntegration:
    """Integration tests for repo context building."""

    def test_python_project_context(self, python_project: Path) -> None:
        """Test context extraction from Python project."""
        builder = RepoContextBuilder(python_project, gates=[])
        result = builder.build()

        assert "python" in result.detected_stacks
        assert result.project_map
        assert result.tooling_snapshot

        # Check profile contains stack info
        assert "Python" in result.project_map or "py" in result.project_map.lower()

        # Check tooling has ruff config
        assert "Ruff" in result.tooling_snapshot
        assert "line-length" in result.tooling_snapshot

        # Check mypy is detected
        assert (
            "Mypy" in result.tooling_snapshot
            or "mypy" in result.tooling_snapshot.lower()
        )

    def test_typescript_project_context(self, ts_project: Path) -> None:
        """Test context extraction from TypeScript project."""
        builder = RepoContextBuilder(ts_project, gates=[])
        result = builder.build()

        assert "typescript" in result.detected_stacks
        assert result.project_map

        # Check profile
        assert "pnpm" in result.project_map
        assert "module" in result.project_map

        # Check tooling has tsconfig
        assert "TypeScript" in result.tooling_snapshot
        assert "strict" in result.tooling_snapshot

    def test_context_with_gates(self, python_project: Path) -> None:
        """Test that gates are included in context."""

        class MockGate:
            def __init__(
                self, name: str, command: str, args: list[str], required: bool
            ):
                self._name = name
                self.command = command
                self.args = args
                self.required = required

            @property
            def name(self) -> str:
                return self._name

        gates = [
            MockGate("ruff", "ruff", ["check", "."], True),
            MockGate("pytest", "pytest", ["-q"], True),
        ]

        builder = RepoContextBuilder(python_project, gates)
        result = builder.build()

        # Verify commands should be in the output
        assert result.verify_commands
        assert "ruff" in result.verify_commands
        assert "pytest" in result.verify_commands
        assert "check ." in result.verify_commands

    def test_context_determinism(self, python_project: Path) -> None:
        """Test that context building is deterministic."""
        builder = RepoContextBuilder(python_project, gates=[])

        result1 = builder.build()
        result2 = builder.build()

        assert result1.project_map == result2.project_map
        assert result1.tooling_snapshot == result2.tooling_snapshot


class TestContextPackIntegration:
    """Test ContextPack with repo context files."""

    def test_write_and_read_tooling_snapshot(self, tmp_path: Path) -> None:
        """Test writing and reading tooling snapshot."""
        paths = RunPaths.create_new(tmp_path)
        pack = ContextPack(paths)

        content = "### Ruff Config\n\n- line-length: 100"
        pack.write_tooling_snapshot(content)

        assert pack.tooling_snapshot_exists()
        assert pack.read_tooling_snapshot() == content

    def test_write_and_read_verify_commands(self, tmp_path: Path) -> None:
        """Test writing and reading verify commands."""
        paths = RunPaths.create_new(tmp_path)
        pack = ContextPack(paths)

        content = "- ruff: `ruff check .`\n- pytest: `pytest -q`"
        pack.write_verify_commands(content)

        assert pack.verify_commands_exists()
        assert pack.read_verify_commands() == content

    def test_context_summary_includes_new_files(self, tmp_path: Path) -> None:
        """Test that context summary includes new artifact types."""
        paths = RunPaths.create_new(tmp_path)
        pack = ContextPack(paths)

        summary = pack.get_context_summary()

        assert "tooling_snapshot.md" in summary
        assert "verify_commands.md" in summary
        assert summary["tooling_snapshot.md"] is False  # Not written yet


class TestRepoContextInRunner:
    """Test repo context integration in Runner."""

    def test_runner_builds_context_on_run(
        self, python_project: Path, tmp_path: Path  # noqa: ARG002
    ) -> None:
        """Test that runner builds repo context during run setup."""
        # Initialize git repo in project
        import subprocess

        subprocess.run(
            ["git", "init"], cwd=python_project, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=python_project,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=python_project,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "add", "."], cwd=python_project, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "Initial"],
            cwd=python_project,
            check=True,
            capture_output=True,
        )

        # Create config
        config = OrxConfig.default(EngineType.FAKE)

        # Create runner (not dry_run so worktree is actually created)
        runner = Runner(config, base_dir=python_project, dry_run=False)

        # Initialize state and workspace manually for testing
        runner.state.initialize()
        runner.pack.write_task("Test task")
        runner.workspace.create("main")

        # Build repo context
        runner._build_repo_context()

        # Verify context was written
        assert runner.pack.tooling_snapshot_exists()
        assert runner.pack.project_map_exists()

        tooling = runner.pack.read_tooling_snapshot()
        assert tooling
        assert "Ruff" in tooling or "ruff" in tooling.lower()

        # Clean up worktree
        runner.workspace.remove()

    def test_runner_skips_existing_context_on_resume(
        self,
        python_project: Path,
        tmp_path: Path,  # noqa: ARG002
    ) -> None:
        """Test that runner doesn't overwrite context on resume."""

        # Initialize git repo
        import subprocess

        subprocess.run(
            ["git", "init"], cwd=python_project, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=python_project,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=python_project,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "add", "."], cwd=python_project, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "Initial"],
            cwd=python_project,
            check=True,
            capture_output=True,
        )

        # Create config
        config = OrxConfig.default(EngineType.FAKE)

        # Create runner and set up initial context
        runner = Runner(config, base_dir=python_project, dry_run=True)
        runner.state.initialize()
        runner.pack.write_task("Test task")
        runner.workspace.create("main")

        # Write custom context (simulating previous run)
        custom_content = "### Custom Context\n\nPreviously generated"
        runner.pack.write_tooling_snapshot(custom_content)
        runner.pack.write_project_map("### Custom Profile")

        # Build context (should skip because files exist)
        runner._build_repo_context()

        # Verify original content preserved
        assert runner.pack.read_tooling_snapshot() == custom_content
        assert "Custom" in runner.pack.read_project_map()
