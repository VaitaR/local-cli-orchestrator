"""Run directory layout management for orx."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


def generate_run_id() -> str:
    """Generate a unique run ID with timestamp prefix.

    Returns:
        A run ID in format: YYYYMMDD_HHMMSS_<short-uuid>

    Example:
        >>> run_id = generate_run_id()
        >>> len(run_id) > 20
        True
    """
    ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    return f"{ts}_{short_uuid}"


@dataclass
class RunPaths:
    """Manages the directory structure for a single orx run.

    Attributes:
        base_dir: The base directory (typically project root).
        run_id: Unique identifier for this run.

    Example:
        >>> paths = RunPaths(Path("/project"), "20240101_120000_abc12345")
        >>> paths.run_dir.name
        '20240101_120000_abc12345'
    """

    base_dir: Path
    run_id: str
    _created: bool = field(default=False, repr=False)

    @property
    def runs_dir(self) -> Path:
        """Directory containing all runs."""
        return self.base_dir / "runs"

    @property
    def run_dir(self) -> Path:
        """Root directory for this specific run."""
        return self.runs_dir / self.run_id

    @property
    def context_dir(self) -> Path:
        """Directory for context artifacts."""
        return self.run_dir / "context"

    @property
    def prompts_dir(self) -> Path:
        """Directory for materialized prompts."""
        return self.run_dir / "prompts"

    @property
    def artifacts_dir(self) -> Path:
        """Directory for output artifacts."""
        return self.run_dir / "artifacts"

    @property
    def logs_dir(self) -> Path:
        """Directory for log files."""
        return self.run_dir / "logs"

    @property
    def worktrees_dir(self) -> Path:
        """Directory for git worktrees."""
        return self.base_dir / ".worktrees"

    @property
    def worktree_path(self) -> Path:
        """Path to the worktree for this run."""
        return self.worktrees_dir / self.run_id

    # Context files
    @property
    def task_md(self) -> Path:
        """Path to task.md."""
        return self.context_dir / "task.md"

    @property
    def plan_md(self) -> Path:
        """Path to plan.md."""
        return self.context_dir / "plan.md"

    @property
    def spec_md(self) -> Path:
        """Path to spec.md."""
        return self.context_dir / "spec.md"

    @property
    def backlog_yaml(self) -> Path:
        """Path to backlog.yaml."""
        return self.context_dir / "backlog.yaml"

    @property
    def project_map_md(self) -> Path:
        """Path to project_map.md."""
        return self.context_dir / "project_map.md"

    @property
    def decisions_md(self) -> Path:
        """Path to decisions.md."""
        return self.context_dir / "decisions.md"

    @property
    def lessons_md(self) -> Path:
        """Path to lessons.md."""
        return self.context_dir / "lessons.md"

    # Artifact files
    @property
    def patch_diff(self) -> Path:
        """Path to patch.diff."""
        return self.artifacts_dir / "patch.diff"

    @property
    def review_md(self) -> Path:
        """Path to review.md artifact."""
        return self.artifacts_dir / "review.md"

    @property
    def pr_body_md(self) -> Path:
        """Path to pr_body.md artifact."""
        return self.artifacts_dir / "pr_body.md"

    # State files
    @property
    def meta_json(self) -> Path:
        """Path to meta.json."""
        return self.run_dir / "meta.json"

    @property
    def state_json(self) -> Path:
        """Path to state.json."""
        return self.run_dir / "state.json"

    def prompt_path(self, stage: str) -> Path:
        """Get the path for a materialized prompt.

        Args:
            stage: The stage name (e.g., "plan", "spec", "implement").

        Returns:
            Path to the prompt file.
        """
        return self.prompts_dir / f"{stage}.md"

    def log_path(self, name: str, suffix: str = ".log") -> Path:
        """Get the path for a log file.

        Args:
            name: Base name for the log file.
            suffix: File suffix (default: .log).

        Returns:
            Path to the log file.
        """
        return self.logs_dir / f"{name}{suffix}"

    def agent_log_paths(
        self, stage: str, item_id: str | None = None, iteration: int | None = None
    ) -> tuple[Path, Path]:
        """Get stdout and stderr log paths for an agent execution.

        Args:
            stage: The stage name.
            item_id: Optional work item ID.
            iteration: Optional iteration number.

        Returns:
            Tuple of (stdout_path, stderr_path).
        """
        parts = [f"agent_{stage}"]
        if item_id:
            parts.append(f"item_{item_id}")
        if iteration is not None:
            parts.append(f"iter_{iteration}")
        base = "_".join(parts)
        return (
            self.logs_dir / f"{base}.stdout.log",
            self.logs_dir / f"{base}.stderr.log",
        )

    def create_directories(self) -> None:
        """Create all directories for the run.

        This is idempotent - can be called multiple times safely.
        """
        self.context_dir.mkdir(parents=True, exist_ok=True)
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        self._created = True

    def validate(self) -> bool:
        """Validate that the run directory structure exists.

        Returns:
            True if all required directories exist.
        """
        return all(
            d.exists()
            for d in [
                self.run_dir,
                self.context_dir,
                self.prompts_dir,
                self.artifacts_dir,
                self.logs_dir,
            ]
        )

    @classmethod
    def create_new(cls, base_dir: Path, run_id: str | None = None) -> RunPaths:
        """Create a new RunPaths instance and initialize directories.

        Args:
            base_dir: The base directory for runs.
            run_id: Optional run ID (generated if not provided).

        Returns:
            A new RunPaths instance with directories created.
        """
        if run_id is None:
            run_id = generate_run_id()
        paths = cls(base_dir=base_dir, run_id=run_id)
        paths.create_directories()
        return paths

    @classmethod
    def from_existing(cls, base_dir: Path, run_id: str) -> RunPaths:
        """Load an existing run's paths.

        Args:
            base_dir: The base directory for runs.
            run_id: The run ID to load.

        Returns:
            A RunPaths instance for the existing run.

        Raises:
            ValueError: If the run directory doesn't exist or is invalid.
        """
        paths = cls(base_dir=base_dir, run_id=run_id)
        if not paths.run_dir.exists():
            msg = f"Run directory does not exist: {paths.run_dir}"
            raise ValueError(msg)
        if not paths.validate():
            msg = f"Run directory structure is incomplete: {paths.run_dir}"
            raise ValueError(msg)
        return paths
