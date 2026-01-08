"""Context block definitions for repo context pack."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class ContextPriority(IntEnum):
    """Priority levels for context blocks (higher = more important)."""

    VERIFY_COMMANDS = 100  # Most important - what gates will run
    PYTHON_CORE = 80  # ruff/mypy/pytest settings
    TS_CORE = 75  # tsconfig/scripts
    LAYOUT = 50  # Project layout hints
    FORMATTER = 30  # Formatter settings (lower priority)
    EXTRAS = 10  # Pre-commit, misc hints


@dataclass
class ContextBlock:
    """A unit of context content with metadata for packing.

    Attributes:
        priority: Priority level (higher = more important).
        title: Section heading for the block.
        body: Content lines (facts, snippets, etc.).
        sources: Source-of-truth file paths.
        estimated_chars: Approximate character count (calculated if not set).
        category: Category for grouping (e.g., "python", "typescript", "gates").
    """

    priority: ContextPriority | int
    title: str
    body: str
    sources: list[str] = field(default_factory=list)
    estimated_chars: int = 0
    category: str = "general"

    def __post_init__(self) -> None:
        """Calculate estimated_chars if not provided."""
        if self.estimated_chars == 0:
            self.estimated_chars = len(self.title) + len(self.body) + sum(len(s) for s in self.sources) + 50

    def render(self, *, include_sources: bool = True) -> str:
        """Render the block as markdown.

        Args:
            include_sources: Whether to include source-of-truth paths.

        Returns:
            Markdown string representation.
        """
        lines = [f"### {self.title}", "", self.body]

        if include_sources and self.sources:
            lines.append("")
            lines.append(f"_Source of truth: {', '.join(self.sources)}_")

        return "\n".join(lines)

    def render_compact(self, max_lines: int = 3) -> str:
        """Render a compact version for when space is limited.

        Args:
            max_lines: Maximum lines of body to include.

        Returns:
            Compact markdown string.
        """
        body_lines = self.body.strip().split("\n")
        if len(body_lines) > max_lines:
            body = "\n".join(body_lines[:max_lines]) + "\n..."
        else:
            body = self.body

        lines = [f"### {self.title}", "", body]
        if self.sources:
            lines.append(f"_({', '.join(self.sources)})_")

        return "\n".join(lines)


def merge_blocks(blocks: list[ContextBlock], title: str, category: str) -> ContextBlock:
    """Merge multiple blocks into one.

    Args:
        blocks: Blocks to merge.
        title: Title for the merged block.
        category: Category for the merged block.

    Returns:
        A single merged ContextBlock.
    """
    if not blocks:
        return ContextBlock(
            priority=ContextPriority.EXTRAS,
            title=title,
            body="",
            category=category,
        )

    # Use highest priority
    priority = max(b.priority for b in blocks)
    sources = []
    body_parts = []

    for block in blocks:
        body_parts.append(f"**{block.title}**\n{block.body}")
        sources.extend(block.sources)

    return ContextBlock(
        priority=priority,
        title=title,
        body="\n\n".join(body_parts),
        sources=list(dict.fromkeys(sources)),  # Dedupe preserving order
        category=category,
    )
