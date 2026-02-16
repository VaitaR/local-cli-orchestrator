"""Repo dependency graph built from Tree-sitter analysis.

Builds a file-level import graph and provides methods
for querying neighbours and relevance.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from orx.context.intelligence.parser import FileAnalysis, RepoParser

logger = structlog.get_logger()


@dataclass
class RepoGraph:
    """File-level dependency graph.

    Nodes are relative file paths.
    Edges represent import relationships (A imports B).

    Attributes:
        analyses: Mapping from relative path to FileAnalysis.
        edges_out: Adjacency list — file -> set of files it imports.
        edges_in: Reverse adjacency — file -> set of files that import it.
    """

    analyses: dict[str, FileAnalysis] = field(default_factory=dict)
    edges_out: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    edges_in: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    @classmethod
    def build(
        cls,
        root: Path,
        *,
        max_files: int = 500,
    ) -> RepoGraph:
        """Build a dependency graph from a directory.

        Args:
            root: Root directory to scan.
            max_files: Maximum number of files to parse.

        Returns:
            Populated RepoGraph.
        """
        parser = RepoParser()
        analyses = parser.parse_directory(root, max_files=max_files)

        graph = cls()
        for analysis in analyses:
            graph.analyses[analysis.path] = analysis

        # Build edge index
        graph._resolve_imports(root)
        return graph

    def _resolve_imports(self, root: Path) -> None:
        """Resolve imports into file-level edges."""
        # Build module -> file path lookup for Python
        module_to_file: dict[str, str] = {}
        for fpath, analysis in self.analyses.items():
            if analysis.language == "python":
                # Convert path to module: src/orx/config.py -> orx.config
                module = self._path_to_module(fpath)
                if module:
                    module_to_file[module] = fpath

        for fpath, analysis in self.analyses.items():
            for imp in analysis.imports:
                resolved = self._resolve_single_import(
                    fpath,
                    imp.module,
                    is_relative=imp.is_relative,
                    language=analysis.language,
                    module_to_file=module_to_file,
                    root=root,
                )
                if resolved and resolved != fpath and resolved in self.analyses:
                    self.edges_out[fpath].add(resolved)
                    self.edges_in[resolved].add(fpath)

    @staticmethod
    def _path_to_module(fpath: str) -> str | None:
        """Convert a file path to a Python module path.

        Strips src/ prefix and .py suffix. Returns None for __init__.py or
        non-Python files.
        """
        p = Path(fpath)
        if p.suffix != ".py":
            return None

        parts = list(p.parts)
        # Strip "src/" prefix if present
        if parts and parts[0] == "src":
            parts = parts[1:]

        if parts and parts[-1] == "__init__.py":
            # Package: orx/config/__init__.py -> orx.config
            parts = parts[:-1]
        else:
            # Module: orx/config.py -> orx.config
            parts[-1] = parts[-1].removesuffix(".py")

        return ".".join(parts) if parts else None

    def _resolve_single_import(
        self,
        source_file: str,
        module: str,
        *,
        is_relative: bool,
        language: str,
        module_to_file: dict[str, str],
        root: Path,
    ) -> str | None:
        """Resolve a single import to a file path."""
        if language == "python":
            return self._resolve_python_import(
                source_file, module, is_relative=is_relative, module_to_file=module_to_file
            )
        return self._resolve_js_import(source_file, module, root=root)

    @staticmethod
    def _resolve_python_import(
        source_file: str,
        module: str,
        *,
        is_relative: bool,
        module_to_file: dict[str, str],
    ) -> str | None:
        """Resolve a Python import to a file path."""
        if is_relative:
            # Relative import: resolve from current file's package
            source_dir = str(Path(source_file).parent)
            # Strip "src/" prefix for module resolution
            if source_dir.startswith("src/"):
                pkg = source_dir[4:].replace("/", ".")
            else:
                pkg = source_dir.replace("/", ".")
            full_module = f"{pkg}.{module}" if module else pkg
        else:
            full_module = module

        # Try exact match first
        if full_module in module_to_file:
            return module_to_file[full_module]

        # Try parent module (from orx.config import OrxConfig -> orx.config)
        parts = full_module.split(".")
        for i in range(len(parts), 0, -1):
            candidate = ".".join(parts[:i])
            if candidate in module_to_file:
                return module_to_file[candidate]

        return None

    @staticmethod
    def _resolve_js_import(
        source_file: str,
        module: str,
        *,
        root: Path,
    ) -> str | None:
        """Resolve a JS/TS import to a file path."""
        if not module.startswith("."):
            return None  # External package

        source_dir = Path(source_file).parent
        target = source_dir / module

        # Try common extensions
        for ext in (".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.js"):
            candidate = str(target) + ext
            if (root / candidate).exists():
                return candidate

        return None

    def get_neighbours(self, file_path: str, *, depth: int = 1) -> set[str]:
        """Get neighbouring files (imports and importers) up to a given depth.

        Args:
            file_path: Relative file path.
            depth: How many hops to follow.

        Returns:
            Set of neighbouring file paths (excluding the file itself).
        """
        visited: set[str] = {file_path}
        frontier = {file_path}

        for _ in range(depth):
            next_frontier: set[str] = set()
            for f in frontier:
                next_frontier |= self.edges_out.get(f, set())
                next_frontier |= self.edges_in.get(f, set())
            next_frontier -= visited
            visited |= next_frontier
            frontier = next_frontier

        visited.discard(file_path)
        return visited

    def get_relevant_context(
        self,
        target_files: list[str],
        *,
        depth: int = 1,
    ) -> tuple[set[str], set[str]]:
        """Get the set of relevant files for a task.

        Args:
            target_files: Primary files being modified.
            depth: How many hops to follow.

        Returns:
            Tuple of (neighbour_files, remaining_files).
            neighbour_files: 1st-level neighbours (files that import or are imported by targets).
            remaining_files: All other files in the graph.
        """
        target_set = set(target_files) & set(self.analyses.keys())

        neighbours: set[str] = set()
        for f in target_set:
            neighbours |= self.get_neighbours(f, depth=depth)
        neighbours -= target_set

        all_files = set(self.analyses.keys())
        remaining = all_files - target_set - neighbours

        return neighbours, remaining

    def render_tags_map(self, *, max_files: int = 200) -> str:
        """Render a compact tags/map of the entire repository.

        Similar to aider's repo-map: shows file paths with their
        top-level definitions (classes and functions).

        Args:
            max_files: Maximum number of files to include.

        Returns:
            Markdown-formatted repo map string.
        """
        lines: list[str] = []
        sorted_files = sorted(self.analyses.keys())[:max_files]

        for fpath in sorted_files:
            analysis = self.analyses[fpath]
            defs = analysis.definitions

            if not defs:
                lines.append(fpath)
                continue

            lines.append(fpath)
            for d in defs:
                indent = "  " if d.parent is None else "    "
                lines.append(f"{indent}{d.signature}")

        return "\n".join(lines)
