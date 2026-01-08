"""Context pack for managing run artifacts."""

from __future__ import annotations

from pathlib import Path

from orx.paths import RunPaths


class ContextPack:
    """Manages reading and writing of context artifacts for a run.

    The ContextPack provides a high-level interface for working with
    the various markdown and yaml files that make up the run context.

    Attributes:
        paths: The RunPaths instance for this run.

    Example:
        >>> paths = RunPaths.create_new(Path("/project"), "test_run")
        >>> pack = ContextPack(paths)
        >>> pack.write_task("Implement feature X")
        >>> pack.read_task()
        'Implement feature X'
    """

    def __init__(self, paths: RunPaths) -> None:
        """Initialize the context pack.

        Args:
            paths: RunPaths instance for this run.
        """
        self.paths = paths

    def _read_file(self, path: Path) -> str | None:
        """Read a file, returning None if it doesn't exist."""
        if path.exists():
            return path.read_text()
        return None

    def _write_file(self, path: Path, content: str) -> None:
        """Write content to a file, creating parent dirs if needed."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    # Task
    def read_task(self) -> str | None:
        """Read the task description."""
        return self._read_file(self.paths.task_md)

    def write_task(self, content: str) -> None:
        """Write the task description."""
        self._write_file(self.paths.task_md, content)

    def task_exists(self) -> bool:
        """Check if task.md exists."""
        return self.paths.task_md.exists()

    # Plan
    def read_plan(self) -> str | None:
        """Read the plan."""
        return self._read_file(self.paths.plan_md)

    def write_plan(self, content: str) -> None:
        """Write the plan."""
        self._write_file(self.paths.plan_md, content)

    def plan_exists(self) -> bool:
        """Check if plan.md exists."""
        return self.paths.plan_md.exists()

    # Spec
    def read_spec(self) -> str | None:
        """Read the spec."""
        return self._read_file(self.paths.spec_md)

    def write_spec(self, content: str) -> None:
        """Write the spec."""
        self._write_file(self.paths.spec_md, content)

    def spec_exists(self) -> bool:
        """Check if spec.md exists."""
        return self.paths.spec_md.exists()

    # Project map
    def read_project_map(self) -> str | None:
        """Read the project map."""
        return self._read_file(self.paths.project_map_md)

    def write_project_map(self, content: str) -> None:
        """Write the project map."""
        self._write_file(self.paths.project_map_md, content)

    def project_map_exists(self) -> bool:
        """Check if project_map.md exists."""
        return self.paths.project_map_md.exists()

    # Decisions
    def read_decisions(self) -> str | None:
        """Read the decisions log."""
        return self._read_file(self.paths.decisions_md)

    def write_decisions(self, content: str) -> None:
        """Write the decisions log."""
        self._write_file(self.paths.decisions_md, content)

    def append_decision(self, decision: str) -> None:
        """Append a decision to the decisions log."""
        existing = self.read_decisions() or ""
        new_content = f"{existing}\n{decision}".strip() + "\n"
        self.write_decisions(new_content)

    # Lessons
    def read_lessons(self) -> str | None:
        """Read the lessons learned."""
        return self._read_file(self.paths.lessons_md)

    def write_lessons(self, content: str) -> None:
        """Write the lessons learned."""
        self._write_file(self.paths.lessons_md, content)

    def append_lesson(self, lesson: str) -> None:
        """Append a lesson to the lessons file."""
        existing = self.read_lessons() or ""
        new_content = f"{existing}\n{lesson}".strip() + "\n"
        self.write_lessons(new_content)

    # Repo Context Pack (tooling snapshot)
    def read_tooling_snapshot(self) -> str | None:
        """Read the tooling snapshot."""
        return self._read_file(self.paths.tooling_snapshot_md)

    def write_tooling_snapshot(self, content: str) -> None:
        """Write the tooling snapshot."""
        self._write_file(self.paths.tooling_snapshot_md, content)

    def tooling_snapshot_exists(self) -> bool:
        """Check if tooling_snapshot.md exists."""
        return self.paths.tooling_snapshot_md.exists()

    def read_verify_commands(self) -> str | None:
        """Read the verify commands."""
        return self._read_file(self.paths.verify_commands_md)

    def write_verify_commands(self, content: str) -> None:
        """Write the verify commands."""
        self._write_file(self.paths.verify_commands_md, content)

    def verify_commands_exists(self) -> bool:
        """Check if verify_commands.md exists."""
        return self.paths.verify_commands_md.exists()

    # Artifacts
    def read_patch_diff(self) -> str | None:
        """Read the patch diff."""
        return self._read_file(self.paths.patch_diff)

    def write_patch_diff(self, content: str) -> None:
        """Write the patch diff."""
        self._write_file(self.paths.patch_diff, content)

    def read_review(self) -> str | None:
        """Read the review."""
        return self._read_file(self.paths.review_md)

    def write_review(self, content: str) -> None:
        """Write the review."""
        self._write_file(self.paths.review_md, content)

    def read_pr_body(self) -> str | None:
        """Read the PR body."""
        return self._read_file(self.paths.pr_body_md)

    def write_pr_body(self, content: str) -> None:
        """Write the PR body."""
        self._write_file(self.paths.pr_body_md, content)

    # Prompts
    def read_prompt(self, stage: str) -> str | None:
        """Read a materialized prompt."""
        return self._read_file(self.paths.prompt_path(stage))

    def write_prompt(self, stage: str, content: str) -> None:
        """Write a materialized prompt."""
        self._write_file(self.paths.prompt_path(stage), content)

    # Logs
    def read_log(self, name: str) -> str | None:
        """Read a log file."""
        return self._read_file(self.paths.log_path(name))

    def log_exists(self, name: str) -> bool:
        """Check if a log file exists."""
        return self.paths.log_path(name).exists()

    def get_log_tail(self, name: str, lines: int = 50) -> str:
        """Get the tail of a log file.

        Args:
            name: Log file name.
            lines: Number of lines to return.

        Returns:
            The last N lines of the log, or empty string if not found.
        """
        content = self.read_log(name)
        if not content:
            return ""
        log_lines = content.splitlines()
        return "\n".join(log_lines[-lines:])

    # Summary helpers
    def get_context_summary(self) -> dict[str, bool]:
        """Get a summary of which context files exist.

        Returns:
            Dict mapping file names to existence status.
        """
        return {
            "task.md": self.task_exists(),
            "plan.md": self.plan_exists(),
            "spec.md": self.spec_exists(),
            "project_map.md": self.project_map_exists(),
            "backlog.yaml": self.paths.backlog_yaml.exists(),
            "tooling_snapshot.md": self.tooling_snapshot_exists(),
            "verify_commands.md": self.verify_commands_exists(),
        }

    def get_evidence_bundle(
        self,
        *,
        include_diff: bool = True,
        log_names: list[str] | None = None,
        log_tail_lines: int = 50,
    ) -> dict[str, str]:
        """Build an evidence bundle for fix prompts.

        Args:
            include_diff: Whether to include the patch diff.
            log_names: List of log names to include.
            log_tail_lines: Number of lines to include from each log.

        Returns:
            Dict with evidence content.
        """
        bundle: dict[str, str] = {}

        if include_diff:
            diff = self.read_patch_diff()
            if diff:
                bundle["patch_diff"] = diff

        for name in log_names or []:
            tail = self.get_log_tail(name, log_tail_lines)
            if tail:
                bundle[f"log_{name}"] = tail

        return bundle
