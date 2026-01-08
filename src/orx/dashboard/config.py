"""Dashboard configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings


class DashboardConfig(BaseSettings):
    """Configuration for the ORX Dashboard.

    Environment variables:
        ORX_RUNS_ROOT: Base directory containing runs/
        ORX_DASHBOARD_HOST: Host to bind (127.0.0.1 for security)
        ORX_DASHBOARD_PORT: Port to bind
        ORX_BIN: Path to orx CLI binary
        ORX_DASHBOARD_MAX_CONCURRENCY: Max concurrent runs
        ORX_DASHBOARD_LOG_TAIL_LINES: Default lines for log tail
    """

    # Paths
    runs_root: Path = Field(
        default_factory=lambda: Path.cwd() / "runs",
        validation_alias="ORX_RUNS_ROOT",
        description="Base directory containing runs/",
    )
    orx_bin: str = Field(
        default="orx",
        validation_alias="ORX_BIN",
        description="Path to orx CLI binary",
    )

    # Server
    host: str = Field(
        default="127.0.0.1",
        validation_alias="ORX_DASHBOARD_HOST",
        description="Host to bind (127.0.0.1 for security)",
    )
    port: int = Field(
        default=8000,
        validation_alias="ORX_DASHBOARD_PORT",
        description="Port to bind",
    )

    # Worker
    max_concurrency: int = Field(
        default=1,
        validation_alias="ORX_DASHBOARD_MAX_CONCURRENCY",
        description="Maximum concurrent runs",
    )
    cancel_grace_seconds: int = Field(
        default=5,
        description="Seconds to wait after SIGTERM before SIGKILL",
    )

    # UI
    log_tail_lines: int = Field(
        default=200,
        validation_alias="ORX_DASHBOARD_LOG_TAIL_LINES",
        description="Default number of lines for log tail",
    )
    poll_interval_active: int = Field(
        default=3,
        description="Polling interval for active runs (seconds)",
    )
    poll_interval_logs: int = Field(
        default=2,
        description="Polling interval for logs (seconds)",
    )

    # Security
    allowed_extensions: set[str] = Field(
        default={".md", ".json", ".log", ".diff", ".txt", ".yaml", ".yml"},
        description="File extensions allowed for preview",
    )
    allowed_dirs: set[str] = Field(
        default={"context", "artifacts", "logs", "metrics", "prompts"},
        description="Subdirectories allowed for file access",
    )

    model_config = {
        "env_prefix": "",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    def get_runs_dir(self) -> Path:
        """Get the runs directory path.

        Returns:
            Path to runs directory, checking multiple locations.
        """
        # Try configured path first
        if self.runs_root.exists():
            return self.runs_root

        # Try ~/.orx/runs
        home_runs = Path.home() / ".orx" / "runs"
        if home_runs.exists():
            return home_runs

        # Fall back to configured path (will be created if needed)
        return self.runs_root

    def is_path_allowed(self, run_dir: Path, relative_path: str) -> bool:
        """Check if a relative path is allowed for access.

        Args:
            run_dir: Base run directory.
            relative_path: Path relative to run directory.

        Returns:
            True if path is safe and allowed.
        """
        # Reject path traversal
        if ".." in relative_path:
            return False

        # Check extension
        path = Path(relative_path)
        if path.suffix.lower() not in self.allowed_extensions:
            return False

        # Check if in allowed subdirectory or root
        parts = path.parts
        if len(parts) > 1 and parts[0] not in self.allowed_dirs:
            return False

        # Verify resolved path stays within run_dir
        resolved = (run_dir / relative_path).resolve()
        try:
            resolved.relative_to(run_dir.resolve())
            return True
        except ValueError:
            return False
