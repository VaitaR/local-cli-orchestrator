"""Tests for prompt rendering."""

from pathlib import Path

import pytest

from orx.prompts.renderer import PromptRenderer, render_prompt


class TestPromptRenderer:
    """Tests for PromptRenderer."""

    def test_list_templates(self) -> None:
        """Test listing available templates."""
        renderer = PromptRenderer()
        templates = renderer.list_templates()

        # Should have the core templates
        assert "plan" in templates
        assert "spec" in templates
        assert "decompose" in templates
        assert "decompose_fix" in templates
        assert "implement" in templates
        assert "fix" in templates
        assert "review" in templates

    def test_template_exists(self) -> None:
        """Test template existence check."""
        renderer = PromptRenderer()

        assert renderer.template_exists("plan")
        assert renderer.template_exists("spec")
        assert not renderer.template_exists("nonexistent")

    def test_render_plan(self) -> None:
        """Test rendering plan template."""
        renderer = PromptRenderer()

        content = renderer.render(
            "plan",
            task="Build a CLI tool for X",
            project_context="Python project with pytest",
        )

        assert "Build a CLI tool for X" in content
        assert "Python project with pytest" in content
        assert "plan.md" in content

    def test_render_spec(self) -> None:
        """Test rendering spec template."""
        renderer = PromptRenderer()

        content = renderer.render(
            "spec",
            task="Build a CLI tool",
            plan="1. Create CLI\n2. Add commands",
            project_context="",
        )

        assert "Build a CLI tool" in content
        assert "Create CLI" in content
        assert "spec.md" in content

    def test_render_decompose(self) -> None:
        """Test rendering decompose template."""
        renderer = PromptRenderer()

        content = renderer.render(
            "decompose",
            spec="## Acceptance\n- Feature works",
            plan="Step 1: Implement",
            run_id="test_run_123",
            max_items=5,
        )

        assert "test_run_123" in content
        assert "backlog.yaml" in content
        assert "W001" in content

    def test_render_decompose_fix(self) -> None:
        """Test rendering decompose fix template."""
        renderer = PromptRenderer()

        content = renderer.render(
            "decompose_fix",
            error="Invalid YAML: mapping values are not allowed here",
            invalid_output="not yaml",
            run_id="test_run_123",
            max_items=3,
        )

        assert "Invalid YAML" in content
        assert "test_run_123" in content

    def test_render_implement(self) -> None:
        """Test rendering implement template."""
        renderer = PromptRenderer()

        content = renderer.render(
            "implement",
            task_summary="Build feature",
            spec_highlights="## Acceptance Criteria\n- Feature spec",
            item_id="W001",
            item_title="Implement function",
            item_objective="Create the function",
            acceptance=["Function works", "Tests pass"],
            files_hint=["src/app.py"],
            file_snippets=[],
        )

        assert "W001" in content
        assert "Implement function" in content
        assert "Function works" in content
        assert "src/app.py" in content

    def test_render_fix(self) -> None:
        """Test rendering fix template."""
        renderer = PromptRenderer()

        content = renderer.render(
            "fix",
            task_summary="Build feature",
            spec_highlights="## Acceptance Criteria\n- Feature spec",
            item_id="W001",
            item_title="Fix function",
            item_objective="Fix the function",
            acceptance=["Function works"],
            attempt=2,
            ruff_failed=True,
            ruff_log="E501 line too long",
            pytest_failed=False,
            pytest_log="",
            diff_empty=False,
            patch_diff="",
            files_hint=["src/app.py"],
            file_snippets=[],
        )

        assert "W001" in content
        assert "Attempt" in content or "attempt" in content
        assert "E501" in content

    def test_render_fix_empty_diff(self) -> None:
        """Test rendering fix template with empty diff."""
        renderer = PromptRenderer()

        content = renderer.render(
            "fix",
            task_summary="Build feature",
            spec_highlights="## Acceptance Criteria\n- Feature spec",
            item_id="W001",
            item_title="Fix function",
            item_objective="Fix the function",
            acceptance=["Function works"],
            attempt=1,
            ruff_failed=False,
            ruff_log="",
            pytest_failed=False,
            pytest_log="",
            diff_empty=True,
            patch_diff="",
            files_hint=[],
            file_snippets=[],
        )

        assert "No Changes Detected" in content or "no file changes" in content.lower()

    def test_render_review(self) -> None:
        """Test rendering review template."""
        renderer = PromptRenderer()

        content = renderer.render(
            "review",
            spec="Feature spec",
            patch_diff="diff --git a/file.py",
            gate_results=[
                {"name": "ruff", "ok": True, "message": "Passed"},
                {"name": "pytest", "ok": True, "message": "All tests passed"},
            ],
        )

        assert "diff --git" in content
        assert "review.md" in content
        assert "pr_body.md" in content

    def test_render_to_file(self, tmp_path: Path) -> None:
        """Test rendering to file."""
        renderer = PromptRenderer()
        out_path = tmp_path / "prompts" / "plan.md"

        renderer.render_to_file(
            "plan",
            out_path,
            task="Build a feature",
            project_context="",
        )

        assert out_path.exists()
        content = out_path.read_text()
        assert "Build a feature" in content

    def test_render_missing_variable(self) -> None:
        """Test that missing variables raise error."""
        renderer = PromptRenderer()

        with pytest.raises(Exception):  # noqa: B017  # jinja2.UndefinedError
            renderer.render("plan")  # Missing required 'task'


def test_render_prompt_convenience() -> None:
    """Test the convenience function."""
    content = render_prompt(
        "plan",
        task="Quick task",
        project_context="",
    )

    assert "Quick task" in content
