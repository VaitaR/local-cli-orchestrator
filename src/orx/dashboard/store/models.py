"""Data models for the dashboard store layer."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    """Status of a run."""

    RUNNING = "running"
    SUCCESS = "success"
    FAIL = "fail"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"

    @classmethod
    def from_state(cls, state_status: str | None, stage: str | None) -> RunStatus:
        """Convert from Orx state.json status/stage to RunStatus.

        Args:
            state_status: Status from state.json (pending/running/completed/failed).
            stage: Current stage from state.json.

        Returns:
            Mapped RunStatus.
        """
        if stage in ("done",):
            return cls.SUCCESS
        if stage in ("failed",):
            return cls.FAIL
        if state_status == "running" or stage not in ("done", "failed", None):
            return cls.RUNNING
        if state_status == "completed":
            return cls.SUCCESS
        if state_status == "failed":
            return cls.FAIL
        return cls.UNKNOWN


class LastError(BaseModel):
    """Information about the last error in a run."""

    category: str | None = None
    message: str | None = None
    evidence_paths: list[str] = Field(default_factory=list)


class RunSummary(BaseModel):
    """Lightweight run information for list views.

    This is the minimum info needed to render runs list.
    """

    run_id: str
    status: RunStatus = RunStatus.UNKNOWN
    current_stage: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    elapsed_ms: int | None = None
    pid: int | None = None
    repo_path: str | None = None
    base_branch: str | None = None
    engine: str | None = None
    fail_category: str | None = None
    task_preview: str | None = None

    @property
    def is_active(self) -> bool:
        """Check if run is currently active."""
        return self.status == RunStatus.RUNNING

    @property
    def can_cancel(self) -> bool:
        """True if dashboard can attempt to cancel the run."""
        return self.is_active and isinstance(self.pid, int) and self.pid > 0

    @property
    def elapsed_human(self) -> str:
        """Get human-readable elapsed time."""
        if self.elapsed_ms is None:
            return "-"
        seconds = self.elapsed_ms // 1000
        if seconds < 60:
            return f"{seconds}s"
        minutes = seconds // 60
        secs = seconds % 60
        if minutes < 60:
            return f"{minutes}m {secs}s"
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}h {mins}m"

    @property
    def started_at(self) -> str | None:
        """Get start time as ISO 8601 string for frontend consumption.

        Returns:
            ISO 8601 formatted timestamp string or None if created_at is None.
        """
        if self.created_at is None:
            return None
        return self.created_at.isoformat()

    @property
    def started_at_short(self) -> str | None:
        """Get a short start time string (HH:MM) for server-rendered fallback."""
        if self.created_at is None:
            return None
        return self.created_at.strftime("%H:%M")

    @property
    def created_at_iso(self) -> str | None:
        """Alias for started_at property.

        Returns:
            Same value as started_at (ISO 8601 formatted timestamp or None).
        """
        return self.started_at


class RunDetail(RunSummary):
    """Full run information for detail page.

    Extends RunSummary with additional detail-only fields.
    """

    base_sha: str | None = None
    worktree_path: str | None = None
    last_error: LastError | None = None
    artifacts: list[str] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)
    has_diff: bool = False
    has_metrics: bool = False
    task_content: str | None = None

    # Stage statuses for overview
    stage_statuses: dict[str, str] = Field(default_factory=dict)

    # Metrics summary (if available)
    metrics_summary: dict[str, Any] | None = None


class ArtifactInfo(BaseModel):
    """Information about an artifact file."""

    name: str
    path: str
    size_bytes: int
    extension: str
    is_previewable: bool = True


class LogChunk(BaseModel):
    """A chunk of log content with cursor for pagination."""

    content: str
    cursor: int  # Line offset for next request
    has_more: bool
    total_lines: int | None = None


class StartRunRequest(BaseModel):
    """Request to start a new run."""

    task: str = Field(..., min_length=1, description="Task description or @file path")
    repo_path: str | None = Field(None, description="Path to repository")
    base_branch: str | None = Field(None, description="Base branch name")
    pipeline: str | None = Field(
        None, description="Pipeline to use (standard, fast_fix, etc.)"
    )
    pipeline_override: dict[str, Any] | None = Field(
        None, description="Custom pipeline definition (nodes) for this run only"
    )
    config_overrides: dict[str, Any] = Field(
        default_factory=dict, description="Config overrides"
    )


class StartRunResponse(BaseModel):
    """Response after starting a run."""

    run_id: str
    status: str = "queued"
    message: str | None = None
