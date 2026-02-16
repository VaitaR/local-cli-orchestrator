"""Tests for MCP server operator guide integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from orx.mcp import server as mcp_server


def test_read_operator_guide_prefers_skills_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SKILLS.md should be used when present."""
    monkeypatch.setenv("ORX_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "SKILLS.md").write_text("# SKILLS\npreferred")
    (tmp_path / "SKILSS.md").write_text("# SKILSS\nlegacy")

    content = mcp_server._read_operator_guide()
    assert "preferred" in content
    assert "legacy" not in content


def test_read_operator_guide_uses_legacy_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Legacy SKILSS.md should still work for compatibility."""
    monkeypatch.setenv("ORX_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "SKILSS.md").write_text("# SKILSS\nlegacy")

    content = mcp_server._read_operator_guide()
    assert "legacy" in content


def test_read_operator_guide_returns_fallback_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fallback guidance is returned when no guide files exist."""
    monkeypatch.setenv("ORX_PROJECT_ROOT", str(tmp_path))

    content = mcp_server._read_operator_guide()
    assert "Guide file not found" in content
    assert "start_run" in content


def test_mcp_instructions_reference_operator_guide() -> None:
    """Server-level MCP instructions should direct clients to operator_guide."""
    instructions = mcp_server.mcp.instructions
    assert instructions is not None
    assert "get_operator_guide" in instructions
    assert "Do NOT call start_run(task='operator_guide')" in instructions


def test_get_operator_guide_tool_returns_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tool should expose guide text directly to clients."""
    monkeypatch.setenv("ORX_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "SKILLS.md").write_text("# SKILLS\nfrom tool")

    content = mcp_server.get_operator_guide()
    assert "from tool" in content
