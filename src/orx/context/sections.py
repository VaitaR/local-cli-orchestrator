"""Markdown section extraction utilities.

Extracts specific sections from markdown files like AGENTS.md and ARCHITECTURE.md
to provide targeted context to LLM agents without overwhelming them with full files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExtractedSection:
    """A section extracted from a markdown file.

    Attributes:
        title: Section heading.
        content: Section body content.
        level: Heading level (1-6).
        source: Source file path.
    """

    title: str
    content: str
    level: int
    source: str

    def render(self, *, include_source: bool = True) -> str:
        """Render the section as markdown.

        Args:
            include_source: Whether to include source attribution.

        Returns:
            Markdown string.
        """
        header = "#" * self.level + " " + self.title
        lines = [header, "", self.content.strip()]
        if include_source:
            lines.append(f"\n_Source: {self.source}_")
        return "\n".join(lines)


def extract_section(
    content: str,
    heading: str,
    *,
    source: str = "",
    include_subsections: bool = True,
) -> ExtractedSection | None:
    """Extract a specific section from markdown content.

    Args:
        content: Full markdown content.
        heading: The heading text to find (without # prefix).
        source: Source file path for attribution.
        include_subsections: Whether to include nested subsections.

    Returns:
        ExtractedSection if found, None otherwise.
    """
    lines = content.split("\n")
    section_lines: list[str] = []
    section_level = 0
    in_section = False

    for line in lines:
        # Check for heading
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)

        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()

            if in_section:
                # Check if we should end the section
                if level <= section_level:
                    # Same or higher level heading - end section
                    break
                elif not include_subsections:
                    # Found a subsection but we don't want them
                    break
                # Otherwise include subsection

            if title.lower() == heading.lower() or heading.lower() in title.lower():
                in_section = True
                section_level = level
                continue  # Don't include the heading line itself

        if in_section:
            section_lines.append(line)

    if not section_lines:
        return None

    # Clean up trailing empty lines
    while section_lines and not section_lines[-1].strip():
        section_lines.pop()

    return ExtractedSection(
        title=heading,
        content="\n".join(section_lines),
        level=section_level,
        source=source,
    )


def extract_sections(
    content: str,
    headings: list[str],
    *,
    source: str = "",
    include_subsections: bool = True,
) -> list[ExtractedSection]:
    """Extract multiple sections from markdown content.

    Args:
        content: Full markdown content.
        headings: List of heading texts to find.
        source: Source file path for attribution.
        include_subsections: Whether to include nested subsections.

    Returns:
        List of ExtractedSection objects found.
    """
    sections = []
    for heading in headings:
        section = extract_section(
            content, heading, source=source, include_subsections=include_subsections
        )
        if section:
            sections.append(section)
    return sections


def extract_sections_from_file(
    filepath: Path,
    headings: list[str],
    *,
    include_subsections: bool = True,
) -> list[ExtractedSection]:
    """Extract sections from a markdown file.

    Args:
        filepath: Path to the markdown file.
        headings: List of heading texts to find.
        include_subsections: Whether to include nested subsections.

    Returns:
        List of ExtractedSection objects found.
    """
    if not filepath.exists():
        return []

    try:
        content = filepath.read_text()
        return extract_sections(
            content,
            headings,
            source=filepath.name,
            include_subsections=include_subsections,
        )
    except Exception:
        return []


def extract_agents_context(worktree: Path) -> str:
    """Extract key context sections from AGENTS.md for implementation.

    Extracts:
    - Module Boundaries
    - NOT TO DO (Common LLM Mistakes)
    - Coding Patterns
    - Auto-Updated Learnings

    Args:
        worktree: Path to the repository worktree.

    Returns:
        Combined markdown string with relevant sections.
    """
    agents_path = worktree / "AGENTS.md"
    if not agents_path.exists():
        return ""

    sections = extract_sections_from_file(
        agents_path,
        [
            "Module Boundaries",
            "NOT TO DO",
            "Coding Patterns",
            "Auto-Updated Learnings",
            "Definition of Done",
        ],
        include_subsections=True,
    )

    if not sections:
        return ""

    parts = []
    for section in sections:
        parts.append(section.render(include_source=False))

    return "\n\n---\n\n".join(parts)


def extract_architecture_overview(worktree: Path) -> str:
    """Extract architecture overview from ARCHITECTURE.md.

    Extracts:
    - Overview
    - Component Architecture
    - Module Dependency Graph

    Args:
        worktree: Path to the repository worktree.

    Returns:
        Combined markdown string with relevant sections.
    """
    arch_path = worktree / "ARCHITECTURE.md"
    if not arch_path.exists():
        return ""

    sections = extract_sections_from_file(
        arch_path,
        [
            "Overview",
            "Component Architecture",
            "Module Dependency Graph",
        ],
        include_subsections=True,
    )

    if not sections:
        return ""

    parts = []
    for section in sections:
        parts.append(section.render(include_source=False))

    return "\n\n---\n\n".join(parts)


def extract_file_tree(worktree: Path, max_depth: int = 3) -> str:
    """Extract a simple file tree for decompose context.

    Args:
        worktree: Path to the repository worktree.
        max_depth: Maximum depth to traverse.

    Returns:
        Formatted file tree string.
    """
    src_path = worktree / "src"
    if not src_path.exists():
        src_path = worktree

    lines = ["```"]
    _build_tree(src_path, lines, prefix="", max_depth=max_depth, current_depth=0)
    lines.append("```")

    return "\n".join(lines)


def _build_tree(
    path: Path,
    lines: list[str],
    prefix: str,
    max_depth: int,
    current_depth: int,
) -> None:
    """Recursively build file tree lines.

    Args:
        path: Current directory path.
        lines: List to append lines to.
        prefix: Current prefix for indentation.
        max_depth: Maximum depth to traverse.
        current_depth: Current depth level.
    """
    if current_depth >= max_depth:
        return

    # Skip common non-essential directories
    skip_dirs = {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "dist",
        "build",
        "*.egg-info",
    }

    try:
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
    except PermissionError:
        return

    # Filter and limit entries
    dirs = [e for e in entries if e.is_dir() and e.name not in skip_dirs]
    files = [e for e in entries if e.is_file() and not e.name.startswith(".")]

    # Show directories
    for d in dirs[:10]:  # Limit to 10 dirs
        lines.append(f"{prefix}{d.name}/")
        _build_tree(d, lines, prefix + "  ", max_depth, current_depth + 1)

    # Show files (limited)
    for f in files[:15]:  # Limit to 15 files
        lines.append(f"{prefix}{f.name}")

    if len(dirs) > 10 or len(files) > 15:
        lines.append(f"{prefix}...")


def extract_focused_errors(log: str, max_errors: int = 10) -> str:
    """Extract focused error information from a log.

    Instead of passing the full log, extracts only the error lines
    with minimal context, focusing on actionable information.

    Args:
        log: Full log content.
        max_errors: Maximum number of errors to include.

    Returns:
        Focused error output.
    """
    if not log:
        return ""

    lines = log.split("\n")
    errors: list[str] = []
    seen_errors: set[str] = set()

    # Patterns that indicate error lines
    error_patterns = [
        r"error[:\[]",
        r"Error:",
        r"FAILED",
        r"E\s+\w+Error",
        r"^\s*>\s+",  # pytest assertion context
        r"AssertionError",
        r"ImportError",
        r"ModuleNotFoundError",
        r"SyntaxError",
        r"TypeError",
        r"ValueError",
        r"KeyError",
        r"AttributeError",
        r"ruff.*:\d+:\d+:",  # ruff format: file:line:col: ERROR
    ]
    combined_pattern = "|".join(f"({p})" for p in error_patterns)

    i = 0
    while i < len(lines) and len(errors) < max_errors:
        line = lines[i]

        if re.search(combined_pattern, line, re.IGNORECASE):
            # Dedupe similar errors
            error_key = re.sub(r"\d+", "N", line.strip()[:80])
            if error_key not in seen_errors:
                seen_errors.add(error_key)

                # Grab context: 1 line before, current, 2 lines after
                start = max(0, i - 1)
                end = min(len(lines), i + 3)
                context = "\n".join(lines[start:end])
                errors.append(context)

        i += 1

    if not errors:
        # Fallback: return last 30 lines if no errors found
        return "\n".join(lines[-30:])

    return "\n---\n".join(errors)


def extract_error_files(log: str) -> list[str]:
    """Extract list of files mentioned in error logs.

    Args:
        log: Log content.

    Returns:
        List of file paths mentioned in errors.
    """
    if not log:
        return []

    # Patterns for file paths in errors
    patterns = [
        r"([a-zA-Z_][\w/]*\.py):\d+",  # Python file with line number
        r"File \"([^\"]+\.py)\"",  # Python traceback format
        r"([a-zA-Z_][\w/]*\.(ts|js|tsx|jsx)):\d+",  # JS/TS files
    ]

    files: set[str] = set()
    for pattern in patterns:
        matches = re.findall(pattern, log)
        for match in matches:
            if isinstance(match, tuple):
                match = match[0]
            # Skip stdlib and site-packages
            if "site-packages" not in match and "/usr/" not in match:
                files.add(match)

    return sorted(files)
