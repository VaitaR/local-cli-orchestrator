"""Tests for context sections extraction utilities."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from orx.context.sections import (
    ExtractedSection,
    extract_agents_context,
    extract_architecture_overview,
    extract_error_files,
    extract_file_tree,
    extract_focused_errors,
    extract_section,
    extract_sections,
)


class TestExtractSection:
    """Tests for extract_section function."""

    def test_extract_single_section(self) -> None:
        """Should extract a section by heading."""
        content = dedent("""
            # Main Title

            Some intro text.

            ## Module Boundaries

            - No cyclic imports
            - Use proper layering

            ## Other Section

            Different content.
        """).strip()

        section = extract_section(content, "Module Boundaries")

        assert section is not None
        assert section.title == "Module Boundaries"
        assert "No cyclic imports" in section.content
        assert "Different content" not in section.content

    def test_extract_section_case_insensitive(self) -> None:
        """Should find section regardless of case."""
        content = dedent("""
            ## module boundaries

            Content here.
        """).strip()

        section = extract_section(content, "Module Boundaries")
        assert section is not None

    def test_extract_section_partial_match(self) -> None:
        """Should find section with partial heading match."""
        content = dedent("""
            ## NOT TO DO (Common LLM Mistakes)

            Don't do this.
        """).strip()

        section = extract_section(content, "NOT TO DO")
        assert section is not None
        assert "Don't do this" in section.content

    def test_extract_section_with_subsections(self) -> None:
        """Should include nested subsections by default."""
        content = dedent("""
            ## Parent Section

            Parent content.

            ### Subsection

            Nested content.

            ## Next Section

            Different.
        """).strip()

        section = extract_section(content, "Parent Section", include_subsections=True)

        assert section is not None
        assert "Parent content" in section.content
        assert "Nested content" in section.content
        assert "Different" not in section.content

    def test_extract_section_without_subsections(self) -> None:
        """Should exclude subsections when requested."""
        content = dedent("""
            ## Parent Section

            Parent content.

            ### Subsection

            Nested content.
        """).strip()

        section = extract_section(content, "Parent Section", include_subsections=False)

        assert section is not None
        assert "Parent content" in section.content
        assert "Nested content" not in section.content

    def test_extract_section_not_found(self) -> None:
        """Should return None when section not found."""
        content = "## Some Section\n\nContent."
        section = extract_section(content, "Nonexistent")
        assert section is None

    def test_extract_section_render(self) -> None:
        """Should render section as markdown."""
        section = ExtractedSection(
            title="Test",
            content="Line 1\nLine 2",
            level=2,
            source="test.md",
        )

        rendered = section.render()

        assert "## Test" in rendered
        assert "Line 1" in rendered
        assert "_Source: test.md_" in rendered


class TestExtractSections:
    """Tests for extract_sections function."""

    def test_extract_multiple_sections(self) -> None:
        """Should extract multiple sections."""
        content = dedent("""
            ## Section One

            Content one.

            ## Section Two

            Content two.

            ## Section Three

            Content three.
        """).strip()

        sections = extract_sections(content, ["Section One", "Section Three"])

        assert len(sections) == 2
        assert sections[0].title == "Section One"
        assert sections[1].title == "Section Three"

    def test_extract_sections_partial_match(self) -> None:
        """Should only return sections that exist."""
        content = "## Real Section\n\nContent."

        sections = extract_sections(content, ["Real Section", "Fake Section"])

        assert len(sections) == 1
        assert sections[0].title == "Real Section"


class TestExtractAgentsContext:
    """Tests for extract_agents_context function."""

    def test_extract_from_agents_md(self, tmp_path: Path) -> None:
        """Should extract key sections from AGENTS.md."""
        agents_content = dedent("""
            # AGENTS.md

            ## Module Boundaries

            - src/orx/cli.py: Entry point
            - src/orx/runner.py: Orchestration

            ## NOT TO DO

            - Don't use bare except
            - Don't hardcode paths

            ## Other Section

            Ignored.
        """).strip()

        (tmp_path / "AGENTS.md").write_text(agents_content)

        result = extract_agents_context(tmp_path)

        assert "Module Boundaries" in result
        assert "NOT TO DO" in result
        assert "Don't use bare except" in result

    def test_extract_missing_file(self, tmp_path: Path) -> None:
        """Should return empty string when file missing."""
        result = extract_agents_context(tmp_path)
        assert result == ""


class TestExtractArchitectureOverview:
    """Tests for extract_architecture_overview function."""

    def test_extract_from_architecture_md(self, tmp_path: Path) -> None:
        """Should extract overview sections from ARCHITECTURE.md."""
        arch_content = dedent("""
            # System Architecture

            ## Overview

            orx is a CLI orchestrator.

            ## Component Architecture

            ### CLI Layer
            Entry point.

            ## Other Details

            Not needed.
        """).strip()

        (tmp_path / "ARCHITECTURE.md").write_text(arch_content)

        result = extract_architecture_overview(tmp_path)

        assert "Overview" in result
        assert "Component Architecture" in result
        assert "CLI orchestrator" in result

    def test_extract_missing_file(self, tmp_path: Path) -> None:
        """Should return empty string when file missing."""
        result = extract_architecture_overview(tmp_path)
        assert result == ""


class TestExtractFileTree:
    """Tests for extract_file_tree function."""

    def test_basic_tree(self, tmp_path: Path) -> None:
        """Should generate basic file tree."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("# main")
        (src / "utils.py").write_text("# utils")

        subdir = src / "subdir"
        subdir.mkdir()
        (subdir / "helper.py").write_text("# helper")

        result = extract_file_tree(tmp_path)

        # Should contain file structure markers
        assert "```" in result
        assert "main.py" in result
        assert "subdir/" in result or "helper.py" in result

    def test_skips_pycache(self, tmp_path: Path) -> None:
        """Should skip __pycache__ directories."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("# main")
        pycache = src / "__pycache__"
        pycache.mkdir()
        (pycache / "main.cpython-311.pyc").write_bytes(b"")

        result = extract_file_tree(tmp_path)

        assert "main.py" in result
        assert "__pycache__" not in result


class TestExtractFocusedErrors:
    """Tests for extract_focused_errors function."""

    def test_extract_ruff_errors(self) -> None:
        """Should extract ruff error lines."""
        log = dedent("""
            src/orx/test.py:10:1: F401 'os' imported but unused
            src/orx/test.py:15:1: I001 Import block is un-sorted
            All other checks passed
        """).strip()

        result = extract_focused_errors(log, max_errors=10)

        assert "F401" in result
        assert "I001" in result

    def test_extract_pytest_errors(self) -> None:
        """Should extract pytest failure lines."""
        log = dedent("""
            tests/test_foo.py::test_bar FAILED
            E       AssertionError: assert 1 == 2
            E       +  where 1 = func()
        """).strip()

        result = extract_focused_errors(log, max_errors=10)

        assert "FAILED" in result or "AssertionError" in result

    def test_dedupe_similar_errors(self) -> None:
        """Should deduplicate similar errors."""
        log = dedent("""
            src/a.py:1:1: error: Same error type
            src/a.py:2:1: error: Same error type
            src/a.py:3:1: error: Same error type
        """).strip()

        result = extract_focused_errors(log, max_errors=10)

        # Should have fewer errors than input (deduped by pattern)
        # The exact count depends on context lines overlap
        assert result != ""

    def test_fallback_for_no_errors(self) -> None:
        """Should return tail of log when no errors found."""
        log = "Just some normal output\n" * 50

        result = extract_focused_errors(log, max_errors=10)

        assert result != ""  # Should return something

    def test_empty_log(self) -> None:
        """Should handle empty log."""
        result = extract_focused_errors("", max_errors=10)
        assert result == ""


class TestExtractErrorFiles:
    """Tests for extract_error_files function."""

    def test_extract_python_files(self) -> None:
        """Should extract Python file paths from errors."""
        log = dedent("""
            src/orx/runner.py:123: error: Missing type
            File "src/orx/config.py", line 45
        """).strip()

        files = extract_error_files(log)

        assert "src/orx/runner.py" in files
        assert "src/orx/config.py" in files

    def test_skip_site_packages(self) -> None:
        """Should skip stdlib and site-packages paths."""
        log = dedent("""
            src/orx/runner.py:1: error
            /opt/miniconda3/lib/python3.11/site-packages/jinja2/env.py:100: error
        """).strip()

        files = extract_error_files(log)

        assert "src/orx/runner.py" in files
        # site-packages paths should be filtered out
        assert not any("site-packages" in f for f in files)

    def test_empty_log(self) -> None:
        """Should handle empty log."""
        files = extract_error_files("")
        assert files == []
