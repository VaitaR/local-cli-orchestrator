"""Tests for MCP server operator guide integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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
    assert "execute_orx_cli" in instructions


def test_get_operator_guide_tool_returns_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tool should expose guide text directly to clients."""
    monkeypatch.setenv("ORX_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "SKILLS.md").write_text("# SKILLS\nfrom tool")

    content = mcp_server.get_operator_guide()
    assert "from tool" in content


def test_start_run_supports_model_and_engine_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """start_run should forward CLI-equivalent options to `orx run`."""
    monkeypatch.setenv("ORX_PROJECT_ROOT", str(tmp_path))

    recorded: dict[str, object] = {}
    proc = MagicMock()
    proc.pid = 12345

    def _start_process(
        command: list[str],
        *,
        cwd: Path | None = None,
        stdout_path: Path | None = None,
        stderr_path: Path | None = None,
        env: dict[str, str] | None = None,
        start_new_session: bool = True,
    ) -> MagicMock:
        _ = (stdout_path, stderr_path, env)
        recorded["command"] = command
        recorded["cwd"] = cwd
        recorded["start_new_session"] = start_new_session
        return proc

    with (
        patch.object(mcp_server.CommandRunner, "start_process", side_effect=_start_process),
        patch.object(mcp_server, "_wait_for_new_run_id", return_value="20260216_foo"),
    ):
        result = mcp_server.start_run(
            task="fix bug",
            pipeline="fast_fix",
            config_path="orx.yaml",
            engine=mcp_server.EngineType.CODEX,
            model="gpt-5.2",
            base_branch="dev",
            legacy_fsm=False,
            dry_run=True,
        )

    assert result["run_id"] == "20260216_foo"
    assert result["pid"] == "12345"

    cmd = recorded["command"]
    assert isinstance(cmd, list)
    assert cmd[:3] == ["orx", "run", "--dir"]
    assert "--config" in cmd
    assert "--engine" in cmd and cmd[cmd.index("--engine") + 1] == "codex"
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "gpt-5.2"
    assert "--pipeline" in cmd and cmd[cmd.index("--pipeline") + 1] == "fast_fix"
    assert "--base-branch" in cmd and cmd[cmd.index("--base-branch") + 1] == "dev"
    assert "--dry-run" in cmd
    assert cmd[-1] == "fix bug"


def test_start_run_rejects_legacy_fsm_with_custom_pipeline() -> None:
    """legacy_fsm cannot be combined with a non-default pipeline."""
    result = mcp_server.start_run(
        task="x",
        pipeline="fast_fix",
        legacy_fsm=True,
    )
    assert "error" in result


def test_execute_orx_cli_returns_json_payload() -> None:
    """execute_orx_cli should parse JSON stdout when possible."""
    with patch.object(
        mcp_server.CommandRunner,
        "run_capture",
        return_value=(0, '{"ok": true}', ""),
    ):
        result = mcp_server.execute_orx_cli(args=["pipelines", "list", "--json"])

    assert result["returncode"] == 0
    assert isinstance(result["json"], dict)
    parsed = result["json"]
    assert parsed is not None
    assert parsed["ok"] is True


def test_execute_orx_cli_background_run_returns_pid_and_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Background mode should return pid and discovered run_id."""
    monkeypatch.setenv("ORX_PROJECT_ROOT", str(tmp_path))
    proc = MagicMock()
    proc.pid = 999

    with (
        patch.object(mcp_server.CommandRunner, "start_process", return_value=proc),
        patch.object(mcp_server, "_wait_for_new_run_id", return_value="20260216_bar"),
    ):
        result = mcp_server.execute_orx_cli(
            args=["run", "hello"],
            background=True,
        )

    assert result["status"] == "started"
    assert result["pid"] == "999"
    assert result["run_id"] == "20260216_bar"
