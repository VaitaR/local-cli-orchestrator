"""Unit tests for guardrails artifact filtering (forbidden_new_files)."""

from pathlib import Path

import pytest

from orx.config import GuardrailConfig
from orx.exceptions import GuardrailError
from orx.workspace.guardrails import Guardrails


def test_forbidden_new_files_blocks_artifacts(tmp_path: Path) -> None:
    """Test that forbidden_new_files blocks artifact creation."""
    config = GuardrailConfig(
        forbidden_new_files=["pr_body.md", "review.md", "*.orx.md"],
    )
    guardrails = Guardrails(config)

    new_files = [
        "pr_body.md",
        "review.md",
    ]

    with pytest.raises(GuardrailError) as exc_info:
        guardrails.check_new_files(new_files, tmp_path)

    assert "Forbidden new files created" in str(exc_info.value)
    assert exc_info.value.rule == "forbidden_new_files"
    assert "pr_body.md" in exc_info.value.violated_files
    assert "review.md" in exc_info.value.violated_files


def test_forbidden_new_files_allows_normal_files(tmp_path: Path) -> None:
    """Test that forbidden_new_files allows normal files."""
    config = GuardrailConfig(
        forbidden_new_files=["pr_body.md", "review.md"],
    )
    guardrails = Guardrails(config)

    new_files = [
        "src/app.py",
        "tests/test_app.py",
        "README.md",
    ]

    # Should not raise
    guardrails.check_new_files(new_files, tmp_path)


def test_forbidden_new_files_pattern_matching(tmp_path: Path) -> None:
    """Test that forbidden_new_files supports glob patterns."""
    config = GuardrailConfig(
        forbidden_new_files=["*.orx.md", ".orx-*"],
    )
    guardrails = Guardrails(config)

    # These should be blocked
    blocked_files = [
        "temp.orx.md",
        "debug.orx.md",
        ".orx-temp",
    ]

    with pytest.raises(GuardrailError):
        guardrails.check_new_files(blocked_files, tmp_path)

    # These should be allowed
    allowed_files = [
        "normal.md",
        "temp.txt",
    ]

    guardrails.check_new_files(allowed_files, tmp_path)


def test_forbidden_new_files_disabled(tmp_path: Path) -> None:
    """Test that disabled guardrails don't check new files."""
    config = GuardrailConfig(
        enabled=False,
        forbidden_new_files=["pr_body.md"],
    )
    guardrails = Guardrails(config)

    # Should not raise even for forbidden files
    guardrails.check_new_files(["pr_body.md"], tmp_path)


def test_forbidden_new_files_relative_paths(tmp_path: Path) -> None:
    """Test that forbidden_new_files works with relative paths."""
    config = GuardrailConfig(
        forbidden_new_files=["pr_body.md", "review.md"],
    )
    guardrails = Guardrails(config)

    # Create subdirectories
    subdir = tmp_path / "subdir"
    subdir.mkdir()

    # Files in root should be blocked
    with pytest.raises(GuardrailError):
        guardrails.check_new_files([str(tmp_path / "pr_body.md")], tmp_path)

    # Files in subdirectories should also be checked
    # (depends on pattern matching implementation)
    new_files = [str(subdir / "pr_body.md")]
    with pytest.raises(GuardrailError):
        guardrails.check_new_files(new_files, tmp_path)
