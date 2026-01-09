"""Project documentation extractor.

Extracts key project documentation files like AGENTS.md and ARCHITECTURE.md
to provide context about coding patterns, architecture, and project guidelines.

These files are passed in FULL to agents - the knowledge_update stage is
responsible for keeping them concise and high-density.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from orx.context.repo_context.blocks import ContextBlock, ContextPriority

logger = structlog.get_logger()


class DocsExtractor:
    """Extracts project documentation for agent context.

    Files are passed in full without truncation. The knowledge_update stage
    is responsible for maintaining these files at an appropriate size.
    """

    def __init__(self, worktree: Path) -> None:
        """Initialize the extractor.

        Args:
            worktree: Path to the repository worktree.
        """
        self.worktree = worktree

    def extract_all(self) -> list[ContextBlock]:
        """Extract all project documentation blocks.

        Returns:
            List of context blocks for project documentation.
        """
        blocks: list[ContextBlock] = []

        # AGENTS.md - coding patterns, gotchas, module boundaries
        agents_block = self._extract_agents_md()
        if agents_block:
            blocks.append(agents_block)

        # ARCHITECTURE.md - system architecture overview
        arch_block = self._extract_architecture_md()
        if arch_block:
            blocks.append(arch_block)

        return blocks

    def _extract_agents_md(self) -> ContextBlock | None:
        """Extract AGENTS.md content (full, no truncation).

        Returns:
            Context block with AGENTS.md content or None.
        """
        agents_path = self.worktree / "AGENTS.md"
        if not agents_path.exists():
            return None

        try:
            content = agents_path.read_text()

            return ContextBlock(
                priority=ContextPriority.LAYOUT + 20,  # High priority for patterns
                title="Agent Guidelines (AGENTS.md)",
                body=content,
                sources=["AGENTS.md"],
                category="docs",
            )

        except Exception as e:
            logger.warning("Failed to extract AGENTS.md", error=str(e))
            return None

    def _extract_architecture_md(self) -> ContextBlock | None:
        """Extract ARCHITECTURE.md content (full, no truncation).

        Returns:
            Context block with ARCHITECTURE.md content or None.
        """
        arch_path = self.worktree / "ARCHITECTURE.md"
        if not arch_path.exists():
            return None

        try:
            content = arch_path.read_text()

            return ContextBlock(
                priority=ContextPriority.LAYOUT + 10,  # High priority for architecture
                title="System Architecture (ARCHITECTURE.md)",
                body=content,
                sources=["ARCHITECTURE.md"],
                category="docs",
            )

        except Exception as e:
            logger.warning("Failed to extract ARCHITECTURE.md", error=str(e))
            return None
