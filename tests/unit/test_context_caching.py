"""Tests for context caching functionality."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orx.config import ContextCachingConfig, EngineType, OrxConfig  # noqa: F401
from orx.prompts.renderer import (
    STATIC_CONTEXT_KEYS,
    PromptRenderer,
    RenderedPrompt,
)

# ============================================================================
# RenderedPrompt Tests
# ============================================================================


class TestRenderedPrompt:
    """Tests for the RenderedPrompt dataclass."""

    def test_prompt_only(self) -> None:
        """RenderedPrompt without system prompt."""
        rp = RenderedPrompt(prompt_path=Path("/tmp/plan.md"))
        assert rp.prompt_path == Path("/tmp/plan.md")
        assert rp.system_prompt_path is None

    def test_with_system_prompt(self) -> None:
        """RenderedPrompt with system prompt path."""
        rp = RenderedPrompt(
            prompt_path=Path("/tmp/plan.md"),
            system_prompt_path=Path("/tmp/plan_system.md"),
        )
        assert rp.system_prompt_path == Path("/tmp/plan_system.md")


# ============================================================================
# PromptRenderer.render_with_context_split Tests
# ============================================================================


class TestRenderWithContextSplit:
    """Tests for the context-split rendering method."""

    @pytest.fixture
    def renderer(self) -> PromptRenderer:
        return PromptRenderer()

    def test_splits_static_and_dynamic(self, renderer: PromptRenderer) -> None:
        """Static context variables go to system prompt file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            result = renderer.render_with_context_split(
                "plan",
                out_dir,
                task="Build a feature",
                agents_context="Follow guidelines from AGENTS.md",
                project_context="Python 3.12 project",
            )

            assert result.prompt_path.exists()
            assert result.system_prompt_path is not None
            assert result.system_prompt_path.exists()

            # System prompt should contain the static context
            system_content = result.system_prompt_path.read_text()
            assert "Follow guidelines from AGENTS.md" in system_content
            assert "Python 3.12 project" in system_content

            # Main prompt should contain the dynamic task but NOT the static context
            main_content = result.prompt_path.read_text()
            assert "Build a feature" in main_content
            assert "Follow guidelines from AGENTS.md" not in main_content

    def test_no_static_context_skips_system_file(
        self, renderer: PromptRenderer
    ) -> None:
        """When no static context is provided, no system prompt file is created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            result = renderer.render_with_context_split(
                "plan",
                out_dir,
                task="Simple task",
            )

            assert result.prompt_path.exists()
            assert result.system_prompt_path is None

    def test_empty_static_context_skipped(self, renderer: PromptRenderer) -> None:
        """Empty string static context values are treated as absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            result = renderer.render_with_context_split(
                "plan",
                out_dir,
                task="A task",
                agents_context="",
                repo_context="",
            )

            assert result.system_prompt_path is None

    def test_system_prompt_file_naming(self, renderer: PromptRenderer) -> None:
        """System prompt file follows <template>_system.md convention."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            result = renderer.render_with_context_split(
                "implement",
                out_dir,
                task_summary="Implement feature",
                spec_highlights="spec",
                item_id="W001",
                item_title="Do the thing",
                item_objective="Make it work",
                item_notes="",
                acceptance=["Works"],
                files_hint=["src/app.py"],
                file_snippets=[],
                agents_context="Static guidelines",
            )

            assert result.system_prompt_path is not None
            assert result.system_prompt_path.name == "implement_system.md"
            assert result.prompt_path.name == "implement.md"


# ============================================================================
# STATIC_CONTEXT_KEYS Tests
# ============================================================================


class TestStaticContextKeys:
    """Verify the set of static context keys is correct."""

    def test_known_static_keys(self) -> None:
        """All expected static keys are present."""
        expected = {
            "agents_context",
            "architecture_overview",
            "architecture",
            "project_context",
            "repo_context",
            "repo_tags",
            "smart_context",
            "verify_commands",
            "definition_of_done",
        }
        assert expected == STATIC_CONTEXT_KEYS

    def test_dynamic_keys_not_in_static(self) -> None:
        """Dynamic keys must never appear in static set."""
        dynamic_keys = {"task", "plan", "spec", "item_id", "patch_diff", "error_logs"}
        assert not dynamic_keys & STATIC_CONTEXT_KEYS


# ============================================================================
# Config Tests
# ============================================================================


class TestContextCachingConfig:
    """Tests for ContextCachingConfig."""

    def test_default_enabled(self) -> None:
        """Context caching is enabled by default."""
        cfg = ContextCachingConfig()
        assert cfg.enabled is True

    def test_disable_caching(self) -> None:
        """Context caching can be disabled."""
        cfg = ContextCachingConfig(enabled=False)
        assert cfg.enabled is False

    def test_in_orx_config(self) -> None:
        """ContextCachingConfig is available in OrxConfig."""
        from orx.config import EngineConfig

        config = OrxConfig(engine=EngineConfig(type=EngineType.FAKE))
        assert config.context_caching.enabled is True

    def test_orx_config_caching_disabled(self) -> None:
        """ContextCachingConfig can be disabled in OrxConfig."""
        from orx.config import EngineConfig

        config = OrxConfig(
            engine=EngineConfig(type=EngineType.FAKE),
            context_caching=ContextCachingConfig(enabled=False),
        )
        assert config.context_caching.enabled is False


# ============================================================================
# Paths Tests
# ============================================================================


class TestPathsSystemPrompt:
    """Tests for system prompt handling in RunPaths."""

    def test_copy_prompt_copies_system_file(self) -> None:
        """copy_prompt_to_worktree should also copy the system prompt file."""
        from orx.paths import RunPaths

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = RunPaths.create_new(Path(tmpdir))

            # Write main prompt
            prompt = paths.prompt_path("plan")
            prompt.parent.mkdir(parents=True, exist_ok=True)
            prompt.write_text("Dynamic content")

            # Write system prompt
            system = paths.prompts_dir / "plan_system.md"
            system.write_text("Static system content")

            # Create worktree directory
            paths.worktree_path.mkdir(parents=True, exist_ok=True)

            # Copy to worktree
            result = paths.copy_prompt_to_worktree("plan")

            assert result.exists()
            assert result.read_text() == "Dynamic content"

            system_dst = result.parent / "plan_system.md"
            assert system_dst.exists()
            assert system_dst.read_text() == "Static system content"

    def test_copy_prompt_no_system_file(self) -> None:
        """copy_prompt_to_worktree works fine without a system prompt file."""
        from orx.paths import RunPaths

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = RunPaths.create_new(Path(tmpdir))

            # Write main prompt only
            prompt = paths.prompt_path("plan")
            prompt.parent.mkdir(parents=True, exist_ok=True)
            prompt.write_text("Dynamic content")

            paths.worktree_path.mkdir(parents=True, exist_ok=True)

            result = paths.copy_prompt_to_worktree("plan")

            assert result.exists()
            system_dst = result.parent / "plan_system.md"
            assert not system_dst.exists()


# ============================================================================
# Claude Code Executor - System Prompt Detection
# ============================================================================


class TestClaudeCodeContextCaching:
    """Tests for Claude Code executor context caching support."""

    def test_system_prompt_flag_when_file_exists(self) -> None:
        """_build_command should add --system-prompt when system file exists."""
        from orx.executors.claude_code import ClaudeCodeExecutor
        from orx.infra.command import CommandRunner

        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_dir = Path(tmpdir)
            prompt_path = prompt_dir / "implement.md"
            prompt_path.write_text("Dynamic task content")

            system_path = prompt_dir / "implement_system.md"
            system_path.write_text("Static system context")

            executor = ClaudeCodeExecutor(cmd=MagicMock(spec=CommandRunner))
            cmd, _ = executor._build_command(
                prompt_path=prompt_path,
                cwd=Path("/workspace"),
            )

            assert "--system-prompt" in cmd
            sp_index = cmd.index("--system-prompt")
            assert cmd[sp_index + 1] == "Static system context"

    def test_no_system_prompt_without_file(self) -> None:
        """_build_command should not add --system-prompt without system file."""
        from orx.executors.claude_code import ClaudeCodeExecutor
        from orx.infra.command import CommandRunner

        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "implement.md"
            prompt_path.write_text("Dynamic task content")

            executor = ClaudeCodeExecutor(cmd=MagicMock(spec=CommandRunner))
            cmd, _ = executor._build_command(
                prompt_path=prompt_path,
                cwd=Path("/workspace"),
            )

            assert "--system-prompt" not in cmd

    def test_empty_system_prompt_skipped(self) -> None:
        """Empty system prompt file should not add --system-prompt flag."""
        from orx.executors.claude_code import ClaudeCodeExecutor
        from orx.infra.command import CommandRunner

        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "plan.md"
            prompt_path.write_text("Task content")

            system_path = Path(tmpdir) / "plan_system.md"
            system_path.write_text("   \n  ")  # whitespace only

            executor = ClaudeCodeExecutor(cmd=MagicMock(spec=CommandRunner))
            cmd, _ = executor._build_command(
                prompt_path=prompt_path,
                cwd=Path("/workspace"),
            )

            assert "--system-prompt" not in cmd


# ============================================================================
# Gemini Executor - Prefix Caching
# ============================================================================


class TestGeminiContextCaching:
    """Tests for Gemini executor context caching support."""

    def test_creates_combined_prompt(self) -> None:
        """_maybe_prepend_system_context creates combined file."""
        from orx.executors.gemini import GeminiExecutor
        from orx.infra.command import CommandRunner

        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "plan.md"
            prompt_path.write_text("Dynamic content")

            system_path = Path(tmpdir) / "plan_system.md"
            system_path.write_text("Static prefix")

            executor = GeminiExecutor(cmd=MagicMock(spec=CommandRunner))
            result = executor._maybe_prepend_system_context(prompt_path)

            assert result != prompt_path
            assert result.name == "plan_combined.md"
            combined = result.read_text()
            # System content should come FIRST (prefix caching)
            assert combined.index("Static prefix") < combined.index("Dynamic content")

    def test_returns_original_without_system(self) -> None:
        """Without system file, returns original prompt path."""
        from orx.executors.gemini import GeminiExecutor
        from orx.infra.command import CommandRunner

        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "plan.md"
            prompt_path.write_text("Content")

            executor = GeminiExecutor(cmd=MagicMock(spec=CommandRunner))
            result = executor._maybe_prepend_system_context(prompt_path)

            assert result == prompt_path

    def test_build_command_uses_combined(self) -> None:
        """_build_command should reference the combined file."""
        from orx.executors.gemini import GeminiExecutor
        from orx.infra.command import CommandRunner

        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "spec.md"
            prompt_path.write_text("Spec content")

            system_path = Path(tmpdir) / "spec_system.md"
            system_path.write_text("System context")

            executor = GeminiExecutor(cmd=MagicMock(spec=CommandRunner))
            cmd, _ = executor._build_command(prompt_path=prompt_path)

            # Should reference the combined file, not original
            prompt_arg = [a for a in cmd if a.startswith("@")]
            assert len(prompt_arg) == 1
            assert "spec_combined.md" in prompt_arg[0]


# ============================================================================
# Codex Executor - Prefix Caching
# ============================================================================


class TestCodexContextCaching:
    """Tests for Codex executor context caching support."""

    def test_creates_combined_prompt(self) -> None:
        """_maybe_prepend_system_context creates combined file."""
        from orx.executors.codex import CodexExecutor
        from orx.infra.command import CommandRunner

        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "implement.md"
            prompt_path.write_text("Work item details")

            system_path = Path(tmpdir) / "implement_system.md"
            system_path.write_text("Static project context")

            executor = CodexExecutor(cmd=MagicMock(spec=CommandRunner))
            result = executor._maybe_prepend_system_context(prompt_path)

            assert result.name == "implement_combined.md"
            combined = result.read_text()
            assert combined.index("Static project context") < combined.index(
                "Work item details"
            )

    def test_returns_original_without_system(self) -> None:
        """Without system file, returns original prompt path."""
        from orx.executors.codex import CodexExecutor
        from orx.infra.command import CommandRunner

        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "plan.md"
            prompt_path.write_text("Content")

            executor = CodexExecutor(cmd=MagicMock(spec=CommandRunner))
            result = executor._maybe_prepend_system_context(prompt_path)

            assert result == prompt_path


# ============================================================================
# System Context Template Tests
# ============================================================================


class TestSystemContextTemplate:
    """Tests for the system_context.md template."""

    @pytest.fixture
    def renderer(self) -> PromptRenderer:
        return PromptRenderer()

    def test_template_exists(self, renderer: PromptRenderer) -> None:
        """system_context template should exist."""
        assert renderer.template_exists("system_context")

    def test_renders_agents_context(self, renderer: PromptRenderer) -> None:
        """Renders agents_context section."""
        content = renderer.render(
            "system_context",
            agents_context="## Rules\n- Follow module boundaries",
        )
        assert "Follow module boundaries" in content
        assert "Development Guidelines" in content

    def test_renders_all_static_sections(self, renderer: PromptRenderer) -> None:
        """All static sections render correctly."""
        content = renderer.render(
            "system_context",
            agents_context="AGENTS content",
            architecture_overview="ARCH overview",
            repo_context="Repo tooling config",
            verify_commands="ruff check .",
            definition_of_done="All tests pass",
        )
        assert "AGENTS content" in content
        assert "ARCH overview" in content
        assert "Repo tooling config" in content
        assert "ruff check ." in content
        assert "All tests pass" in content

    def test_empty_context_renders_minimal(self, renderer: PromptRenderer) -> None:
        """With no context, renders only the header."""
        content = renderer.render("system_context")
        assert "System Context" in content
        # Should not have section headers for empty sections
        assert "Development Guidelines" not in content
