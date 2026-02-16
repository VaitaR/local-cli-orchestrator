"""Tests for CLI power tools dependency checking."""

from __future__ import annotations

from unittest.mock import patch

from orx.infra.command import (
    POWER_TOOLS,
    DependencyReport,
    ToolStatus,
    check_dependencies,
)


class TestToolStatus:
    """Tests for ToolStatus dataclass."""

    def test_available_tool(self) -> None:
        t = ToolStatus(
            name="rg",
            available=True,
            path="/usr/local/bin/rg",
            description="ripgrep",
            install_hint="brew install ripgrep",
        )
        assert t.available
        assert t.path == "/usr/local/bin/rg"

    def test_missing_tool(self) -> None:
        t = ToolStatus(
            name="rg",
            available=False,
            path=None,
            description="ripgrep",
            install_hint="brew install ripgrep",
        )
        assert not t.available
        assert t.path is None


class TestDependencyReport:
    """Tests for DependencyReport."""

    def test_all_available(self) -> None:
        report = DependencyReport(
            tools=[
                ToolStatus("rg", True, "/usr/bin/rg", "ripgrep", ""),
                ToolStatus("fd", True, "/usr/bin/fd", "fd", ""),
            ]
        )
        assert report.all_available
        assert len(report.available_tools) == 2
        assert len(report.missing_tools) == 0

    def test_some_missing(self) -> None:
        report = DependencyReport(
            tools=[
                ToolStatus("rg", True, "/usr/bin/rg", "ripgrep", ""),
                ToolStatus("fd", False, None, "fd", "brew install fd"),
            ]
        )
        assert not report.all_available
        assert len(report.available_tools) == 1
        assert len(report.missing_tools) == 1
        assert report.missing_tools[0].name == "fd"

    def test_summary_output(self) -> None:
        report = DependencyReport(
            tools=[
                ToolStatus("rg", True, "/usr/bin/rg", "ripgrep", "brew install ripgrep"),
                ToolStatus("fd", False, None, "fd", "brew install fd"),
            ]
        )
        summary = report.summary()
        assert "✓" in summary
        assert "✗" in summary
        assert "rg" in summary
        assert "fd" in summary
        assert "brew install fd" in summary


class TestCheckDependencies:
    """Tests for check_dependencies function."""

    def test_checks_all_power_tools(self) -> None:
        """Should check all tools defined in POWER_TOOLS."""
        report = check_dependencies()
        tool_names = {t.name for t in report.tools}
        expected = {name for name, _, _ in POWER_TOOLS}
        assert tool_names == expected

    def test_with_extra_tools(self) -> None:
        """Should include extra tools when provided."""
        extras = [("mybin", "custom tool", "pip install mybin")]
        report = check_dependencies(extra_tools=extras)
        tool_names = {t.name for t in report.tools}
        assert "mybin" in tool_names

    @patch("orx.infra.command.shutil.which")
    def test_all_available(self, mock_which: patch) -> None:  # type: ignore[type-arg]
        """When all tools found, report shows all_available."""
        mock_which.return_value = "/usr/local/bin/tool"
        report = check_dependencies()
        assert report.all_available
        for t in report.tools:
            assert t.available
            assert t.path == "/usr/local/bin/tool"

    @patch("orx.infra.command.shutil.which")
    def test_none_available(self, mock_which: patch) -> None:  # type: ignore[type-arg]
        """When no tools found, report shows all missing."""
        mock_which.return_value = None
        report = check_dependencies()
        assert not report.all_available
        assert len(report.missing_tools) == len(POWER_TOOLS)

    @patch("orx.infra.command.shutil.which")
    def test_partial_availability(self, mock_which: patch) -> None:  # type: ignore[type-arg]
        """When some tools found and some not."""

        def selective_which(name: str) -> str | None:
            return "/usr/bin/rg" if name == "rg" else None

        mock_which.side_effect = selective_which
        report = check_dependencies()
        assert not report.all_available
        rg_tool = next(t for t in report.tools if t.name == "rg")
        assert rg_tool.available
        fd_tool = next(t for t in report.tools if t.name == "fd")
        assert not fd_tool.available
