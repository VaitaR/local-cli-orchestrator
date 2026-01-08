"""Main Repo Context Builder - coordinates extraction and packing.

This is the primary entry point for building repo context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from orx.context.repo_context.blocks import ContextBlock, ContextPriority
from orx.context.repo_context.packer import pack_for_stage
from orx.context.repo_context.python_extractor import PythonExtractor
from orx.context.repo_context.ts_extractor import TypeScriptExtractor
from orx.context.repo_context.verify_commands import build_verify_commands

if TYPE_CHECKING:
    from orx.gates.base import Gate

logger = structlog.get_logger()


@dataclass
class RepoContextResult:
    """Result of repo context extraction.

    Attributes:
        project_map: Stack/profile markdown (for plan/spec).
        tooling_snapshot: Full tooling config markdown (for implement/fix).
        verify_commands: Gate commands markdown.
        all_blocks: All extracted context blocks.
        detected_stacks: Detected project types (e.g., ["python", "typescript"]).
    """

    project_map: str
    tooling_snapshot: str
    verify_commands: str
    all_blocks: list[ContextBlock] = field(default_factory=list)
    detected_stacks: list[str] = field(default_factory=list)


class RepoContextBuilder:
    """Builds repo context from a worktree.

    Coordinates extraction from Python and TypeScript projects,
    and packs the results within token budgets.

    Example:
        >>> builder = RepoContextBuilder(Path("/repo"), gates)
        >>> result = builder.build()
        >>> print(result.project_map)
    """

    def __init__(
        self,
        worktree: Path,
        gates: list[Gate] | None = None,
        *,
        profile_budget: int = 3000,
        full_budget: int = 11000,
    ) -> None:
        """Initialize the builder.

        Args:
            worktree: Path to the repository worktree.
            gates: List of gates that will run during VERIFY.
            profile_budget: Character budget for profile-only extraction.
            full_budget: Character budget for full extraction.
        """
        self.worktree = worktree
        self.gates = gates or []
        self.profile_budget = profile_budget
        self.full_budget = full_budget

        # Extractors
        self.python = PythonExtractor(worktree)
        self.typescript = TypeScriptExtractor(worktree)

    def build(self) -> RepoContextResult:
        """Build all repo context artifacts.

        Returns:
            RepoContextResult with all context artifacts.
        """
        log = logger.bind(worktree=str(self.worktree))
        log.info("Building repo context pack")

        # Collect all blocks
        all_blocks: list[ContextBlock] = []
        detected: list[str] = []

        # Python extraction
        if self.python.is_python_project():
            detected.append("python")
            python_blocks = self.python.extract_all()
            all_blocks.extend(python_blocks)
            log.debug("Python blocks extracted", count=len(python_blocks))

        # TypeScript extraction
        if self.typescript.is_ts_project():
            detected.append("typescript")
            ts_blocks = self.typescript.extract_all()
            all_blocks.extend(ts_blocks)
            log.debug("TypeScript blocks extracted", count=len(ts_blocks))

        # Verify commands
        verify_block = build_verify_commands(self.gates)
        if verify_block:
            all_blocks.append(verify_block)

        # Build project_map (profile only, for plan/spec)
        profile_blocks = self._filter_profile_blocks(all_blocks)
        project_map = pack_for_stage(profile_blocks, "plan", char_budget=self.profile_budget)

        # Build tooling_snapshot (full, for implement/fix)
        tooling_snapshot = pack_for_stage(all_blocks, "implement", char_budget=self.full_budget)

        # Build verify_commands separately for easy access
        verify_commands = verify_block.render(include_sources=False) if verify_block else ""

        log.info(
            "Repo context pack built",
            stacks=detected,
            block_count=len(all_blocks),
            profile_size=len(project_map),
            tooling_size=len(tooling_snapshot),
        )

        return RepoContextResult(
            project_map=project_map,
            tooling_snapshot=tooling_snapshot,
            verify_commands=verify_commands,
            all_blocks=all_blocks,
            detected_stacks=detected,
        )

    def build_profile_only(self) -> str:
        """Build only the project profile (for plan/spec stages).

        Returns:
            Profile markdown content.
        """
        blocks: list[ContextBlock] = []

        if self.python.is_python_project():
            profile = self.python.extract_profile_only()
            if profile:
                blocks.append(profile)

        if self.typescript.is_ts_project():
            profile = self.typescript.extract_profile_only()
            if profile:
                blocks.append(profile)

        return pack_for_stage(blocks, "plan", char_budget=self.profile_budget)

    def build_for_implement(self) -> str:
        """Build full context for implement/fix stages.

        Returns:
            Full tooling context markdown.
        """
        result = self.build()
        return result.tooling_snapshot

    def _filter_profile_blocks(self, blocks: list[ContextBlock]) -> list[ContextBlock]:
        """Filter blocks to profile-only (stack/layout info).

        Args:
            blocks: All context blocks.

        Returns:
            Blocks suitable for profile-only display.
        """
        return [
            b for b in blocks
            if b.priority <= ContextPriority.LAYOUT or "Profile" in b.title
        ]


def build_repo_context(
    worktree: Path,
    gates: list[Gate] | None = None,
) -> RepoContextResult:
    """Convenience function to build repo context.

    Args:
        worktree: Path to the repository.
        gates: List of gates for VERIFY.

    Returns:
        RepoContextResult with all artifacts.
    """
    builder = RepoContextBuilder(worktree, gates)
    return builder.build()
