"""Project documentation extractor.

Extracts key project documentation files like AGENTS.md and ARCHITECTURE.md
to provide context about coding patterns, architecture, and project guidelines.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from orx.context.repo_context.blocks import ContextBlock, ContextPriority

logger = structlog.get_logger()


class DocsExtractor:
    """Extracts project documentation for agent context."""

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
        """Extract AGENTS.md content.

        Returns:
            Context block with AGENTS.md content or None.
        """
        agents_path = self.worktree / "AGENTS.md"
        if not agents_path.exists():
            return None

        try:
            content = agents_path.read_text()

            # Extract the auto-updated learnings section if present
            lines = content.split("\n")
            learnings_start = None
            learnings_end = None

            for i, line in enumerate(lines):
                if "<!-- ORX:START AGENTS -->" in line:
                    learnings_start = i
                elif "<!-- ORX:END AGENTS -->" in line:
                    learnings_end = i + 1
                    break

            # If learnings section exists, extract it separately
            main_content = content
            learnings_content = ""

            if learnings_start is not None and learnings_end is not None:
                # Extract learnings
                learnings_lines = lines[learnings_start:learnings_end]
                learnings_content = "\n".join(learnings_lines)

                # Main content excludes learnings for brevity
                # We'll show learnings separately with higher priority
                main_lines = lines[:learnings_start] + lines[learnings_end:]
                main_content = "\n".join(main_lines).strip()

            # Limit main content to ~3000 chars for context efficiency
            if len(main_content) > 3000:
                main_content = main_content[:3000] + "\n\n_[Content truncated for brevity]_"

            # Build main AGENTS.md block
            body = f"**Coding guidelines and module boundaries from AGENTS.md:**\n\n{main_content}"

            blocks = []

            blocks.append(
                ContextBlock(
                    priority=ContextPriority.LAYOUT + 20,  # High priority for patterns
                    title="Agent Guidelines (AGENTS.md)",
                    body=body,
                    sources=["AGENTS.md"],
                    category="docs",
                )
            )

            # If learnings exist, add them as a separate high-priority block
            if learnings_content:
                blocks.append(
                    ContextBlock(
                        priority=ContextPriority.VERIFY_COMMANDS
                        - 5,  # Just below verify commands
                        title="Recent Learnings (AGENTS.md)",
                        body=f"**Auto-updated learnings from recent runs:**\n\n{learnings_content}",
                        sources=["AGENTS.md"],
                        category="docs",
                    )
                )

            # Return the main block (learnings will be added separately in extract_all)
            return blocks[0] if len(blocks) == 1 else blocks[0]

        except Exception as e:
            logger.warning("Failed to extract AGENTS.md", error=str(e))
            return None

    def _extract_architecture_md(self) -> ContextBlock | None:
        """Extract ARCHITECTURE.md content.

        Returns:
            Context block with ARCHITECTURE.md content or None.
        """
        arch_path = self.worktree / "ARCHITECTURE.md"
        if not arch_path.exists():
            return None

        try:
            content = arch_path.read_text()

            # Limit to ~2500 chars for context efficiency
            if len(content) > 2500:
                content = content[:2500] + "\n\n_[Content truncated for brevity]_"

            body = f"**System architecture from ARCHITECTURE.md:**\n\n{content}"

            return ContextBlock(
                priority=ContextPriority.LAYOUT + 10,  # High priority for architecture
                title="System Architecture (ARCHITECTURE.md)",
                body=body,
                sources=["ARCHITECTURE.md"],
                category="docs",
            )

        except Exception as e:
            logger.warning("Failed to extract ARCHITECTURE.md", error=str(e))
            return None
