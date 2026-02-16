"""Smart context bundler — assembles tiered context for LLM prompts.

Tiers:
1. **Target files** — full source code for files being modified.
2. **Neighbour skeletons** — signature-only versions of 1st-level imports.
3. **Repo map (tags)** — compact listing of all remaining definitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog

from orx.context.intelligence.graph import RepoGraph
from orx.context.intelligence.skeleton import SkeletonGenerator

logger = structlog.get_logger()


@dataclass
class BundleResult:
    """Result of smart context bundling.

    Attributes:
        repo_map: Tags/map for the whole repository (for plan stage).
        smart_context: Full tiered context (for implement stage).
        target_count: How many target files were included in full.
        neighbour_count: How many neighbour skeletons were included.
        remaining_count: How many files appear only in the repo map.
        total_chars: Total character count of smart_context.
    """

    repo_map: str
    smart_context: str
    target_count: int = 0
    neighbour_count: int = 0
    remaining_count: int = 0
    total_chars: int = 0


class SmartBundler:
    """Builds tiered context bundles using the repo graph.

    Usage:
        >>> graph = RepoGraph.build(worktree)
        >>> bundler = SmartBundler(worktree, graph)
        >>> result = bundler.bundle(target_files=["src/orx/config.py"])
    """

    def __init__(
        self,
        root: Path,
        graph: RepoGraph,
        *,
        max_target_chars: int = 50_000,
        max_skeleton_chars: int = 30_000,
        max_map_chars: int = 15_000,
    ) -> None:
        """Initialize the bundler.

        Args:
            root: Repository root directory.
            graph: Pre-built RepoGraph.
            max_target_chars: Character budget for full target files.
            max_skeleton_chars: Character budget for neighbour skeletons.
            max_map_chars: Character budget for the repo map.
        """
        self.root = root
        self.graph = graph
        self.skeleton_gen = SkeletonGenerator()
        self.max_target_chars = max_target_chars
        self.max_skeleton_chars = max_skeleton_chars
        self.max_map_chars = max_map_chars

    def build_repo_map(self, *, max_files: int = 200) -> str:
        """Build a repo-map (tags) for the entire repository.

        This is a compact listing of all files with their top-level
        definitions. Suitable for the plan stage.

        Args:
            max_files: Maximum number of files to include.

        Returns:
            Markdown-formatted repo map.
        """
        raw_map = self.graph.render_tags_map(max_files=max_files)
        if len(raw_map) > self.max_map_chars:
            raw_map = raw_map[: self.max_map_chars] + "\n... (truncated)"
        return raw_map

    def bundle(
        self,
        target_files: list[str],
        *,
        neighbour_depth: int = 1,
    ) -> BundleResult:
        """Build a smart context bundle for the implement stage.

        Args:
            target_files: Files being modified (shown in full).
            neighbour_depth: How many hops to follow for neighbours.

        Returns:
            BundleResult with tiered context.
        """
        neighbours, remaining = self.graph.get_relevant_context(
            target_files, depth=neighbour_depth
        )

        parts: list[str] = []

        # Tier 1: Full target files
        target_chars = 0
        targets_included = 0
        target_section: list[str] = []

        for fpath in sorted(target_files):
            if fpath not in self.graph.analyses:
                continue
            full_path = self.root / fpath
            if not full_path.exists():
                continue
            try:
                content = full_path.read_text()
            except OSError:
                continue

            if target_chars + len(content) > self.max_target_chars:
                break

            target_section.append(f"### {fpath} (full)\n```\n{content}\n```")
            target_chars += len(content)
            targets_included += 1

        if target_section:
            parts.append("## Target Files\n\n" + "\n\n".join(target_section))

        # Tier 2: Neighbour skeletons
        skeleton_chars = 0
        neighbours_included = 0
        skeleton_section: list[str] = []

        for fpath in sorted(neighbours):
            full_path = self.root / fpath
            if not full_path.exists():
                continue

            skeleton = self.skeleton_gen.generate(full_path)
            if skeleton is None:
                continue

            if skeleton_chars + len(skeleton) > self.max_skeleton_chars:
                break

            skeleton_section.append(f"### {fpath} (skeleton)\n```\n{skeleton}\n```")
            skeleton_chars += len(skeleton)
            neighbours_included += 1

        if skeleton_section:
            parts.append(
                "## Dependency Signatures (neighbours)\n\n"
                + "\n\n".join(skeleton_section)
            )

        # Tier 3: Repo map for remaining files
        remaining_included = 0
        if remaining:
            map_lines: list[str] = []
            chars = 0
            for fpath in sorted(remaining):
                analysis = self.graph.analyses.get(fpath)
                if not analysis:
                    continue

                entry_lines = [fpath]
                for d in analysis.definitions:
                    if d.parent is None:
                        entry_lines.append(f"  {d.signature}")

                entry = "\n".join(entry_lines)
                if chars + len(entry) > self.max_map_chars:
                    break

                map_lines.append(entry)
                chars += len(entry)
                remaining_included += 1

            if map_lines:
                parts.append(
                    "## Repo Map (remaining files)\n\n```\n"
                    + "\n".join(map_lines)
                    + "\n```"
                )

        smart_context = "\n\n".join(parts)

        return BundleResult(
            repo_map=self.build_repo_map(),
            smart_context=smart_context,
            target_count=targets_included,
            neighbour_count=neighbours_included,
            remaining_count=remaining_included,
            total_chars=len(smart_context),
        )
