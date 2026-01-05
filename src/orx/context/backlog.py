"""Backlog schema and YAML parsing for work items."""

from __future__ import annotations

import math
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


def _strip_markdown_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text

    lines = stripped.splitlines()
    if not lines:
        return text

    fence = lines[0].strip()
    if not fence.startswith("```"):
        return text

    end_idx: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "```":
            end_idx = idx
            break

    if end_idx is None:
        return text

    inner = "\n".join(lines[1:end_idx]).strip()
    return inner


class WorkItemStatus(str, Enum):
    """Status of a work item."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkItem(BaseModel):
    """A single work item in the backlog.

    Attributes:
        id: Unique identifier for the work item (e.g., W001).
        title: Short title describing the work.
        objective: Clear objective of what needs to be done.
        acceptance: List of acceptance criteria.
        files_hint: Optional list of files likely to be modified.
        depends_on: List of work item IDs this depends on.
        status: Current status of the work item.
        attempts: Number of implementation attempts.
        notes: Additional notes (e.g., failure evidence).

    Example:
        >>> item = WorkItem(
        ...     id="W001",
        ...     title="Add helper function",
        ...     objective="Create a helper function for parsing",
        ...     acceptance=["Function exists", "Tests pass"],
        ... )
        >>> item.status
        <WorkItemStatus.TODO: 'todo'>
    """

    id: str = Field(..., pattern=r"^W\d{3}$")
    title: str = Field(..., min_length=1, max_length=200)
    objective: str = Field(..., min_length=1)
    acceptance: list[str] = Field(default_factory=list, min_length=1)
    files_hint: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    status: WorkItemStatus = Field(default=WorkItemStatus.TODO)
    attempts: int = Field(default=0, ge=0)
    notes: str = Field(default="")

    @field_validator("depends_on")
    @classmethod
    def validate_depends_on(cls, v: list[str]) -> list[str]:
        """Validate that dependencies are valid work item IDs."""
        import re

        pattern = re.compile(r"^W\d{3}$")
        for dep in v:
            if not pattern.match(dep):
                msg = f"Invalid dependency ID format: {dep}"
                raise ValueError(msg)
        return v

    def mark_in_progress(self) -> None:
        """Mark the work item as in progress."""
        self.status = WorkItemStatus.IN_PROGRESS

    def mark_done(self) -> None:
        """Mark the work item as done."""
        self.status = WorkItemStatus.DONE

    def mark_failed(self, notes: str = "") -> None:
        """Mark the work item as failed with optional notes."""
        self.status = WorkItemStatus.FAILED
        if notes:
            self.notes = notes

    def increment_attempts(self) -> None:
        """Increment the attempt counter."""
        self.attempts += 1


class Backlog(BaseModel):
    """The complete backlog of work items for a run.

    Attributes:
        run_id: The run ID this backlog belongs to.
        items: List of work items.

    Example:
        >>> backlog = Backlog(run_id="test_run", items=[])
        >>> backlog.add_item(WorkItem(
        ...     id="W001",
        ...     title="Test",
        ...     objective="Test objective",
        ...     acceptance=["Test passes"],
        ... ))
        >>> len(backlog.items)
        1
    """

    run_id: str = Field(..., min_length=1)
    items: list[WorkItem] = Field(default_factory=list)

    def add_item(self, item: WorkItem) -> None:
        """Add a work item to the backlog."""
        if any(existing.id == item.id for existing in self.items):
            msg = f"Work item with ID {item.id} already exists"
            raise ValueError(msg)
        self.items.append(item)

    def get_item(self, item_id: str) -> WorkItem | None:
        """Get a work item by ID."""
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def get_next_todo(self) -> WorkItem | None:
        """Get the next work item with status TODO.

        Returns:
            The next TODO item, or None if all items are done.
        """
        for item in self.items:
            if item.status == WorkItemStatus.TODO:
                # Check if dependencies are satisfied
                deps_satisfied = all(
                    self.get_item(dep_id) is not None
                    and self.get_item(dep_id).status == WorkItemStatus.DONE  # type: ignore[union-attr]
                    for dep_id in item.depends_on
                )
                if deps_satisfied:
                    return item
        return None

    def all_done(self) -> bool:
        """Check if all items are done."""
        return all(item.status == WorkItemStatus.DONE for item in self.items)

    def todo_count(self) -> int:
        """Count items that are still TODO."""
        return sum(1 for item in self.items if item.status == WorkItemStatus.TODO)

    def done_count(self) -> int:
        """Count items that are DONE."""
        return sum(1 for item in self.items if item.status == WorkItemStatus.DONE)

    def failed_count(self) -> int:
        """Count items that FAILED."""
        return sum(1 for item in self.items if item.status == WorkItemStatus.FAILED)

    def validate_dependencies(self) -> list[str]:
        """Validate that all dependencies reference existing items.

        Returns:
            List of error messages (empty if valid).
        """
        errors: list[str] = []
        item_ids = {item.id for item in self.items}
        for item in self.items:
            for dep_id in item.depends_on:
                if dep_id not in item_ids:
                    errors.append(f"Item {item.id} depends on unknown item {dep_id}")
                if dep_id == item.id:
                    errors.append(f"Item {item.id} depends on itself")
        return errors

    def detect_cycles(self) -> list[str]:
        """Detect circular dependencies in the backlog.

        Returns:
            List of cycle descriptions (empty if no cycles).
        """
        cycles: list[str] = []
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def dfs(item_id: str, path: list[str]) -> None:
            visited.add(item_id)
            rec_stack.add(item_id)
            item = self.get_item(item_id)
            if item:
                for dep_id in item.depends_on:
                    if dep_id not in visited:
                        dfs(dep_id, path + [dep_id])
                    elif dep_id in rec_stack:
                        cycle_path = path[path.index(dep_id) :] + [dep_id]
                        cycles.append(" -> ".join(cycle_path))
            rec_stack.discard(item_id)

        for item in self.items:
            if item.id not in visited:
                dfs(item.id, [item.id])

        return cycles

    def to_yaml(self) -> str:
        """Serialize the backlog to YAML.

        Returns:
            YAML string representation.
        """
        data = self.model_dump(mode="json")
        return yaml.dump(data, default_flow_style=False, sort_keys=False)

    def coalesce(self, max_items: int) -> "Backlog":
        """Coalesce work items to reduce total count.

        Args:
            max_items: Maximum number of items to keep.

        Returns:
            A new Backlog with merged items if needed.
        """
        if max_items < 1 or len(self.items) <= max_items:
            return self

        group_size = math.ceil(len(self.items) / max_items)
        groups = [
            self.items[i : i + group_size]
            for i in range(0, len(self.items), group_size)
        ]

        def unique(values: list[str]) -> list[str]:
            seen: set[str] = set()
            result: list[str] = []
            for value in values:
                if value not in seen:
                    result.append(value)
                    seen.add(value)
            return result

        id_to_group: dict[str, int] = {}
        for idx, group in enumerate(groups):
            for item in group:
                id_to_group[item.id] = idx

        group_ids = [f"W{idx + 1:03d}" for idx in range(len(groups))]
        new_items: list[WorkItem] = []

        for idx, group in enumerate(groups):
            merged_ids = [item.id for item in group]
            title = group[0].title
            objective = group[0].objective
            notes = group[0].notes
            acceptance: list[str] = []

            if len(group) > 1:
                title = f"Batch {idx + 1}: {group[0].title} + {len(group) - 1} more"
                objective = "; ".join(item.objective for item in group)
                notes = f"Merged from {', '.join(merged_ids)}"

            for item in group:
                for criterion in item.acceptance:
                    if len(group) > 1:
                        entry = f"{item.id}: {criterion}"
                    else:
                        entry = criterion
                    acceptance.append(entry)

            acceptance = unique(acceptance)
            if not acceptance:
                acceptance = [f"Complete {title}"]

            files_hint = unique([path for item in group for path in item.files_hint])

            dep_targets: list[str] = []
            for item in group:
                for dep_id in item.depends_on:
                    dep_group = id_to_group.get(dep_id)
                    if dep_group is None or dep_group == idx:
                        continue
                    dep_targets.append(group_ids[dep_group])

            new_items.append(
                WorkItem(
                    id=group_ids[idx],
                    title=title,
                    objective=objective,
                    acceptance=acceptance,
                    files_hint=files_hint,
                    depends_on=unique(dep_targets),
                    status=WorkItemStatus.TODO,
                    attempts=0,
                    notes=notes,
                )
            )

        return Backlog(run_id=self.run_id, items=new_items)

    def save(self, path: Path) -> None:
        """Save the backlog to a YAML file.

        Args:
            path: Path to save the file.
        """
        path.write_text(self.to_yaml())

    @classmethod
    def from_yaml(cls, yaml_content: str) -> Backlog:
        """Parse a backlog from YAML content.

        Args:
            yaml_content: YAML string to parse.

        Returns:
            Parsed Backlog instance.

        Raises:
            ValueError: If the YAML is invalid.
        """
        yaml_content = _strip_markdown_code_fence(yaml_content)
        try:
            data: dict[str, Any] = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            msg = f"Invalid YAML: {e}"
            raise ValueError(msg) from e

        if not isinstance(data, dict):
            msg = "Backlog YAML must be a mapping"
            raise ValueError(msg)

        return cls.model_validate(data)

    @classmethod
    def load(cls, path: Path) -> Backlog:
        """Load a backlog from a YAML file.

        Args:
            path: Path to the YAML file.

        Returns:
            Parsed Backlog instance.

        Raises:
            FileNotFoundError: If the file doesn't exist.
            ValueError: If the YAML is invalid.
        """
        if not path.exists():
            msg = f"Backlog file not found: {path}"
            raise FileNotFoundError(msg)
        return cls.from_yaml(path.read_text())
