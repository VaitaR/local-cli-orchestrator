"""Unit tests for guardrails allowlist mode."""

import pytest

from orx.config import GuardrailConfig
from orx.exceptions import GuardrailError
from orx.workspace.guardrails import Guardrails


def test_allowlist_mode_allows_matching_files() -> None:
    """Test that allowlist mode allows files matching patterns."""
    config = GuardrailConfig(
        mode="allowlist",
        allowed_patterns=["src/**/*.py", "tests/**/*.py"],
    )
    guardrails = Guardrails(config)

    # These should be allowed
    allowed_files = [
        "src/app.py",
        "src/utils/helper.py",
        "tests/test_app.py",
        "tests/unit/test_helper.py",
    ]

    # Should not raise
    guardrails.check_files(allowed_files)

    # Check individual files
    for file_path in allowed_files:
        assert guardrails.is_file_allowed(file_path) is True


def test_allowlist_mode_blocks_non_matching_files() -> None:
    """Test that allowlist mode blocks files not matching patterns."""
    config = GuardrailConfig(
        mode="allowlist",
        allowed_patterns=["src/**/*.py"],
    )
    guardrails = Guardrails(config)

    # These should be blocked
    blocked_files = [
        "README.md",
        "package.json",
        "docs/guide.md",
        "tests/test_app.py",  # Not in allowed_patterns
    ]

    for file_path in blocked_files:
        assert guardrails.is_file_allowed(file_path) is False


def test_allowlist_mode_raises_on_violation() -> None:
    """Test that allowlist mode raises GuardrailError on violation."""
    config = GuardrailConfig(
        mode="allowlist",
        allowed_patterns=["src/**/*.py"],
    )
    guardrails = Guardrails(config)

    changed_files = [
        "src/app.py",  # Allowed
        "README.md",  # Not allowed
        "package.json",  # Not allowed
    ]

    with pytest.raises(GuardrailError) as exc_info:
        guardrails.check_files(changed_files)

    assert "Files not in allowlist" in str(exc_info.value)
    assert exc_info.value.rule == "forbidden_files"
    assert "README.md" in exc_info.value.violated_files
    assert "package.json" in exc_info.value.violated_files
    assert "src/app.py" not in exc_info.value.violated_files


def test_allowlist_empty_means_nothing_allowed() -> None:
    """Test that empty allowlist blocks everything."""
    config = GuardrailConfig(
        mode="allowlist",
        allowed_patterns=[],  # Empty allowlist
    )
    guardrails = Guardrails(config)

    # Everything should be blocked
    assert guardrails.is_file_allowed("src/app.py") is False
    assert guardrails.is_file_allowed("README.md") is False

    with pytest.raises(GuardrailError):
        guardrails.check_files(["src/app.py"])


def test_blacklist_mode_still_works() -> None:
    """Test that blacklist mode (default) still works correctly."""
    config = GuardrailConfig(
        mode="blacklist",
        forbidden_patterns=["*.env"],
        forbidden_paths=[".env.local"],
    )
    guardrails = Guardrails(config)

    # Most files should be allowed
    assert guardrails.is_file_allowed("src/app.py") is True
    assert guardrails.is_file_allowed("README.md") is True

    # Forbidden files should be blocked
    assert guardrails.is_file_allowed(".env") is False
    assert guardrails.is_file_allowed(".env.local") is False

    with pytest.raises(GuardrailError):
        guardrails.check_files(["src/app.py", ".env"])


def test_allowlist_with_specific_files() -> None:
    """Test allowlist with specific file paths."""
    config = GuardrailConfig(
        mode="allowlist",
        allowed_patterns=[
            "src/config.yaml",
            "src/values.yaml",
            "src/**/*.py",
        ],
    )
    guardrails = Guardrails(config)

    # Specific files should be allowed
    assert guardrails.is_file_allowed("src/config.yaml") is True
    assert guardrails.is_file_allowed("src/values.yaml") is True
    assert guardrails.is_file_allowed("src/app.py") is True

    # Other files should be blocked
    assert guardrails.is_file_allowed("src/other.yaml") is False
    assert guardrails.is_file_allowed("README.md") is False
