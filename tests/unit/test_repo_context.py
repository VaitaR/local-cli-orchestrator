"""Unit tests for repo context pack extractors and packer."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

from orx.context.repo_context.blocks import ContextBlock, ContextPriority, merge_blocks
from orx.context.repo_context.builder import RepoContextBuilder
from orx.context.repo_context.packer import ContextPacker, pack_for_stage
from orx.context.repo_context.python_extractor import PythonExtractor
from orx.context.repo_context.ts_extractor import TypeScriptExtractor
from orx.context.repo_context.verify_commands import build_verify_commands


class TestContextBlock:
    """Tests for ContextBlock."""

    def test_render_basic(self) -> None:
        """Test basic block rendering."""
        block = ContextBlock(
            priority=ContextPriority.PYTHON_CORE,
            title="Ruff Config",
            body="- line-length: 100\n- target-version: py311",
            sources=["pyproject.toml"],
        )

        rendered = block.render()
        assert "### Ruff Config" in rendered
        assert "line-length: 100" in rendered
        assert "pyproject.toml" in rendered

    def test_render_compact(self) -> None:
        """Test compact rendering with truncation."""
        block = ContextBlock(
            priority=ContextPriority.PYTHON_CORE,
            title="Long Config",
            body="line1\nline2\nline3\nline4\nline5",
            sources=["config.toml"],
        )

        compact = block.render_compact(max_lines=2)
        assert "line1" in compact
        assert "line2" in compact
        assert "..." in compact

    def test_estimated_chars_calculated(self) -> None:
        """Test that estimated_chars is auto-calculated."""
        block = ContextBlock(
            priority=ContextPriority.LAYOUT,
            title="Test",
            body="Content here",
        )
        assert block.estimated_chars > 0


class TestContextPacker:
    """Tests for ContextPacker."""

    def test_pack_empty(self) -> None:
        """Test packing empty list."""
        packer = ContextPacker(char_budget=1000)
        result = packer.pack([])
        assert result.content == ""
        assert result.included_blocks == []
        assert result.excluded_blocks == []

    def test_pack_within_budget(self) -> None:
        """Test packing blocks within budget."""
        blocks = [
            ContextBlock(
                priority=ContextPriority.VERIFY_COMMANDS,
                title="Gates",
                body="- ruff\n- pytest",
            ),
            ContextBlock(
                priority=ContextPriority.PYTHON_CORE,
                title="Ruff",
                body="- line-length: 100",
            ),
        ]

        packer = ContextPacker(char_budget=5000)
        result = packer.pack(blocks)

        assert len(result.included_blocks) == 2
        assert len(result.excluded_blocks) == 0
        assert "Gates" in result.content
        assert "Ruff" in result.content

    def test_pack_priority_ordering(self) -> None:
        """Test that higher priority blocks come first."""
        blocks = [
            ContextBlock(
                priority=ContextPriority.EXTRAS,
                title="Extras",
                body="low priority",
            ),
            ContextBlock(
                priority=ContextPriority.VERIFY_COMMANDS,
                title="Verify",
                body="high priority",
            ),
        ]

        packer = ContextPacker(char_budget=5000)
        result = packer.pack(blocks)

        # Verify comes before Extras in content
        verify_pos = result.content.find("Verify")
        extras_pos = result.content.find("Extras")
        assert verify_pos < extras_pos

    def test_pack_budget_exceeded(self) -> None:
        """Test that blocks are excluded when budget exceeded."""
        blocks = [
            ContextBlock(
                priority=ContextPriority.VERIFY_COMMANDS,
                title="Important",
                body="x" * 500,
            ),
            ContextBlock(
                priority=ContextPriority.EXTRAS,
                title="Excluded",
                body="x" * 500,
            ),
        ]

        packer = ContextPacker(char_budget=600)
        result = packer.pack(blocks)

        assert len(result.included_blocks) == 1
        assert result.included_blocks[0].title == "Important"
        assert len(result.excluded_blocks) == 1

    def test_pack_deterministic(self) -> None:
        """Test that packing is deterministic."""
        blocks = [
            ContextBlock(priority=80, title="B", body="content"),
            ContextBlock(priority=80, title="A", body="content"),
        ]

        packer = ContextPacker(char_budget=5000)
        result1 = packer.pack(blocks)
        result2 = packer.pack(blocks)

        assert result1.content == result2.content


class TestPythonExtractor:
    """Tests for PythonExtractor."""

    def test_is_python_project_pyproject(self, tmp_path: Path) -> None:
        """Test Python project detection via pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")

        extractor = PythonExtractor(tmp_path)
        assert extractor.is_python_project()

    def test_is_python_project_requirements(self, tmp_path: Path) -> None:
        """Test Python project detection via requirements.txt."""
        (tmp_path / "requirements.txt").write_text("pytest\n")

        extractor = PythonExtractor(tmp_path)
        assert extractor.is_python_project()

    def test_not_python_project(self, tmp_path: Path) -> None:
        """Test non-Python project detection."""
        (tmp_path / "package.json").write_text('{"name": "test"}')

        extractor = PythonExtractor(tmp_path)
        assert not extractor.is_python_project()

    def test_extract_ruff_from_pyproject(self, tmp_path: Path) -> None:
        """Test extracting ruff config from pyproject.toml."""
        pyproject = dedent("""
            [project]
            name = "test"

            [tool.ruff]
            line-length = 100
            target-version = "py311"

            [tool.ruff.lint]
            select = ["E", "F", "I"]
        """)
        (tmp_path / "pyproject.toml").write_text(pyproject)

        extractor = PythonExtractor(tmp_path)
        blocks = extractor.extract_all()

        ruff_block = next((b for b in blocks if "Ruff" in b.title), None)
        assert ruff_block is not None
        assert "line-length: 100" in ruff_block.body
        assert "target-version: py311" in ruff_block.body

    def test_extract_mypy_from_pyproject(self, tmp_path: Path) -> None:
        """Test extracting mypy config from pyproject.toml."""
        pyproject = dedent("""
            [project]
            name = "test"

            [tool.mypy]
            strict = true
            python_version = "3.11"
        """)
        (tmp_path / "pyproject.toml").write_text(pyproject)

        extractor = PythonExtractor(tmp_path)
        blocks = extractor.extract_all()

        mypy_block = next((b for b in blocks if "Mypy" in b.title), None)
        assert mypy_block is not None
        assert "strict: true" in mypy_block.body

    def test_extract_pytest_from_pyproject(self, tmp_path: Path) -> None:
        """Test extracting pytest config from pyproject.toml."""
        pyproject = dedent("""
            [project]
            name = "test"

            [tool.pytest.ini_options]
            testpaths = ["tests"]
            addopts = "-q --tb=short"
        """)
        (tmp_path / "pyproject.toml").write_text(pyproject)

        extractor = PythonExtractor(tmp_path)
        blocks = extractor.extract_all()

        pytest_block = next((b for b in blocks if "Pytest" in b.title), None)
        assert pytest_block is not None
        assert "testpaths: tests" in pytest_block.body

    def test_extract_profile_poetry(self, tmp_path: Path) -> None:
        """Test profile extraction for Poetry project."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        (tmp_path / "poetry.lock").write_text("")
        (tmp_path / "src").mkdir()

        extractor = PythonExtractor(tmp_path)
        profile = extractor.extract_profile_only()

        assert profile is not None
        assert "Poetry" in profile.body
        assert "src/" in profile.body


class TestTypeScriptExtractor:
    """Tests for TypeScriptExtractor."""

    def test_parse_jsonc_with_comments_and_trailing_commas(self, tmp_path: Path) -> None:
        """Test JSONC parsing for tsconfig/eslint style files."""
        (tmp_path / "package.json").write_text('{"name": "test"}')

        tsconfig_jsonc = dedent(
            """
            {
              // comment
              "compilerOptions": {
                "strict": true, /* inline comment */
                "target": "ES2022",
              },
            }
            """
        ).strip()
        (tmp_path / "tsconfig.json").write_text(tsconfig_jsonc)

        extractor = TypeScriptExtractor(tmp_path)
        blocks = extractor.extract_all()
        ts_block = next((b for b in blocks if "TypeScript Configuration" in b.title), None)
        assert ts_block is not None
        assert "strict: true" in ts_block.body
        assert "target: ES2022" in ts_block.body

    def test_is_ts_project_package(self, tmp_path: Path) -> None:
        """Test TS project detection via package.json."""
        (tmp_path / "package.json").write_text('{"name": "test"}')

        extractor = TypeScriptExtractor(tmp_path)
        assert extractor.is_ts_project()

    def test_is_ts_project_tsconfig(self, tmp_path: Path) -> None:
        """Test TS project detection via tsconfig.json."""
        (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {}}')

        extractor = TypeScriptExtractor(tmp_path)
        assert extractor.is_ts_project()

    def test_not_ts_project(self, tmp_path: Path) -> None:
        """Test non-TS project detection."""
        (tmp_path / "pyproject.toml").write_text("[project]")

        extractor = TypeScriptExtractor(tmp_path)
        assert not extractor.is_ts_project()

    def test_extract_scripts(self, tmp_path: Path) -> None:
        """Test extracting npm scripts."""
        package = {
            "name": "test",
            "scripts": {
                "lint": "eslint .",
                "test": "jest",
                "build": "tsc",
            },
        }
        (tmp_path / "package.json").write_text(json.dumps(package))

        extractor = TypeScriptExtractor(tmp_path)
        blocks = extractor.extract_all()

        scripts_block = next((b for b in blocks if "Scripts" in b.title), None)
        assert scripts_block is not None
        assert "lint" in scripts_block.body
        assert "test" in scripts_block.body

    def test_extract_tsconfig(self, tmp_path: Path) -> None:
        """Test extracting tsconfig compiler options."""
        tsconfig = {
            "compilerOptions": {
                "strict": True,
                "target": "ES2022",
                "module": "ESNext",
                "baseUrl": "./src",
            },
        }
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "tsconfig.json").write_text(json.dumps(tsconfig))

        extractor = TypeScriptExtractor(tmp_path)
        blocks = extractor.extract_all()

        ts_block = next((b for b in blocks if "TypeScript Configuration" in b.title), None)
        assert ts_block is not None
        assert "strict: true" in ts_block.body
        assert "target: ES2022" in ts_block.body

    def test_extract_profile_pnpm(self, tmp_path: Path) -> None:
        """Test profile extraction for pnpm project."""
        package = {
            "name": "test",
            "type": "module",
            "devDependencies": {"typescript": "^5.0.0"},
        }
        (tmp_path / "package.json").write_text(json.dumps(package))
        (tmp_path / "pnpm-lock.yaml").write_text("")

        extractor = TypeScriptExtractor(tmp_path)
        profile = extractor.extract_profile_only()

        assert profile is not None
        assert "pnpm" in profile.body
        assert "module" in profile.body

    def test_extract_eslint_json(self, tmp_path: Path) -> None:
        """Test extracting ESLint config from JSON."""
        eslint = {
            "extends": ["eslint:recommended", "plugin:@typescript-eslint/recommended"],
            "parser": "@typescript-eslint/parser",
        }
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / ".eslintrc.json").write_text(json.dumps(eslint))

        extractor = TypeScriptExtractor(tmp_path)
        blocks = extractor.extract_all()

        eslint_block = next((b for b in blocks if "ESLint" in b.title), None)
        assert eslint_block is not None
        assert "extends" in eslint_block.body
        assert "@typescript-eslint/parser" in eslint_block.body


class MockGate:
    """Mock gate for testing."""

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        required: bool = True,
    ):
        self._name = name
        self.command = command
        self.args = args or []
        self.required = required

    @property
    def name(self) -> str:
        return self._name


class TestVerifyCommands:
    """Tests for verify commands builder."""

    def test_build_verify_commands_empty(self) -> None:
        """Test with no gates."""
        block = build_verify_commands([])
        assert block is None

    def test_build_verify_commands_single(self) -> None:
        """Test with single gate."""
        gates = [MockGate("ruff", "ruff", ["check", "."])]
        block = build_verify_commands(gates)

        assert block is not None
        assert "ruff" in block.body
        assert "ruff check ." in block.body
        assert "(required)" in block.body

    def test_build_verify_commands_multiple(self) -> None:
        """Test with multiple gates."""
        gates = [
            MockGate("ruff", "ruff", ["check", "."], required=True),
            MockGate("pytest", "pytest", ["-q"], required=True),
            MockGate("docker", "docker", ["build", "."], required=False),
        ]
        block = build_verify_commands(gates)

        assert block is not None
        assert "ruff" in block.body
        assert "pytest" in block.body
        assert "docker" in block.body
        assert "(optional)" in block.body
        assert block.priority == ContextPriority.VERIFY_COMMANDS


class TestRepoContextBuilder:
    """Tests for RepoContextBuilder."""

    def test_build_python_project(self, tmp_path: Path) -> None:
        """Test building context for Python project."""
        pyproject = dedent("""
            [project]
            name = "test"
            requires-python = ">=3.11"

            [tool.ruff]
            line-length = 100
        """)
        (tmp_path / "pyproject.toml").write_text(pyproject)

        gates = [MockGate("ruff", "ruff", ["check", "."])]
        builder = RepoContextBuilder(tmp_path, gates)
        result = builder.build()

        assert "python" in result.detected_stacks
        assert result.project_map  # Has profile
        assert result.tooling_snapshot  # Has full context
        assert result.verify_commands  # Has gates

    def test_build_typescript_project(self, tmp_path: Path) -> None:
        """Test building context for TypeScript project."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {"strict": true}}')

        builder = RepoContextBuilder(tmp_path, [])
        result = builder.build()

        assert "typescript" in result.detected_stacks
        assert result.project_map

    def test_build_mixed_project(self, tmp_path: Path) -> None:
        """Test building context for mixed Python+TS project."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'backend'\n")
        (tmp_path / "package.json").write_text('{"name": "frontend"}')

        builder = RepoContextBuilder(tmp_path, [])
        result = builder.build()

        assert "python" in result.detected_stacks
        assert "typescript" in result.detected_stacks

    def test_build_empty_project(self, tmp_path: Path) -> None:
        """Test building context for empty project."""
        builder = RepoContextBuilder(tmp_path, [])
        result = builder.build()

        assert result.detected_stacks == []
        assert result.project_map == ""

    def test_build_respects_budget(self, tmp_path: Path) -> None:
        """Test that builder respects character budget."""
        pyproject = dedent("""
            [project]
            name = "test"

            [tool.ruff]
            line-length = 100
            target-version = "py311"
            select = ["E", "F", "I", "W", "UP", "B", "C4", "SIM"]
            ignore = ["E501"]

            [tool.ruff.lint.per-file-ignores]
            "tests/*" = ["S101", "D"]
        """)
        (tmp_path / "pyproject.toml").write_text(pyproject)

        # Small budget
        builder = RepoContextBuilder(tmp_path, [], profile_budget=100, full_budget=200)
        result = builder.build()

        assert len(result.tooling_snapshot) <= 300  # Some overhead

    def test_profile_only(self, tmp_path: Path) -> None:
        """Test build_profile_only method."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        (tmp_path / "poetry.lock").write_text("")

        builder = RepoContextBuilder(tmp_path, [])
        profile = builder.build_profile_only()

        assert "Python" in profile
        assert "Poetry" in profile


