"""Unit tests for context snippet helpers."""

from __future__ import annotations

from pathlib import Path

from orx.context.snippets import build_file_snippets, compact_text, extract_spec_highlights


def test_compact_text_truncates_lines() -> None:
    text = "\n".join([f"line {i}" for i in range(10)])
    compacted = compact_text(text, max_lines=3)
    assert compacted.splitlines() == ["line 0", "line 1", "line 2"]


def test_extract_spec_highlights_prefers_acceptance() -> None:
    spec = "\n".join(
        [
            "# Specification",
            "",
            "## Acceptance Criteria",
            "- Must pass tests",
            "",
            "## Technical Constraints",
            "- Python 3.11",
            "",
            "## Other",
            "Ignore this section",
        ]
    )
    highlights = extract_spec_highlights(spec, max_lines=10)
    assert "Acceptance Criteria" in highlights
    assert "Must pass tests" in highlights
    assert "Technical Constraints" in highlights
    assert "Python 3.11" in highlights
    assert "Ignore this section" not in highlights


def test_build_file_snippets_limits_lines(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    target = worktree / "src" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_text("\n".join([f"line {i}" for i in range(200)]))

    snippets = build_file_snippets(
        worktree=worktree,
        files=["src/app.py"],
        max_lines=10,
    )

    assert len(snippets) == 1
    assert snippets[0].path == "src/app.py"
    assert snippets[0].truncated is True
    assert "line 0" in snippets[0].content
