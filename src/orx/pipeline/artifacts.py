"""Artifact storage for pipeline execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
import yaml

from orx.paths import RunPaths
from orx.pipeline.constants import MAX_CONTEXT_BLOCK_SIZE

logger = structlog.get_logger()


@dataclass
class ArtifactMeta:
    """Metadata for an artifact."""

    key: str
    created_at: datetime
    size_bytes: int
    source_node: str | None = None
    content_type: str = "text"


@dataclass
class ArtifactStore:
    """Storage for pipeline artifacts.

    Provides a key-value interface for storing and retrieving artifacts
    with persistence to disk and lazy loading.

    Attributes:
        paths: RunPaths instance for file locations.
    """

    paths: RunPaths
    _cache: dict[str, Any] = field(default_factory=dict)
    _metadata: dict[str, ArtifactMeta] = field(default_factory=dict)

    # Mapping of artifact keys to file paths (relative to run_dir)
    KEY_TO_PATH: dict[str, str] = field(
        default_factory=lambda: {
            "task": "context/task.md",
            "plan": "context/plan.md",
            "spec": "context/spec.md",
            "backlog": "context/backlog.yaml",
            "repo_map": "context/project_map.md",
            "tooling_snapshot": "context/tooling_snapshot.md",
            "verify_commands": "context/verify_commands.md",
            "patch_diff": "artifacts/patch.diff",
            "review": "artifacts/review.md",
            "pr_body": "artifacts/pr_body.md",
            "implementation_report": "artifacts/implementation_report.md",
        }
    )

    def get(self, key: str) -> Any:
        """Get an artifact by key.

        Args:
            key: Artifact key.

        Returns:
            Artifact value, or None if not found.
        """
        # Check cache first
        if key in self._cache:
            return self._cache[key]

        # Try to load from disk
        value = self._load_from_disk(key)
        if value is not None:
            self._cache[key] = value

        return value

    def set(
        self,
        key: str,
        value: Any,
        *,
        persist: bool = True,
        source_node: str | None = None,
    ) -> None:
        """Set an artifact value.

        Args:
            key: Artifact key.
            value: Artifact value.
            persist: Whether to persist to disk.
            source_node: Node that produced this artifact.

        Raises:
            ValueError: If artifact exceeds size limit.
        """
        # Check size limit
        serialized = self._serialize(key, value)
        size = len(serialized.encode() if isinstance(serialized, str) else serialized)
        if size > MAX_CONTEXT_BLOCK_SIZE:
            msg = f"Artifact '{key}' exceeds size limit ({size} > {MAX_CONTEXT_BLOCK_SIZE})"
            raise ValueError(msg)

        # Store in cache
        self._cache[key] = value
        self._metadata[key] = ArtifactMeta(
            key=key,
            created_at=datetime.now(UTC),
            size_bytes=size,
            source_node=source_node,
            content_type="yaml" if key == "backlog" else "text",
        )

        # Persist to disk
        if persist:
            self._persist_to_disk(key, value)

    def exists(self, key: str) -> bool:
        """Check if an artifact exists.

        Args:
            key: Artifact key.

        Returns:
            True if artifact exists in cache or on disk.
        """
        if key in self._cache:
            return True
        path = self._disk_path(key)
        return path.exists() if path else False

    def keys(self) -> list[str]:
        """Get list of all artifact keys.

        Returns:
            List of keys for artifacts in cache and on disk.
        """
        keys = set(self._cache.keys())

        # Add keys from disk
        for key, rel_path in self.KEY_TO_PATH.items():
            path = self.paths.run_dir / rel_path
            if path.exists():
                keys.add(key)

        return sorted(keys)

    def get_metadata(self, key: str) -> ArtifactMeta | None:
        """Get metadata for an artifact.

        Args:
            key: Artifact key.

        Returns:
            ArtifactMeta or None.
        """
        return self._metadata.get(key)

    def clear_cache(self) -> None:
        """Clear the in-memory cache."""
        self._cache.clear()

    def _disk_path(self, key: str) -> Path | None:
        """Get the disk path for an artifact key.

        Args:
            key: Artifact key.

        Returns:
            Path to the file, or None if not mapped.
        """
        rel_path = self.KEY_TO_PATH.get(key)
        if rel_path:
            return self.paths.run_dir / rel_path

        # For unmapped keys, use artifacts directory
        return self.paths.artifacts_dir / f"{key}.md"

    def _load_from_disk(self, key: str) -> Any:
        """Load an artifact from disk.

        Args:
            key: Artifact key.

        Returns:
            Loaded value or None.
        """
        path = self._disk_path(key)
        if not path or not path.exists():
            return None

        try:
            content = path.read_text()

            # Parse YAML for backlog
            if key == "backlog":
                from orx.context.backlog import Backlog

                return Backlog.from_yaml(content)

            return content
        except Exception as e:
            logger.warning("Failed to load artifact from disk", key=key, error=str(e))
            return None

    def _persist_to_disk(self, key: str, value: Any) -> None:
        """Persist an artifact to disk.

        Args:
            key: Artifact key.
            value: Artifact value.
        """
        path = self._disk_path(key)
        if not path:
            return

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            serialized = self._serialize(key, value)
            path.write_text(serialized)
            logger.debug("Persisted artifact", key=key, path=str(path))
        except Exception as e:
            logger.warning("Failed to persist artifact", key=key, error=str(e))

    def _serialize(self, key: str, value: Any) -> str:
        """Serialize an artifact value.

        Args:
            key: Artifact key.
            value: Artifact value.

        Returns:
            Serialized string.
        """
        if key == "backlog":
            # Backlog has its own serialization
            if hasattr(value, "to_yaml"):
                return value.to_yaml()
            return yaml.dump(value, default_flow_style=False)

        if isinstance(value, str):
            return value

        if hasattr(value, "model_dump"):
            return yaml.dump(value.model_dump(mode="json"), default_flow_style=False)

        return str(value)
