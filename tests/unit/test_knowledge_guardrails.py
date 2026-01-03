"""Unit tests for knowledge guardrails."""

import pytest

from orx.config import KnowledgeConfig
from orx.exceptions import GuardrailError
from orx.knowledge.guardrails import KnowledgeGuardrails


@pytest.fixture
def config() -> KnowledgeConfig:
    """Create default knowledge config."""
    return KnowledgeConfig()


@pytest.fixture
def guardrails(config: KnowledgeConfig) -> KnowledgeGuardrails:
    """Create knowledge guardrails instance."""
    return KnowledgeGuardrails(config)


class TestMarkerBounds:
    """Tests for marker detection and manipulation."""

    def test_find_marker_bounds_agents(self, guardrails: KnowledgeGuardrails) -> None:
        """Test finding AGENTS markers."""
        content = """# AGENTS.md

Some existing content.

<!-- ORX:START AGENTS -->
## Key Files
- src/app.py
<!-- ORX:END AGENTS -->

More content.
"""
        bounds = guardrails.find_marker_bounds(content, "agents")

        assert bounds is not None
        assert "## Key Files" in bounds.content
        assert "src/app.py" in bounds.content

    def test_find_marker_bounds_arch(self, guardrails: KnowledgeGuardrails) -> None:
        """Test finding ARCHITECTURE markers."""
        content = """# Architecture

<!-- ORX:START ARCH -->
## Recent Changes
- Added new module
<!-- ORX:END ARCH -->
"""
        bounds = guardrails.find_marker_bounds(content, "arch")

        assert bounds is not None
        assert "Recent Changes" in bounds.content

    def test_find_marker_bounds_missing(self, guardrails: KnowledgeGuardrails) -> None:
        """Test when markers are missing."""
        content = "# AGENTS.md\n\nNo markers here."

        bounds = guardrails.find_marker_bounds(content, "agents")

        assert bounds is None

    def test_replace_marker_content(self, guardrails: KnowledgeGuardrails) -> None:
        """Test replacing content within markers."""
        original = """# AGENTS.md

<!-- ORX:START AGENTS -->
Old content here.
<!-- ORX:END AGENTS -->

Footer.
"""
        new_content = "New content here.\nWith multiple lines."

        result = guardrails.replace_marker_content(original, "agents", new_content)

        assert "New content here." in result
        assert "With multiple lines." in result
        assert "Old content here." not in result
        assert "Footer." in result
        assert "<!-- ORX:START AGENTS -->" in result
        assert "<!-- ORX:END AGENTS -->" in result

    def test_replace_marker_content_missing_markers(
        self, guardrails: KnowledgeGuardrails
    ) -> None:
        """Test replacing content fails when markers missing."""
        original = "# AGENTS.md\n\nNo markers."

        with pytest.raises(GuardrailError) as exc_info:
            guardrails.replace_marker_content(original, "agents", "new content")

        assert "markers_not_found" in str(exc_info.value.rule)

    def test_create_markers_agents(self, guardrails: KnowledgeGuardrails) -> None:
        """Test creating AGENTS markers."""
        markers = guardrails.create_markers("agents")

        assert "<!-- ORX:START AGENTS -->" in markers
        assert "<!-- ORX:END AGENTS -->" in markers

    def test_create_markers_arch(self, guardrails: KnowledgeGuardrails) -> None:
        """Test creating ARCH markers."""
        markers = guardrails.create_markers("arch")

        assert "<!-- ORX:START ARCH -->" in markers
        assert "<!-- ORX:END ARCH -->" in markers


class TestChangeLimits:
    """Tests for change limit validation."""

    def test_validate_within_limits(self, guardrails: KnowledgeGuardrails) -> None:
        """Test validation passes within limits."""
        old = "line1\nline2\nline3"
        new = "line1\nline2\nline3\nline4\nline5"

        stats = guardrails.validate_change_limits(old, new, "AGENTS.md")

        assert stats.added_lines >= 2
        assert stats.deleted_lines == 0

    def test_validate_exceeds_per_file_limit(self) -> None:
        """Test validation fails when exceeding per-file limit."""
        config = KnowledgeConfig()
        config.limits.max_changed_lines_per_file = 10
        guardrails = KnowledgeGuardrails(config)

        old = "\n".join([f"old_line_{i}" for i in range(100)])
        new = "\n".join([f"new_line_{i}" for i in range(100)])

        with pytest.raises(GuardrailError) as exc_info:
            guardrails.validate_change_limits(old, new, "AGENTS.md")

        assert exc_info.value.rule == "max_changed_lines_per_file"

    def test_validate_exceeds_deleted_limit(self) -> None:
        """Test validation fails when deleting too many lines."""
        config = KnowledgeConfig()
        config.limits.max_deleted_lines = 5
        guardrails = KnowledgeGuardrails(config)

        old = "\n".join([f"line_{i}" for i in range(20)])
        new = "only one line"

        with pytest.raises(GuardrailError) as exc_info:
            guardrails.validate_change_limits(old, new, "AGENTS.md")

        assert exc_info.value.rule == "max_deleted_lines"


class TestAllowlist:
    """Tests for file allowlist."""

    def test_file_allowed_in_list(self, guardrails: KnowledgeGuardrails) -> None:
        """Test file in allowlist is allowed."""
        assert guardrails.is_file_allowed("AGENTS.md") is True
        assert guardrails.is_file_allowed("ARCHITECTURE.md") is True

    def test_file_not_in_list(self, guardrails: KnowledgeGuardrails) -> None:
        """Test file not in allowlist is blocked."""
        assert guardrails.is_file_allowed("README.md") is False
        assert guardrails.is_file_allowed("src/app.py") is False


class TestArchitectureGatekeeping:
    """Tests for architecture update gatekeeping."""

    def test_gatekeeping_disabled(self) -> None:
        """Test gatekeeping can be disabled."""
        config = KnowledgeConfig()
        config.architecture_gatekeeping = False
        guardrails = KnowledgeGuardrails(config)

        # Should always return True when disabled
        assert guardrails.should_update_architecture([]) is True
        assert guardrails.should_update_architecture(["src/utils.py"]) is True

    def test_gatekeeping_detects_module_changes(self, guardrails: KnowledgeGuardrails) -> None:
        """Test gatekeeping detects new module changes."""
        changed_files = ["src/orx/newmodule.py"]

        result = guardrails.should_update_architecture(changed_files)

        assert result is True

    def test_gatekeeping_detects_base_changes(self, guardrails: KnowledgeGuardrails) -> None:
        """Test gatekeeping detects base.py changes."""
        changed_files = ["src/orx/stages/base.py"]

        result = guardrails.should_update_architecture(changed_files)

        assert result is True

    def test_gatekeeping_ignores_internal_changes(self, guardrails: KnowledgeGuardrails) -> None:
        """Test gatekeeping ignores internal implementation changes."""
        changed_files = ["src/orx/stages/plan.py", "tests/test_plan.py"]

        result = guardrails.should_update_architecture(changed_files)

        assert result is False

    def test_gatekeeping_detects_dependency_changes(
        self, guardrails: KnowledgeGuardrails
    ) -> None:
        """Test gatekeeping detects dependency changes."""
        changed_files = ["pyproject.toml"]

        result = guardrails.should_update_architecture(changed_files)

        assert result is True
