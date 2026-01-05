"""Utilities for extracting focused context snippets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class FileSnippet:
    """Snippet of a file's content."""

    path: str
    content: str
    truncated: bool = False


def _compact_lines(lines: list[str], max_lines: int) -> tuple[str, bool]:
    if len(lines) <= max_lines:
        return "\n".join(lines), False

    head_count = max_lines // 2
    tail_count = max_lines - head_count
    head = lines[:head_count]
    tail = lines[-tail_count:]
    content = "\n".join(head + ["... (truncated) ..."] + tail)
    return content, True


def build_file_snippets(
    *,
    worktree: Path,
    files: Iterable[str],
    max_lines: int = 120,
    max_files: int = 8,
) -> list[FileSnippet]:
    """Build file snippets for a set of file paths.

    Args:
        worktree: Root path of the worktree.
        files: Iterable of file paths (relative to worktree).
        max_lines: Maximum lines per snippet.
        max_files: Maximum number of files to include.

    Returns:
        List of FileSnippet entries.
    """
    snippets: list[FileSnippet] = []
    seen: set[str] = set()

    for raw_path in files:
        if len(snippets) >= max_files:
            break
        path = raw_path.strip()
        if not path or path in seen:
            continue
        seen.add(path)

        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = worktree / file_path

        if not file_path.exists() or not file_path.is_file():
            continue

        try:
            content = file_path.read_text().splitlines()
        except OSError:
            continue

        snippet, truncated = _compact_lines(content, max_lines=max_lines)
        snippets.append(
            FileSnippet(
                path=str(Path(path)),
                content=snippet,
                truncated=truncated,
            )
        )

    return snippets


def extract_spec_highlights(spec: str, max_lines: int = 120) -> str:
    """Extract key sections from a spec for focused prompts."""
    if not spec:
        return ""

    headings = {"acceptance", "acceptance criteria", "constraints", "technical constraints"}
    lines = spec.splitlines()
    selected: list[str] = []
    capturing = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip().lower()
            capturing = title in headings
            if capturing:
                selected.append(line)
            continue
        if capturing:
            selected.append(line)

    if not selected:
        selected = lines[:max_lines]
    else:
        selected = selected[:max_lines]

    return "\n".join(selected).strip()


def compact_text(text: str, max_lines: int = 80) -> str:
    """Compact a block of text to a line budget."""
    if not text:
        return ""
    lines = text.splitlines()
    return "\n".join(lines[:max_lines]).strip()
