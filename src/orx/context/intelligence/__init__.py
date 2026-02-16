"""Smart Context Intelligence — Tree-sitter-based repo analysis.

Provides:
- ``RepoParser``: extract definitions, references and imports via Tree-sitter.
- ``RepoGraph``: build a file-level dependency graph.
- ``SkeletonGenerator``: strip function bodies for compact context.
- ``SmartBundler``: assemble target files + neighbour skeletons + repo map.
"""

from orx.context.intelligence.bundle import SmartBundler
from orx.context.intelligence.graph import RepoGraph
from orx.context.intelligence.parser import RepoParser
from orx.context.intelligence.skeleton import SkeletonGenerator

__all__ = [
    "RepoGraph",
    "RepoParser",
    "SkeletonGenerator",
    "SmartBundler",
]
