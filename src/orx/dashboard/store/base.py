"""Protocol definitions for the store layer."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from orx.dashboard.store.models import (
        ArtifactInfo,
        LogChunk,
        RunDetail,
        RunSummary,
    )


class RunStore(Protocol):
    """Protocol for run data access.

    Implementations can be filesystem-based, database-backed, etc.
    The dashboard depends only on this interface.
    """

    def list_runs(
        self,
        *,
        active_only: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[RunSummary]:
        """List runs with optional filtering.

        Args:
            active_only: If True, return only running runs.
            limit: Maximum number of runs to return.
            offset: Number of runs to skip.

        Returns:
            List of RunSummary objects.
        """
        ...

    def get_run(self, run_id: str) -> RunDetail | None:
        """Get detailed information about a run.

        Args:
            run_id: Run identifier.

        Returns:
            RunDetail if found, None otherwise.
        """
        ...

    def get_artifact(self, run_id: str, path: str) -> bytes | None:
        """Read an artifact file.

        Args:
            run_id: Run identifier.
            path: Relative path to artifact within run directory.

        Returns:
            File contents as bytes, or None if not found/not allowed.
        """
        ...

    def list_artifacts(self, run_id: str) -> list[ArtifactInfo]:
        """List available artifacts for a run.

        Args:
            run_id: Run identifier.

        Returns:
            List of ArtifactInfo objects.
        """
        ...

    def get_diff(self, run_id: str) -> str | None:
        """Get the diff for a run.

        Args:
            run_id: Run identifier.

        Returns:
            Diff content as string, or None if not available.
        """
        ...

    def tail_log(
        self,
        run_id: str,
        log_name: str,
        cursor: int = 0,
        lines: int = 200,
    ) -> LogChunk | None:
        """Get a chunk of log content.

        Args:
            run_id: Run identifier.
            log_name: Name of the log file (e.g., "pytest.log").
            cursor: Line offset to start from.
            lines: Number of lines to return.

        Returns:
            LogChunk with content and pagination info.
        """
        ...

    def list_logs(self, run_id: str) -> list[str]:
        """List available log files for a run.

        Args:
            run_id: Run identifier.

        Returns:
            List of log file names.
        """
        ...


class Runner(Protocol):
    """Protocol for run control operations.

    Implementations can be local subprocess, remote API, etc.
    """

    def start_run(
        self,
        task: str,
        *,
        repo_path: str | None = None,
        base_branch: str | None = None,
        config_overrides: dict | None = None,
    ) -> str:
        """Start a new run.

        Args:
            task: Task description or @file path.
            repo_path: Path to repository.
            base_branch: Base branch name.
            config_overrides: Optional config overrides.

        Returns:
            Run ID of the started run.
        """
        ...

    def cancel_run(self, run_id: str) -> bool:
        """Cancel a running run.

        Args:
            run_id: Run identifier.

        Returns:
            True if cancellation was initiated.
        """
        ...

    def get_run_pid(self, run_id: str) -> int | None:
        """Get the PID of a running run.

        Args:
            run_id: Run identifier.

        Returns:
            PID if running, None otherwise.
        """
        ...


class DiffProvider(Protocol):
    """Protocol for diff generation.

    Default implementation reads patch.diff, but can be extended
    to compute diff from worktree.
    """

    def get_diff(self, run_id: str) -> str | None:
        """Get diff content for a run.

        Args:
            run_id: Run identifier.

        Returns:
            Diff content or None.
        """
        ...


class MetricsProvider(Protocol):
    """Protocol for metrics access (P1).

    Provides access to run metrics and stage metrics.
    """

    def get_run_metrics(self, run_id: str) -> dict | None:
        """Get aggregated run metrics.

        Args:
            run_id: Run identifier.

        Returns:
            Run metrics dict or None.
        """
        ...

    def get_stage_metrics(self, run_id: str) -> list[dict]:
        """Get per-stage metrics.

        Args:
            run_id: Run identifier.

        Returns:
            List of stage metric records.
        """
        ...