class TestPackForStage:
    """Tests for pack_for_stage helper."""

    def test_plan_stage_uses_smaller_budget(self) -> None:
        """Test that plan stage uses smaller budget."""
        blocks = [
            ContextBlock(
                priority=ContextPriority.VERIFY_COMMANDS,
                title="Gates",
                body="x" * 5000,
            ),
        ]

        result = pack_for_stage(blocks, "plan")
        # Plan budget is 3000, should be truncated
        assert len(result) < 4000

    def test_implement_stage_uses_full_budget(self) -> None:
        """Test that implement stage uses full budget."""
        blocks = [
            ContextBlock(
                priority=ContextPriority.VERIFY_COMMANDS,
                title="Gates",
                body="x" * 8000,
            ),
        ]

        result = pack_for_stage(blocks, "implement")
        # Implement budget is 11000, should fit more
        assert len(result) > 3000


class TestMergeBlocks:
    """Tests for merge_blocks helper."""

    def test_merge_empty(self) -> None:
        """Test merging empty list."""
        result = merge_blocks([], "Merged", "test")
        assert result.body == ""

    def test_merge_multiple(self) -> None:
        """Test merging multiple blocks."""
        blocks = [
            ContextBlock(priority=80, title="A", body="content A", sources=["a.py"]),
            ContextBlock(priority=60, title="B", body="content B", sources=["b.py"]),
        ]

        result = merge_blocks(blocks, "Merged", "test")
        assert "content A" in result.body
        assert "content B" in result.body
        assert result.priority == 80  # Highest
        assert "a.py" in result.sources
        assert "b.py" in result.sources
