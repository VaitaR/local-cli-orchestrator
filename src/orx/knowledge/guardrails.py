"""Guardrails for knowledge file updates."""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog

from orx.config import KnowledgeConfig
from orx.exceptions import GuardrailError

logger = structlog.get_logger()


@dataclass
class MarkerBounds:
    """Start and end positions of a marker block in a file.

    Attributes:
        start_line: Line number where marker block starts (0-indexed).
        end_line: Line number where marker block ends (0-indexed).
        content: Content between the markers.
    """

    start_line: int
    end_line: int
    content: str

    @property
    def line_count(self) -> int:
        """Number of lines in the marker block."""
        return self.end_line - self.start_line - 1


@dataclass
class ChangeStats:
    """Statistics about a proposed change.

    Attributes:
        added_lines: Number of lines added.
        deleted_lines: Number of lines deleted.
        changed_lines: Total lines changed (added + deleted).
    """

    added_lines: int
    deleted_lines: int

    @property
    def changed_lines(self) -> int:
        """Total lines changed."""
        return self.added_lines + self.deleted_lines


class KnowledgeGuardrails:
    """Guardrails for knowledge file updates.

    Enforces:
    - Allowlist of files that can be modified
    - Marker-based scoped updates
    - Limits on change size

    Example:
        >>> config = KnowledgeConfig()
        >>> guardrails = KnowledgeGuardrails(config)
        >>> bounds = guardrails.find_marker_bounds(content, "agents")
        >>> guardrails.validate_change_limits(old_content, new_content)
    """

    def __init__(self, config: KnowledgeConfig) -> None:
        """Initialize knowledge guardrails.

        Args:
            config: Knowledge configuration.
        """
        self.config = config
        self.markers = config.markers
        self.limits = config.limits

    def is_file_allowed(self, filename: str) -> bool:
        """Check if a file is in the allowlist.

        Args:
            filename: Name of the file to check.

        Returns:
            True if the file can be modified.
        """
        return filename in self.config.allowlist

    def find_marker_bounds(
        self,
        content: str,
        marker_type: str,
    ) -> MarkerBounds | None:
        """Find the bounds of a marker block in content.

        Args:
            content: File content to search.
            marker_type: Type of marker ("agents" or "arch").

        Returns:
            MarkerBounds if found, None otherwise.
        """
        if marker_type == "agents":
            start_marker = self.markers.agents_start
            end_marker = self.markers.agents_end
        elif marker_type == "arch":
            start_marker = self.markers.arch_start
            end_marker = self.markers.arch_end
        else:
            msg = f"Unknown marker type: {marker_type}"
            raise ValueError(msg)

        lines = content.split("\n")
        start_line = None
        end_line = None

        for i, line in enumerate(lines):
            if start_marker in line:
                start_line = i
            elif end_marker in line and start_line is not None:
                end_line = i
                break

        if start_line is None or end_line is None:
            return None

        # Extract content between markers
        marker_content = "\n".join(lines[start_line + 1 : end_line])

        return MarkerBounds(
            start_line=start_line,
            end_line=end_line,
            content=marker_content,
        )

    def replace_marker_content(
        self,
        original: str,
        marker_type: str,
        new_content: str,
    ) -> str:
        """Replace content within marker bounds.

        Args:
            original: Original file content.
            marker_type: Type of marker ("agents" or "arch").
            new_content: New content to place between markers.

        Returns:
            Updated file content.

        Raises:
            GuardrailError: If markers not found.
        """
        bounds = self.find_marker_bounds(original, marker_type)

        if bounds is None:
            msg = f"Markers for '{marker_type}' not found in content"
            raise GuardrailError(msg, rule="markers_not_found", violated_files=[])

        lines = original.split("\n")

        # Reconstruct: before markers + start marker + new content + end marker + after
        before = lines[: bounds.start_line + 1]  # Include start marker
        after = lines[bounds.end_line :]  # Include end marker

        # Build new content
        new_lines = new_content.strip().split("\n") if new_content.strip() else []

        result_lines = before + new_lines + after
        return "\n".join(result_lines)

    def validate_change_limits(
        self,
        old_content: str,
        new_content: str,
        filename: str,
    ) -> ChangeStats:
        """Validate that a change is within limits.

        Args:
            old_content: Original file content.
            new_content: Proposed new content.
            filename: Name of the file being changed.

        Returns:
            ChangeStats for the change.

        Raises:
            GuardrailError: If change exceeds limits.
        """
        old_lines = old_content.split("\n")
        new_lines = new_content.split("\n")

        # Simple line-based diff calculation
        added = max(0, len(new_lines) - len(old_lines))
        deleted = max(0, len(old_lines) - len(new_lines))

        # More accurate: count actual different lines
        old_set = set(old_lines)
        new_set = set(new_lines)
        added = len(new_set - old_set)
        deleted = len(old_set - new_set)

        stats = ChangeStats(added_lines=added, deleted_lines=deleted)

        log = logger.bind(
            filename=filename,
            added=stats.added_lines,
            deleted=stats.deleted_lines,
            total=stats.changed_lines,
        )

        # Check per-file limit
        if stats.changed_lines > self.limits.max_changed_lines_per_file:
            log.error("Change exceeds per-file limit")
            msg = (
                f"Change to {filename} exceeds limit: "
                f"{stats.changed_lines} lines changed "
                f"(max: {self.limits.max_changed_lines_per_file})"
            )
            raise GuardrailError(
                msg, rule="max_changed_lines_per_file", violated_files=[filename]
            )

        # Check deleted lines limit
        if stats.deleted_lines > self.limits.max_deleted_lines:
            log.error("Too many lines deleted")
            msg = (
                f"Change to {filename} deletes too many lines: "
                f"{stats.deleted_lines} deleted (max: {self.limits.max_deleted_lines})"
            )
            raise GuardrailError(
                msg, rule="max_deleted_lines", violated_files=[filename]
            )

        log.debug("Change within limits")
        return stats

    def validate_markers_present(self, content: str, marker_type: str) -> bool:
        """Check if markers are present in content.

        Args:
            content: File content.
            marker_type: Type of marker ("agents" or "arch").

        Returns:
            True if both start and end markers are found.
        """
        return self.find_marker_bounds(content, marker_type) is not None

    def create_markers(self, marker_type: str) -> str:
        """Create a new marker block with empty content.

        Args:
            marker_type: Type of marker ("agents" or "arch").

        Returns:
            String containing start marker, empty line, end marker.
        """
        if marker_type == "agents":
            return f"\n{self.markers.agents_start}\n\n{self.markers.agents_end}\n"
        elif marker_type == "arch":
            return f"\n{self.markers.arch_start}\n\n{self.markers.arch_end}\n"
        else:
            msg = f"Unknown marker type: {marker_type}"
            raise ValueError(msg)

    def should_update_architecture(self, changed_files: list[str]) -> bool:
        """Apply gatekeeping logic for architecture updates.

        Returns True only if changes affect:
        - Module structure (new directories)
        - Component interactions (new protocols/interfaces)
        - Data storage
        - Infrastructure
        - Public API contracts

        Args:
            changed_files: List of files changed in this run.

        Returns:
            True if architecture update is warranted.
        """
        if not self.config.architecture_gatekeeping:
            return True  # No gatekeeping, always update

        # Patterns that suggest architectural changes
        arch_patterns = [
            r"^src/orx/[^/]+\.py$",  # New top-level modules
            r"/protocol\.py$",
            r"/interfaces\.py$",
            r"/base\.py$",
            r"^src/orx/[^/]+/__init__\.py$",  # New packages
            r"requirements\.txt$",
            r"pyproject\.toml$",  # Dependency changes
            r"docker-compose",
            r"Dockerfile",
            r"\.github/workflows/",  # CI changes
        ]

        for file_path in changed_files:
            for pattern in arch_patterns:
                if re.search(pattern, file_path):
                    logger.info(
                        "Architecture update warranted",
                        file=file_path,
                        pattern=pattern,
                    )
                    return True

        logger.info("Architecture update not warranted by changed files")
        return False
