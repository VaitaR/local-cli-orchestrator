"""Local worker for running orx as subprocess."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from typing import TYPE_CHECKING, Any

import structlog
import yaml

from orx.infra.command import CommandRunner

if TYPE_CHECKING:
    from orx.dashboard.config import DashboardConfig

logger = structlog.get_logger()


@dataclass
class RunJob:
    """A queued run job."""

    run_id: str
    task: str
    repo_path: str | None = None
    base_branch: str | None = None
    config_overrides: dict = field(default_factory=dict)
    process: subprocess.Popen | None = None
    started_at: float | None = None


class LocalWorker:
    """Local worker that runs orx as subprocess.

    Features:
    - In-memory job queue
    - Background thread for execution
    - PID tracking for cancellation
    - Concurrency limiting
    """

    def __init__(self, config: DashboardConfig) -> None:
        """Initialize the worker.

        Args:
            config: Dashboard configuration.
        """
        self.config = config
        self._queue: Queue[RunJob] = Queue()
        self._active_jobs: dict[str, RunJob] = {}
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._log = logger.bind(component="LocalWorker")
        self._cmd = CommandRunner()

    def start(self) -> None:
        """Start the background worker thread."""
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._log.info("Worker started")

    def stop(self) -> None:
        """Stop the worker thread."""
        self._stop_event.set()

        # Cancel all active jobs
        with self._lock:
            for job in list(self._active_jobs.values()):
                self._cancel_job(job)

        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

        self._log.info("Worker stopped")

    def start_run(
        self,
        task: str,
        *,
        repo_path: str | None = None,
        base_branch: str | None = None,
        config_overrides: dict | None = None,
    ) -> str:
        """Queue a new run.

        Args:
            task: Task description or @file path.
            repo_path: Path to repository.
            base_branch: Base branch name.
            config_overrides: Optional config overrides.

        Returns:
            Generated run_id.

        Raises:
            RuntimeError: If queue is full.
            ValueError: If task is empty.
        """
        if not task.strip():
            raise ValueError("Task cannot be empty")

        # Check queue size
        if self._queue.qsize() >= self.config.max_concurrency * 2:
            raise RuntimeError("Queue is full, try again later")

        # Generate run_id (will be assigned by orx, but we use a placeholder)
        import uuid
        from datetime import UTC, datetime

        ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
        run_id = f"{ts}_{uuid.uuid4().hex[:8]}"

        resolved_repo = self._resolve_repo_path(repo_path)

        job = RunJob(
            run_id=run_id,
            task=task,
            repo_path=str(resolved_repo),
            base_branch=base_branch,
            config_overrides=config_overrides or {},
        )

        self._queue.put(job)
        self._log.info("Run queued", run_id=run_id)

        return run_id

    def cancel_run(self, run_id: str) -> bool:
        """Cancel a running job.

        Args:
            run_id: Run identifier.

        Returns:
            True if cancellation was initiated.
        """
        with self._lock:
            job = self._active_jobs.get(run_id)
            if job is None:
                pid = self._read_run_pid(run_id)
                if pid is None:
                    return False
                return self._cancel_pid(pid, run_id=run_id)

            return self._cancel_job(job)

    def _cancel_job(self, job: RunJob) -> bool:
        """Cancel a specific job.

        Args:
            job: Job to cancel.

        Returns:
            True if cancellation was initiated.
        """
        if job.process is None:
            return False

        pid = job.process.pid
        self._log.info("Cancelling run", run_id=job.run_id, pid=pid)

        try:
            # Send SIGTERM to the whole session (started with start_new_session=True)
            os.killpg(pid, signal.SIGTERM)

            # Wait for grace period
            try:
                job.process.wait(timeout=self.config.cancel_grace_seconds)
            except subprocess.TimeoutExpired:
                # Force kill
                self._log.warning("Force killing run", run_id=job.run_id, pid=pid)
                os.killpg(pid, signal.SIGKILL)
                job.process.wait(timeout=2)

            return True
        except (ProcessLookupError, OSError) as e:
            self._log.warning("Failed to cancel", run_id=job.run_id, error=str(e))
            return False

    def _cancel_pid(self, pid: int, *, run_id: str) -> bool:
        """Cancel a run by PID (for runs started by a previous dashboard session)."""
        self._log.info("Cancelling run by pid", run_id=run_id, pid=pid)
        try:
            os.killpg(pid, signal.SIGTERM)
            deadline = time.time() + self.config.cancel_grace_seconds
            while time.time() < deadline:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    return True
                time.sleep(0.1)
            self._log.warning("Force killing run by pid", run_id=run_id, pid=pid)
            os.killpg(pid, signal.SIGKILL)
            return True
        except (ProcessLookupError, OSError) as e:
            self._log.warning("Failed to cancel by pid", run_id=run_id, error=str(e))
            return False

    def _read_run_pid(self, run_id: str) -> int | None:
        """Read PID for a run from state.json if present."""
        if "/" in run_id or ".." in run_id:
            return None
        run_dir = (self.config.runs_root / run_id).resolve()
        try:
            run_dir.relative_to(self.config.runs_root.resolve())
        except ValueError:
            return None
        state_path = run_dir / "state.json"
        if not state_path.exists():
            return None
        try:
            import json

            data = json.loads(state_path.read_text())
            pid = data.get("pid")
            if isinstance(pid, int) and pid > 0:
                return pid
        except Exception:
            return None
        return None

    def get_run_pid(self, run_id: str) -> int | None:
        """Get PID of a running job.

        Args:
            run_id: Run identifier.

        Returns:
            PID if running, None otherwise.
        """
        with self._lock:
            job = self._active_jobs.get(run_id)
            if job and job.process:
                return job.process.pid
            return None

    def _run_loop(self) -> None:
        """Background worker loop."""
        while not self._stop_event.is_set():
            # Check for completed jobs
            self._cleanup_completed()

            # Check concurrency limit
            with self._lock:
                active_count = len(self._active_jobs)

            if active_count >= self.config.max_concurrency:
                time.sleep(0.5)
                continue

            # Get next job
            try:
                job = self._queue.get(timeout=0.5)
            except Empty:
                continue

            # Execute job
            self._execute_job(job)

    def _execute_job(self, job: RunJob) -> None:
        """Execute a run job.

        Args:
            job: Job to execute.
        """
        self._log.info("Starting run", run_id=job.run_id)

        # Build command
        cmd = [self.config.orx_bin, "run"]

        # Add task
        cmd.append(job.task)

        # Add options
        if job.base_branch:
            cmd.extend(["--base-branch", job.base_branch])

        # Handle config overrides
        temp_config_path = self._create_temp_config(job.config_overrides)
        if temp_config_path:
            cmd.extend(["--config", str(temp_config_path)])
        elif job.config_overrides.get("engine"):
            # Simple engine override via CLI flag
            cmd.extend(["--engine", job.config_overrides["engine"]])

        base_dir = self._resolve_repo_path(job.repo_path)
        runs_dir = base_dir / "runs"
        if self.config.runs_root.resolve() != runs_dir.resolve():
            self._log.warning(
                "Dashboard runs_root differs from orx runs directory",
                runs_root=str(self.config.runs_root),
                expected_runs=str(runs_dir),
            )

        existing_run_ids = self._snapshot_run_ids(runs_dir)

        # Prepare environment - inherit current env and preserve ORX_RUNS_ROOT
        env = os.environ.copy()

        try:
            cmd.extend(["--dir", str(base_dir)])

            # Start subprocess
            process = self._cmd.start_process(
                cmd,
                cwd=base_dir,
                env=env,
                start_new_session=True,  # Allow proper signal handling
            )

            job.process = process
            job.started_at = time.time()

            with self._lock:
                self._active_jobs[job.run_id] = job

            self._log.info(
                "Run started",
                run_id=job.run_id,
                pid=process.pid,
                cmd=" ".join(cmd),
            )

            actual_run_id = self._wait_for_run_id(
                runs_dir,
                existing_run_ids,
            )
            if actual_run_id and actual_run_id != job.run_id:
                with self._lock:
                    self._active_jobs.pop(job.run_id, None)
                    job.run_id = actual_run_id
                    self._active_jobs[job.run_id] = job
                self._log.info("Resolved run id", run_id=job.run_id)

        except Exception as e:
            self._log.error("Failed to start run", run_id=job.run_id, error=str(e))

    def _resolve_repo_path(self, repo_path: str | None) -> Path:
        """Resolve repo path to use for runs."""
        if repo_path:
            resolved = Path(repo_path).expanduser().resolve()
        else:
            resolved = self.config.runs_root.parent.resolve()

        if not resolved.exists():
            msg = f"Repository path does not exist: {resolved}"
            raise ValueError(msg)
        if not resolved.is_dir():
            msg = f"Repository path is not a directory: {resolved}"
            raise ValueError(msg)
        return resolved

    def _snapshot_run_ids(self, runs_dir: Path) -> set[str]:
        """Capture current run ids in runs directory."""
        if not runs_dir.exists():
            return set()
        return {
            entry.name
            for entry in runs_dir.iterdir()
            if entry.is_dir() and not entry.name.startswith(".")
        }

    def _wait_for_run_id(self, runs_dir: Path, existing: set[str]) -> str | None:
        """Wait briefly for a new run directory to appear."""
        deadline = time.time() + self.config.run_id_timeout_seconds
        while time.time() < deadline:
            if runs_dir.exists():
                for entry in runs_dir.iterdir():
                    if not entry.is_dir() or entry.name.startswith("."):
                        continue
                    if entry.name not in existing:
                        return entry.name
            time.sleep(self.config.run_id_poll_interval)
        return None

    def _cleanup_completed(self) -> None:
        """Remove completed jobs from active list."""
        with self._lock:
            completed = []
            for run_id, job in self._active_jobs.items():
                if job.process and job.process.poll() is not None:
                    completed.append(run_id)
                    returncode = job.process.returncode
                    self._log.info(
                        "Run completed",
                        run_id=run_id,
                        returncode=returncode,
                    )

            for run_id in completed:
                del self._active_jobs[run_id]

    def _create_temp_config(self, overrides: dict[str, Any]) -> Path | None:
        """Create a temporary config file from overrides.

        Args:
            overrides: Config overrides dict with optional keys:
                - engine: Global engine type ("codex", "gemini")
                - stages: Per-stage config {stage_name: {executor: "..."}} 

        Returns:
            Path to temp config file, or None if no complex overrides.
        """
        if not overrides:
            return None

        # Check if we need a full config file (per-stage settings)
        stages = overrides.get("stages", {})
        if not stages:
            # Simple engine override can be handled via CLI flag
            return None

        # Build config structure
        engine_type = overrides.get("engine", "codex")
        config_data: dict[str, Any] = {
            "version": "1.0",
            "engine": {
                "type": engine_type,
            },
            "stages": {},
        }

        # Add per-stage executor overrides
        for stage_name, stage_config in stages.items():
            if isinstance(stage_config, dict) and stage_config.get("executor"):
                config_data["stages"][stage_name] = {
                    "executor": stage_config["executor"],
                }

        # Write to temp file
        fd, path = tempfile.mkstemp(suffix=".yaml", prefix="orx_dashboard_")
        try:
            with os.fdopen(fd, "w") as f:
                yaml.dump(config_data, f, default_flow_style=False)
            self._log.debug("Created temp config", path=path, config=config_data)
            return Path(path)
        except Exception as e:
            self._log.error("Failed to create temp config", error=str(e))
            return None
