"""Local worker for running orx as subprocess."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from typing import TYPE_CHECKING

import structlog

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

    def __init__(self, config: "DashboardConfig") -> None:
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

        job = RunJob(
            run_id=run_id,
            task=task,
            repo_path=repo_path,
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
                return False

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
            # Send SIGTERM first
            os.kill(pid, signal.SIGTERM)

            # Wait for grace period
            try:
                job.process.wait(timeout=self.config.cancel_grace_seconds)
            except subprocess.TimeoutExpired:
                # Force kill
                self._log.warning("Force killing run", run_id=job.run_id, pid=pid)
                os.kill(pid, signal.SIGKILL)
                job.process.wait(timeout=2)

            return True
        except (ProcessLookupError, OSError) as e:
            self._log.warning("Failed to cancel", run_id=job.run_id, error=str(e))
            return False

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
        if job.task.startswith("@"):
            cmd.extend(["--task-file", job.task[1:]])
        else:
            cmd.append(job.task)

        # Add options
        if job.base_branch:
            cmd.extend(["--base-branch", job.base_branch])

        # Set working directory
        cwd = job.repo_path or str(Path.cwd())

        try:
            # Start subprocess
            process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
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

        except Exception as e:
            self._log.error("Failed to start run", run_id=job.run_id, error=str(e))

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
