"""Context builder for assembling node inputs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from orx.context.sections import (
    extract_agents_context,
    extract_architecture_overview,
)
from orx.context.snippets import build_file_snippets
from orx.pipeline.artifacts import ArtifactStore
from orx.pipeline.constants import AUTO_EXTRACT_CONTEXTS

if TYPE_CHECKING:
    from orx.context.backlog import WorkItem
    from orx.pipeline.definition import NodeDefinition

logger = structlog.get_logger()


class MissingContextError(Exception):
    """Raised when a required context block is not available."""

    pass


class ContextBuilder:
    """Builds context dictionaries for node execution.

    Assembles input context for nodes by:
    1. Looking up artifacts in the store
    2. Auto-extracting context from the worktree
    3. Building runtime context (file snippets, current item)

    Attributes:
        store: ArtifactStore for artifact lookup.
        worktree: Path to the git worktree.
    """

    def __init__(self, store: ArtifactStore, worktree: Path):
        """Initialize the context builder.

        Args:
            store: ArtifactStore instance.
            worktree: Path to the worktree.
        """
        self._store = store
        self._worktree = worktree
        self._extractors = self._register_extractors()

    def build_for_node(
        self,
        node: NodeDefinition,
        *,
        current_item: WorkItem | None = None,
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build context dictionary for a node.

        Args:
            node: Node definition with input requirements.
            current_item: Current work item (for map nodes).
            extra_context: Additional context to merge.

        Returns:
            Dictionary of context values keyed by input name.

        Raises:
            MissingContextError: If a required context is not available.
        """
        context: dict[str, Any] = {}

        for key in node.inputs:
            value = self._resolve_context(key, current_item=current_item)
            if value is None and key not in AUTO_EXTRACT_CONTEXTS:
                # Allow None for auto-extracted contexts (they may not exist)
                msg = f"Context '{key}' not available for node '{node.id}'"
                raise MissingContextError(msg)
            if value is not None:
                context[key] = value

        # Merge extra context
        if extra_context:
            context.update(extra_context)

        return context

    def extract_default_context(self, keys: list[str]) -> None:
        """Pre-extract default context blocks.

        Args:
            keys: List of context keys to extract.
        """
        for key in keys:
            if key in self._extractors and not self._store.exists(key):
                try:
                    value = self._extractors[key]()
                    if value:
                        self._store.set(key, value, source_node="auto_extract")
                        logger.debug("Auto-extracted context", key=key)
                except Exception as e:
                    logger.warning(
                        "Failed to auto-extract context", key=key, error=str(e)
                    )

    def _resolve_context(
        self,
        key: str,
        *,
        current_item: WorkItem | None = None,
    ) -> Any:
        """Resolve a single context key.

        Args:
            key: Context key to resolve.
            current_item: Current work item for item-specific context.

        Returns:
            Context value or None.
        """
        # Handle special runtime contexts
        if key == "current_item":
            return current_item

        if key == "file_snippets" and current_item:
            return build_file_snippets(
                worktree=self._worktree,
                files=current_item.files_hint,
                max_lines=120,
                max_files=8,
            )

        # Check store first
        if self._store.exists(key):
            return self._store.get(key)

        # Try auto-extraction
        if key in self._extractors:
            try:
                value = self._extractors[key]()
                if value:
                    self._store.set(key, value, source_node="auto_extract")
                return value
            except Exception as e:
                logger.warning("Failed to extract context", key=key, error=str(e))
                return None

        return None

    def _register_extractors(self) -> dict[str, Callable[[], Any]]:
        """Register auto-extraction functions for context keys.

        Returns:
            Dictionary mapping context keys to extractor functions.
        """
        return {
            "repo_map": self._extract_repo_map,
            "tooling_snapshot": self._extract_tooling_snapshot,
            "verify_commands": self._extract_verify_commands,
            "agents_context": lambda: extract_agents_context(self._worktree),
            "architecture": lambda: extract_architecture_overview(self._worktree),
        }

    def _extract_repo_map(self) -> str | None:
        """Extract repository map."""
        from orx.context.repo_context import RepoContextBuilder

        try:
            builder = RepoContextBuilder(worktree=self._worktree, gates=[])
            result = builder.build()
            return result.project_map
        except Exception as e:
            logger.warning("Failed to extract repo_map", error=str(e))
            return None

    def _extract_tooling_snapshot(self) -> str | None:
        """Extract tooling snapshot."""
        from orx.context.repo_context import RepoContextBuilder

        try:
            builder = RepoContextBuilder(worktree=self._worktree, gates=[])
            result = builder.build()
            return result.tooling_snapshot
        except Exception as e:
            logger.warning("Failed to extract tooling_snapshot", error=str(e))
            return None

    def _extract_verify_commands(self) -> str | None:
        """Extract verify commands."""
        from orx.context.repo_context import RepoContextBuilder

        try:
            builder = RepoContextBuilder(worktree=self._worktree, gates=[])
            result = builder.build()
            return result.verify_commands
        except Exception as e:
            logger.warning("Failed to extract verify_commands", error=str(e))
            return None
