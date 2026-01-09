"""Evidence Pack collection for knowledge updates."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from orx.context.pack import ContextPack
from orx.knowledge.problems import ProblemsCollector, ProblemsSummary
from orx.paths import RunPaths

if TYPE_CHECKING:
    pass

logger = structlog.get_logger()


@dataclass
class EvidencePack:
    """Collection of evidence for knowledge update decisions.

    Contains all information needed for the Knowledge Architect
    to decide what to update in AGENTS.md and ARCHITECTURE.md.

    Attributes:
        spec: The specification/AC for the task.
        backlog_yaml: The backlog of work items.
        patch_diff: The git diff of changes made.
        changed_files: List of files changed.
        review: The review output (if available).
        gate_logs: Summary of gate execution logs.
        current_agents_md: Current contents of AGENTS.md.
        current_arch_md: Current contents of ARCHITECTURE.md.
        project_map: Project map (if available).
        decisions: Decisions log (if available).
        problems: Summary of problems encountered during run.
    """

    spec: str = ""
    backlog_yaml: str = ""
    patch_diff: str = ""
    changed_files: list[str] = field(default_factory=list)
    review: str = ""
    gate_logs: dict[str, str] = field(default_factory=dict)
    current_agents_md: str = ""
    current_arch_md: str = ""
    project_map: str = ""
    decisions: str = ""
    problems: ProblemsSummary | None = None

    def summary(self) -> str:
        """Generate a summary of the evidence pack for logging."""
        problems_info = ""
        if self.problems and self.problems.has_problems():
            problems_info = f", problems={len(self.problems.problems)}"
        return (
            f"EvidencePack: spec={len(self.spec)} chars, "
            f"patch={len(self.patch_diff)} chars, "
            f"changed_files={len(self.changed_files)}, "
            f"has_agents={bool(self.current_agents_md)}, "
            f"has_arch={bool(self.current_arch_md)}"
            f"{problems_info}"
        )


class EvidenceCollector:
    """Collects evidence for knowledge update stage.

    Gathers all relevant information from the run artifacts
    and target repository to create an EvidencePack.

    Example:
        >>> collector = EvidenceCollector(paths, pack, repo_root)
        >>> evidence = collector.collect()
        >>> evidence.changed_files
        ['src/app.py', 'tests/test_app.py']
    """

    def __init__(
        self,
        paths: RunPaths,
        pack: ContextPack,
        repo_root: Path,
    ) -> None:
        """Initialize the evidence collector.

        Args:
            paths: RunPaths for artifact locations.
            pack: ContextPack for reading context files.
            repo_root: Root of the target repository.
        """
        self.paths = paths
        self.pack = pack
        self.repo_root = repo_root

    def collect(self) -> EvidencePack:
        """Collect all evidence for knowledge update.

        Returns:
            EvidencePack with all collected evidence.
        """
        log = logger.bind(run_id=self.paths.run_id)
        log.info("Collecting evidence for knowledge update")

        # Collect problems from metrics
        problems_collector = ProblemsCollector(self.paths)
        problems = problems_collector.collect()

        evidence = EvidencePack(
            spec=self._read_spec(),
            backlog_yaml=self._read_backlog(),
            patch_diff=self._read_patch_diff(),
            changed_files=self._parse_changed_files(),
            review=self._read_review(),
            gate_logs=self._collect_gate_logs(),
            current_agents_md=self._read_repo_file("AGENTS.md"),
            current_arch_md=self._read_repo_file("ARCHITECTURE.md"),
            project_map=self.pack.read_project_map() or "",
            decisions=self.pack.read_decisions() or "",
            problems=problems,
        )

        log.info("Evidence collected", summary=evidence.summary())
        return evidence

    def _read_spec(self) -> str:
        """Read the specification from context."""
        return self.pack.read_spec() or ""

    def _read_backlog(self) -> str:
        """Read the backlog YAML."""
        backlog_path = self.paths.backlog_yaml
        if backlog_path.exists():
            return backlog_path.read_text()
        return ""

    def _read_patch_diff(self) -> str:
        """Read the patch.diff artifact."""
        if self.paths.patch_diff.exists():
            return self.paths.patch_diff.read_text()
        return ""

    def _parse_changed_files(self) -> list[str]:
        """Parse list of changed files from patch.diff."""
        patch = self._read_patch_diff()
        if not patch:
            return []

        files: list[str] = []
        for line in patch.split("\n"):
            if line.startswith("diff --git"):
                # Format: diff --git a/path/to/file b/path/to/file
                parts = line.split(" ")
                if len(parts) >= 4:
                    # Extract b/path/to/file and remove b/ prefix
                    file_path = parts[3]
                    if file_path.startswith("b/"):
                        file_path = file_path[2:]
                    files.append(file_path)
        return files

    def _read_review(self) -> str:
        """Read the review artifact."""
        review_path = self.paths.artifacts / "review.md"
        if review_path.exists():
            return review_path.read_text()
        return ""

    def _collect_gate_logs(self, tail_lines: int = 50) -> dict[str, str]:
        """Collect tail of gate logs.

        Args:
            tail_lines: Number of lines to include from each log.

        Returns:
            Dict mapping gate name to log tail.
        """
        logs: dict[str, str] = {}
        logs_dir = self.paths.logs

        if not logs_dir.exists():
            return logs

        for log_file in logs_dir.glob("*.log"):
            gate_name = log_file.stem
            content = log_file.read_text()
            lines = content.splitlines()
            tail = lines[-tail_lines:] if len(lines) > tail_lines else lines
            logs[gate_name] = "\n".join(tail)

        return logs

    def _read_repo_file(self, filename: str) -> str:
        """Read a file from the repository root.

        Args:
            filename: Name of the file to read.

        Returns:
            File contents, or empty string if not found.
        """
        file_path = self.repo_root / filename
        if file_path.exists():
            return file_path.read_text()
        return ""
