"""Unit tests for knowledge evidence collection."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orx.knowledge.evidence import EvidenceCollector, EvidencePack


@pytest.fixture
def mock_paths() -> MagicMock:
    """Create mock RunPaths."""
    paths = MagicMock()
    paths.run_id = "test_run_123"
    paths.context = Path("/tmp/run/context")
    paths.artifacts = Path("/tmp/run/artifacts")
    paths.logs = Path("/tmp/run/logs")
    paths.patch_diff = Path("/tmp/run/artifacts/patch.diff")
    return paths


@pytest.fixture
def mock_pack() -> MagicMock:
    """Create mock ContextPack."""
    pack = MagicMock()
    pack.read_spec.return_value = "## Specification\nDo something useful."
    pack.read_project_map.return_value = None
    pack.read_decisions.return_value = None
    return pack


class TestEvidencePack:
    """Tests for EvidencePack dataclass."""

    def test_summary_empty(self) -> None:
        """Test summary with empty evidence."""
        pack = EvidencePack()
        summary = pack.summary()

        assert "spec=0" in summary
        assert "patch=0" in summary
        assert "changed_files=0" in summary

    def test_summary_with_data(self) -> None:
        """Test summary with populated evidence."""
        pack = EvidencePack(
            spec="Long specification text here.",
            patch_diff="diff --git a/file\n+new line",
            changed_files=["src/app.py", "tests/test.py"],
            current_agents_md="# AGENTS.md content",
            current_arch_md="# ARCHITECTURE.md content",
        )
        summary = pack.summary()

        assert "spec=29" in summary  # "Long specification text here."
        assert "changed_files=2" in summary
        assert "has_agents=True" in summary
        assert "has_arch=True" in summary


class TestEvidenceCollector:
    """Tests for EvidenceCollector."""

    def test_parse_changed_files_from_diff(self) -> None:
        """Test parsing changed files from git diff."""
        patch = """diff --git a/src/app.py b/src/app.py
index 1234567..abcdefg 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,4 @@
+new line
 existing
diff --git a/tests/test_app.py b/tests/test_app.py
--- a/tests/test_app.py
+++ b/tests/test_app.py
@@ -1 +1,2 @@
+test
"""
        # Create a collector with mocks
        collector = EvidenceCollector(
            paths=MagicMock(),
            pack=MagicMock(),
            repo_root=Path("/tmp"),
        )

        # Mock the _read_patch_diff to return our test patch
        collector._read_patch_diff = lambda: patch

        files = collector._parse_changed_files()

        assert "src/app.py" in files
        assert "tests/test_app.py" in files
        assert len(files) == 2

    def test_parse_changed_files_empty_diff(self) -> None:
        """Test parsing when diff is empty."""
        collector = EvidenceCollector(
            paths=MagicMock(),
            pack=MagicMock(),
            repo_root=Path("/tmp"),
        )
        collector._read_patch_diff = lambda: ""

        files = collector._parse_changed_files()

        assert files == []

    def test_read_repo_file_exists(self, tmp_path: Path) -> None:
        """Test reading existing repo file."""
        # Create test file
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# Test AGENTS content")

        collector = EvidenceCollector(
            paths=MagicMock(),
            pack=MagicMock(),
            repo_root=tmp_path,
        )

        content = collector._read_repo_file("AGENTS.md")

        assert content == "# Test AGENTS content"

    def test_read_repo_file_missing(self, tmp_path: Path) -> None:
        """Test reading missing repo file returns empty string."""
        collector = EvidenceCollector(
            paths=MagicMock(),
            pack=MagicMock(),
            repo_root=tmp_path,
        )

        content = collector._read_repo_file("MISSING.md")

        assert content == ""

    def test_collect_gate_logs(self, tmp_path: Path) -> None:
        """Test collecting gate logs."""
        paths = MagicMock()
        paths.logs = tmp_path / "logs"
        paths.logs.mkdir()

        # Create some log files
        (paths.logs / "ruff.log").write_text("ruff output line 1\nline 2\nline 3")
        (paths.logs / "pytest.log").write_text("pytest output")

        collector = EvidenceCollector(
            paths=paths,
            pack=MagicMock(),
            repo_root=tmp_path,
        )

        logs = collector._collect_gate_logs(tail_lines=2)

        assert "ruff" in logs
        assert "line 2" in logs["ruff"]
        assert "line 3" in logs["ruff"]
        assert "pytest" in logs
        assert "pytest output" in logs["pytest"]
