"""Filesystem-based implementation of RunStore."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import structlog

from orx.dashboard.store.models import (
    ArtifactInfo,
    LastError,
    LogChunk,
    RunDetail,
    RunStatus,
    RunSummary,
)
from orx.observability.projector import (
    ProjectedRun,
    load_events,
    project_run,
    project_timeline,
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
            └── observability/
    """

    # Default allowed extensions for safety
    DEFAULT_ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
        {".md", ".json", ".yaml", ".yml", ".txt", ".log", ".diff", ".cast"}
    )

    def __init__(
        self,
        config_or_path: DashboardConfig | Path,
    ) -> None:
        """Initialize the store.

        Args:
            config_or_path: Dashboard configuration or direct path to runs directory.
        """
        if isinstance(config_or_path, Path):
            # Direct path mode (for testing)
            self.config = None
            self._runs_dir = config_or_path
            self._allowed_extensions: set[str] = set(self.DEFAULT_ALLOWED_EXTENSIONS)
        else:
            # Config mode (production)
            self.config = config_or_path
            self._runs_dir = config_or_path.get_runs_dir()
            self._allowed_extensions = set(config_or_path.allowed_extensions)

        self._log = logger.bind(component="FileSystemRunStore")

    @property
    def runs_dir(self) -> Path:
        """Get the runs directory."""
        return self._runs_dir

    def _is_safe_path(self, relative: str) -> bool:
        """Check if a relative path is safe.

        Args:
            relative: Relative path to check.

        Returns:
            True if path is safe to access.
        """
        # Block path traversal
        if ".." in relative or relative.startswith("/"):
            return False

        # Check extension
        ext = Path(relative).suffix.lower()
        return ext in self._allowed_extensions

    def _safe_path(self, run_dir: Path, relative: str) -> Path | None:
        """Resolve a path safely within run directory.

        Args:
            run_dir: Base run directory.
            relative: Relative path.

        Returns:
            Resolved path if safe, None otherwise.
        """
        if not self._is_safe_path(relative):
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
                data = json.loads(path.read_text())
                if isinstance(data, dict):
                    return cast(dict[str, Any], data)
        except (json.JSONDecodeError, OSError) as e:
            self._log.warning("Failed to read JSON", path=str(path), error=str(e))
        return None

    def _events_path(self, run_dir: Path) -> Path:
        """Return canonical observability events path for a run directory."""
        return run_dir / "observability" / "events.jsonl"

    def _load_projected_run(
        self, run_dir: Path
    ) -> tuple[list[dict[str, Any]], ProjectedRun | None]:
        """Load raw events and projected run summary from observability timeline."""
        events_path = self._events_path(run_dir)
        if not events_path.exists():
            return [], None
        events = load_events(events_path)
        if not events:
            return [], None
        return events, project_run(events)

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

        meta = self._read_json(run_dir / "meta.json") or {}
        state = self._read_json(run_dir / "state.json") or {}
        events, projected = self._load_projected_run(run_dir)
        state_status = cast(str | None, state.get("status"))

        current_stage = state.get("current_stage")
        pid = state.get("pid")
        pid_alive: bool | None = None
        if isinstance(pid, int) and pid > 0:
            try:
                os.kill(pid, 0)
                pid_alive = True
            except ProcessLookupError:
                pid_alive = False
            except PermissionError:
                pid_alive = None

        created_at: datetime | None = None
        updated_at: datetime | None = None
        fail_category: str | None = None

        if projected and projected.start_ts:
            try:
                created_at = datetime.fromisoformat(projected.start_ts)
            except ValueError:
                created_at = None
        if projected and projected.end_ts:
            try:
                updated_at = datetime.fromisoformat(projected.end_ts)
            except ValueError:
                updated_at = None

        if created_at is None:
            for value in (state.get("created_at"), meta.get("created_at")):
                if isinstance(value, str):
                    try:
                        created_at = datetime.fromisoformat(value)
                        break
                    except ValueError:
                        continue
        if updated_at is None and isinstance(state.get("updated_at"), str):
            try:
                updated_at = datetime.fromisoformat(cast(str, state["updated_at"]))
            except ValueError:
                updated_at = None

        run_end_error: str | None = None
        for event in reversed(events):
            if event.get("event_type") != "run.end":
                continue
            payload = event.get("payload")
            if isinstance(payload, dict):
                err = payload.get("error")
                if isinstance(err, str) and err.strip():
                    run_end_error = err.strip()
            break

        if projected:
            current_stage = projected.current_stage or current_stage
            if projected.status in {"success", "completed"}:
                status = RunStatus.SUCCESS
            elif projected.status in {"failure", "failed", "fail"} or any(
                str(stage.get("status") or "") in {"failure", "failed", "fail"}
                for stage in projected.stages
            ):
                status = RunStatus.FAIL
            elif projected.end_ts is None:
                status = RunStatus.RUNNING
            else:
                status = RunStatus.UNKNOWN
        else:
            status = RunStatus.from_state(
                state_status=state_status,
                stage=current_stage if isinstance(current_stage, str) else None,
            )

        if status == RunStatus.RUNNING and pid_alive is False:
            status = RunStatus.FAIL
            if fail_category is None:
                fail_category = "process_exited"

        # Legacy dashboard-triggered runs may have only an INIT stage with no PID,
        # no explicit status, and no observability events. Treat them as stale so
        # they don't stay forever in the "Active Runs" list.
        if (
            status == RunStatus.RUNNING
            and not events
            and state_status is None
            and not isinstance(pid, int)
            and isinstance(current_stage, str)
            and current_stage not in {"done", "failed"}
            and updated_at is not None
        ):
            status = RunStatus.UNKNOWN
            if fail_category is None:
                fail_category = "stale_state"

        if run_end_error:
            fail_category = run_end_error

        elapsed_ms: int | None = None
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
                # Task preview is optional metadata; silently ignore read failures
                # (e.g., permission issues, race conditions) and continue without it
                pass

        return RunSummary(
            run_id=run_id,
            status=status,
            current_stage=current_stage,
            created_at=created_at,
            updated_at=updated_at,
            elapsed_ms=elapsed_ms,
            pid=pid if isinstance(pid, int) else None,
            repo_path=meta.get("repo_path"),
            base_branch=meta.get("base_branch"),
            engine=meta.get("engine"),
            fail_category=fail_category,
            task_preview=task_preview,
        )

    def _summarize_failure(
        self, evidence: dict[str, Any], fail_category: str | None
    ) -> str | None:
        """Build a readable failure message from evidence."""
        if evidence.get("message"):
            return str(evidence["message"])

        if evidence.get("ruff_failed"):
            message = "Ruff failed"
            ruff_log = evidence.get("ruff_log")
            if isinstance(ruff_log, str) and ruff_log.strip():
                first_line = ruff_log.strip().splitlines()[0].strip()
                return f"{message}: {first_line}"
            return message

        if evidence.get("pytest_failed"):
            message = "Pytest failed"
            pytest_log = evidence.get("pytest_log")
            if isinstance(pytest_log, str) and pytest_log.strip():
                first_line = pytest_log.strip().splitlines()[0].strip()
                return f"{message}: {first_line}"
            return message

        if evidence.get("diff_empty"):
            return "No changes produced"

        if evidence.get("guardrail_violation"):
            return "Guardrail violation"

        if fail_category:
            return fail_category.replace("_", " ")

        if evidence:
            return "Run failed"

        return None

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
        events, projected = self._load_projected_run(run_dir)

        # Get stage statuses from observability projection only
        stage_statuses: dict[str, str] = {}
        if projected:
            for stage in projected.stages:
                stage_name = str(stage.get("stage") or "unknown")
                stage_statuses[stage_name] = str(stage.get("status") or "unknown")

        # Build last error info
        last_error = None
        evidence = state.get("last_failure_evidence", {})
        if (evidence or summary.fail_category) and not summary.is_active:
            message = self._summarize_failure(
                cast(dict[str, Any], evidence), summary.fail_category
            )
            last_error = LastError(
                category=summary.fail_category,
                message=message,
                evidence_paths=list(evidence.keys()) if isinstance(evidence, dict) else [],
            )

        # List artifacts
        artifacts = self.list_artifacts(run_id)
        artifact_paths = [a.path for a in artifacts]

        # List logs
        logs = self.list_logs(run_id)

        # Check for diff and observability
        has_diff = (run_dir / "artifacts" / "patch.diff").exists()
        has_metrics = self._events_path(run_dir).exists()

        # Load task content
        task_content = None
        task_path = run_dir / "context" / "task.md"
        if task_path.exists():
            import contextlib

            with contextlib.suppress(OSError):
                task_content = task_path.read_text()

        metrics_summary: dict[str, Any] | None = None
        if projected:
            metrics_summary = {
                "status": projected.status,
                "total_duration_ms": projected.duration_ms,
                "tokens": projected.tokens,
                "stages_executed": len(projected.stages),
                "stages": projected.stages,
            }
        elif events:
            metrics_summary = {
                "status": summary.status.value,
                "total_duration_ms": summary.elapsed_ms,
                "tokens": {"input": 0, "output": 0, "total": 0, "tool_calls": 0},
                "stages_executed": 0,
                "stages": [],
            }

        return RunDetail(
            **summary.model_dump(),
            base_sha=meta.get("base_sha") or state.get("baseline_sha"),
            worktree_path=meta.get("worktree_path"),
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
        for subdir_name in ("context", "artifacts", "prompts", "observability"):
            subdir = run_dir / subdir_name
            if not subdir.is_dir():
                continue

            for file_path in subdir.rglob("*"):
                if not file_path.is_file():
                    continue

                ext = file_path.suffix.lower()
                if ext not in self._allowed_extensions:
                    continue

                relative = str(file_path.relative_to(run_dir))

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

    def get_run_metrics(self, run_id: str) -> dict[str, Any] | None:
        """Project run metrics from observability events."""
        run_dir = self._runs_dir / run_id
        _events, projected = self._load_projected_run(run_dir)
        if projected is None:
            return None
        return {
            "status": projected.status,
            "total_duration_ms": projected.duration_ms,
            "tokens": projected.tokens,
            "stages_executed": len(projected.stages),
            "stages": projected.stages,
        }

    def get_stage_metrics(self, run_id: str) -> list[dict[str, Any]]:
        """Project per-stage metrics from observability events."""
        run_dir = self._runs_dir / run_id
        _events, projected = self._load_projected_run(run_dir)
        if projected is None:
            return []

        output: list[dict[str, Any]] = []
        for stage in projected.stages:
            tokens = stage.get("tokens") if isinstance(stage.get("tokens"), dict) else {}
            output.append(
                {
                    "stage": stage.get("stage"),
                    "item_id": stage.get("item_id"),
                    "attempt": stage.get("attempt"),
                    "start_ts": stage.get("start_ts"),
                    "end_ts": stage.get("end_ts"),
                    "duration_ms": stage.get("duration_ms"),
                    "status": stage.get("status"),
                    "failure_message": stage.get("error"),
                    "executor": stage.get("executor"),
                    "model": stage.get("model"),
                    "tokens": tokens,
                    "gates": [],
                }
            )
        return output

    def get_timeline_groups(self, run_id: str) -> dict[str, list[dict[str, Any]]]:
        """Get grouped observability timeline buckets for a run."""
        run_dir = self._runs_dir / run_id
        events_path = self._events_path(run_dir)
        if not events_path.exists():
            return {
                "llm": [],
                "network": [],
                "proc": [],
                "fs": [],
                "tty": [],
                "gate": [],
                "other": [],
            }
        return project_timeline(load_events(events_path))

    def get_observability_events(self, run_id: str) -> list[dict[str, Any]]:
        """Get raw observability events."""
        run_dir = self._runs_dir / run_id
        events_path = self._events_path(run_dir)
        if not events_path.exists():
            return []
        return load_events(events_path)
