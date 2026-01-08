"""Filesystem-based implementation of RunStore."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from orx.dashboard.store.models import (
    ArtifactInfo,
    LastError,
    LogChunk,
    RunDetail,
    RunStatus,
    RunSummary,
)

if TYPE_CHECKING:
    from orx.dashboard.config import DashboardConfig

logger = structlog.get_logger()


class FileSystemRunStore:
    """Filesystem-based run store.

    Reads run data from the standard orx directory layout:
        runs/<run_id>/
            ├── meta.json
            ├── state.json
            ├── context/
            ├── artifacts/
            ├── logs/
            └── metrics/
    """

    def __init__(self, config: "DashboardConfig") -> None:
        """Initialize the store.

        Args:
            config: Dashboard configuration.
        """
        self.config = config
        self._runs_dir = config.get_runs_dir()
        self._log = logger.bind(component="FileSystemRunStore")

    @property
    def runs_dir(self) -> Path:
        """Get the runs directory."""
        return self._runs_dir

    def _safe_path(self, run_dir: Path, relative: str) -> Path | None:
        """Resolve a path safely within run directory.

        Args:
            run_dir: Base run directory.
            relative: Relative path.

        Returns:
            Resolved path if safe, None otherwise.
        """
        if not self.config.is_path_allowed(run_dir, relative):
            return None

        resolved = (run_dir / relative).resolve()
        try:
            resolved.relative_to(run_dir.resolve())
            return resolved
        except ValueError:
            return None

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        """Read and parse a JSON file safely.

        Args:
            path: Path to JSON file.

        Returns:
            Parsed JSON or None on error.
        """
        try:
            if path.exists():
                return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            self._log.warning("Failed to read JSON", path=str(path), error=str(e))
        return None

    def _load_run_summary(self, run_id: str) -> RunSummary | None:
        """Load a run summary from filesystem.

        Args:
            run_id: Run identifier.

        Returns:
            RunSummary or None if not found.
        """
        run_dir = self._runs_dir / run_id
        if not run_dir.is_dir():
            return None

        # Read meta.json (immutable metadata)
        meta = self._read_json(run_dir / "meta.json") or {}

        # Read state.json (current state)
        state = self._read_json(run_dir / "state.json") or {}

        # Determine status
        current_stage = state.get("current_stage")
        stage_statuses = state.get("stage_statuses", {})

        # Check for failure
        fail_category = None
        for status_info in stage_statuses.values():
            if status_info.get("status") == "failed":
                fail_category = status_info.get("error", "unknown")
                break

        # Map to RunStatus
        if current_stage == "done":
            status = RunStatus.SUCCESS
        elif current_stage == "failed" or fail_category:
            status = RunStatus.FAIL
        elif current_stage:
            status = RunStatus.RUNNING
        else:
            status = RunStatus.UNKNOWN

        # Parse timestamps
        created_at = None
        updated_at = None
        try:
            if "created_at" in state:
                created_at = datetime.fromisoformat(state["created_at"])
            elif "created_at" in meta:
                created_at = datetime.fromisoformat(meta["created_at"])
            if "updated_at" in state:
                updated_at = datetime.fromisoformat(state["updated_at"])
        except (ValueError, TypeError):
            pass

        # Calculate elapsed time
        elapsed_ms = None
        if created_at:
            end_time = updated_at or datetime.now(tz=UTC)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=UTC)
            elapsed_ms = int((end_time - created_at).total_seconds() * 1000)

        # Read task preview
        task_preview = None
        task_path = run_dir / "context" / "task.md"
        if task_path.exists():
            try:
                content = task_path.read_text()
                task_preview = content[:100] + "..." if len(content) > 100 else content
            except OSError:
                pass

        return RunSummary(
            run_id=run_id,
            status=status,
            current_stage=current_stage,
            created_at=created_at,
            updated_at=updated_at,
            elapsed_ms=elapsed_ms,
            repo_path=meta.get("repo_path"),
            base_branch=meta.get("base_branch"),
            fail_category=fail_category,
            task_preview=task_preview,
        )

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
            List of RunSummary objects, sorted by created_at descending.
        """
        runs: list[RunSummary] = []

        if not self._runs_dir.exists():
            return runs

        # Scan run directories
        for entry in self._runs_dir.iterdir():
            if not entry.is_dir() or entry.name.startswith("."):
                continue

            summary = self._load_run_summary(entry.name)
            if summary is None:
                continue

            if active_only and not summary.is_active:
                continue

            runs.append(summary)

        # Sort by created_at descending (newest first)
        runs.sort(
            key=lambda r: r.created_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )

        # Apply pagination
        if offset > 0:
            runs = runs[offset:]
        if limit is not None:
            runs = runs[:limit]

        return runs

    def get_run(self, run_id: str) -> RunDetail | None:
        """Get detailed information about a run.

        Args:
            run_id: Run identifier.

        Returns:
            RunDetail if found, None otherwise.
        """
        run_dir = self._runs_dir / run_id
        if not run_dir.is_dir():
            return None

        # Load summary first
        summary = self._load_run_summary(run_id)
        if summary is None:
            return None

        # Read additional detail from state.json
        state = self._read_json(run_dir / "state.json") or {}
        meta = self._read_json(run_dir / "meta.json") or {}

        # Get stage statuses
        stage_statuses = {}
        for key, val in state.get("stage_statuses", {}).items():
            stage_statuses[key] = val.get("status", "unknown")

        # Build last error info
        last_error = None
        evidence = state.get("last_failure_evidence", {})
        if evidence or summary.fail_category:
            last_error = LastError(
                category=summary.fail_category,
                message=evidence.get("message"),
                evidence_paths=list(evidence.keys()),
            )

        # List artifacts
        artifacts = self.list_artifacts(run_id)
        artifact_paths = [a.path for a in artifacts]

        # List logs
        logs = self.list_logs(run_id)

        # Check for diff and metrics
        has_diff = (run_dir / "artifacts" / "patch.diff").exists()
        has_metrics = (run_dir / "metrics" / "run.json").exists()

        # Load task content
        task_content = None
        task_path = run_dir / "context" / "task.md"
        if task_path.exists():
            try:
                task_content = task_path.read_text()
            except OSError:
                pass

        # Load metrics summary if available
        metrics_summary = None
        if has_metrics:
            metrics_summary = self._read_json(run_dir / "metrics" / "run.json")

        return RunDetail(
            **summary.model_dump(),
            base_sha=meta.get("base_sha") or state.get("baseline_sha"),
            worktree_path=meta.get("worktree_path"),
            pid=state.get("pid"),
            last_error=last_error,
            artifacts=artifact_paths,
            logs=logs,
            has_diff=has_diff,
            has_metrics=has_metrics,
            task_content=task_content,
            stage_statuses=stage_statuses,
            metrics_summary=metrics_summary,
        )

    def list_artifacts(self, run_id: str) -> list[ArtifactInfo]:
        """List available artifacts for a run.

        Args:
            run_id: Run identifier.

        Returns:
            List of ArtifactInfo objects.
        """
        run_dir = self._runs_dir / run_id
        if not run_dir.is_dir():
            return []

        artifacts: list[ArtifactInfo] = []

        # Scan allowed directories
        for subdir_name in ("context", "artifacts", "prompts"):
            subdir = run_dir / subdir_name
            if not subdir.is_dir():
                continue

            for file_path in subdir.iterdir():
                if not file_path.is_file():
                    continue

                ext = file_path.suffix.lower()
                if ext not in self.config.allowed_extensions:
                    continue

                relative = f"{subdir_name}/{file_path.name}"

                try:
                    size = file_path.stat().st_size
                except OSError:
                    size = 0

                artifacts.append(
                    ArtifactInfo(
                        name=file_path.name,
                        path=relative,
                        size_bytes=size,
                        extension=ext,
                        is_previewable=ext in {".md", ".json", ".txt", ".yaml", ".yml"},
                    )
                )

        return sorted(artifacts, key=lambda a: a.path)

    def get_artifact(self, run_id: str, path: str) -> bytes | None:
        """Read an artifact file.

        Args:
            run_id: Run identifier.
            path: Relative path to artifact within run directory.

        Returns:
            File contents as bytes, or None if not found/not allowed.
        """
        run_dir = self._runs_dir / run_id
        if not run_dir.is_dir():
            return None

        safe = self._safe_path(run_dir, path)
        if safe is None or not safe.exists():
            return None

        try:
            return safe.read_bytes()
        except OSError as e:
            self._log.warning("Failed to read artifact", path=path, error=str(e))
            return None

    def get_diff(self, run_id: str) -> str | None:
        """Get the diff for a run.

        Args:
            run_id: Run identifier.

        Returns:
            Diff content as string, or None if not available.
        """
        run_dir = self._runs_dir / run_id
        diff_path = run_dir / "artifacts" / "patch.diff"

        if not diff_path.exists():
            return None

        try:
            return diff_path.read_text()
        except OSError as e:
            self._log.warning("Failed to read diff", run_id=run_id, error=str(e))
            return None

    def list_logs(self, run_id: str) -> list[str]:
        """List available log files for a run.

        Args:
            run_id: Run identifier.

        Returns:
            List of log file names.
        """
        logs_dir = self._runs_dir / run_id / "logs"
        if not logs_dir.is_dir():
            return []

        logs = []
        for entry in logs_dir.iterdir():
            if entry.is_file() and entry.suffix.lower() in (".log", ".txt"):
                logs.append(entry.name)

        return sorted(logs)

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
            log_name: Name of the log file.
            cursor: Line offset to start from (0 = start, negative = from end).
            lines: Number of lines to return.

        Returns:
            LogChunk with content and pagination info.
        """
        run_dir = self._runs_dir / run_id
        log_path = run_dir / "logs" / log_name

        # Validate path
        safe = self._safe_path(run_dir, f"logs/{log_name}")
        if safe is None or not safe.exists():
            return None

        try:
            all_lines = safe.read_text().splitlines()
            total_lines = len(all_lines)

            # Handle negative cursor (from end)
            if cursor < 0:
                cursor = max(0, total_lines + cursor)

            # Get requested lines
            end_idx = min(cursor + lines, total_lines)
            chunk_lines = all_lines[cursor:end_idx]

            return LogChunk(
                content="\n".join(chunk_lines),
                cursor=end_idx,
                has_more=end_idx < total_lines,
                total_lines=total_lines,
            )
        except OSError as e:
            self._log.warning("Failed to read log", log_name=log_name, error=str(e))
            return None

    def get_run_metrics(self, run_id: str) -> dict | None:
        """Get aggregated run metrics.

        Args:
            run_id: Run identifier.

        Returns:
            Run metrics dict or None.
        """
        return self._read_json(self._runs_dir / run_id / "metrics" / "run.json")

    def get_stage_metrics(self, run_id: str) -> list[dict]:
        """Get per-stage metrics.

        Args:
            run_id: Run identifier.

        Returns:
            List of stage metric records.
        """
        stages_path = self._runs_dir / run_id / "metrics" / "stages.jsonl"
        if not stages_path.exists():
            return []

        metrics = []
        try:
            for line in stages_path.read_text().splitlines():
                if line.strip():
                    metrics.append(json.loads(line))
        except (json.JSONDecodeError, OSError) as e:
            self._log.warning("Failed to read stage metrics", run_id=run_id, error=str(e))

        return metrics
