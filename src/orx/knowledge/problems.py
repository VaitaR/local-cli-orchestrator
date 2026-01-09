"""Problems extraction from run metrics for knowledge updates.

This module extracts problem patterns from stages.jsonl to provide
actionable data for AGENTS.md and ARCHITECTURE.md updates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import structlog

from orx.paths import RunPaths

logger = structlog.get_logger()


@dataclass
class StageProblem:
    """A problem encountered during a stage execution.

    Attributes:
        stage: Stage name (plan/spec/decompose/implement/fix/verify).
        category: Failure category (gate_failure, parse_error, timeout, etc).
        message: Human-readable error message.
        attempt: Attempt number when problem occurred.
        gate_name: Gate name if gate_failure.
        error_output: Relevant error output (truncated).
        suggested_fix: Auto-generated suggestion if available.
    """

    stage: str
    category: str
    message: str
    attempt: int = 1
    item_id: str | None = None
    gate_name: str | None = None
    error_output: str | None = None
    suggested_fix: str | None = None

    def to_summary(self) -> str:
        """Generate a one-line summary of the problem."""
        parts = [f"[{self.stage}:{self.category}]"]
        if self.gate_name:
            parts.append(f"({self.gate_name})")
        if self.item_id:
            parts.append(f"item={self.item_id}")
        parts.append(self.message[:100])
        return " ".join(parts)


@dataclass
class FixAttempt:
    """A fix attempt and its outcome.

    Tracks what was tried and whether it worked.
    """

    item_id: str
    attempt: int
    trigger: str  # What triggered the fix (ruff, pytest, etc)
    succeeded: bool
    duration_ms: int
    error_before: str | None = None


@dataclass
class ProblemsSummary:
    """Summary of all problems encountered in a run.

    Provides structured data for knowledge update prompts.
    """

    problems: list[StageProblem] = field(default_factory=list)
    fix_attempts: list[FixAttempt] = field(default_factory=list)
    gate_failures: dict[str, int] = field(default_factory=dict)  # gate -> count
    failure_categories: dict[str, int] = field(
        default_factory=dict
    )  # category -> count
    total_fix_iterations: int = 0
    stages_failed: int = 0
    stages_retried: int = 0

    def has_problems(self) -> bool:
        """Check if any problems were encountered."""
        return bool(self.problems) or self.total_fix_iterations > 0

    def to_prompt_section(self, max_problems: int = 10) -> str:
        """Generate a markdown section for prompts.

        Args:
            max_problems: Maximum number of problems to include.

        Returns:
            Markdown-formatted problems section.
        """
        if not self.has_problems():
            return "No significant problems encountered during this run."

        lines = ["## Problems Encountered During Run\n"]

        # Summary stats
        lines.append("### Run Statistics")
        lines.append(f"- Stages that failed: {self.stages_failed}")
        lines.append(f"- Fix iterations needed: {self.total_fix_iterations}")
        if self.gate_failures:
            lines.append(
                "- Gate failures: "
                + ", ".join(f"{g}={c}" for g, c in sorted(self.gate_failures.items()))
            )
        if self.failure_categories:
            lines.append(
                "- Failure categories: "
                + ", ".join(
                    f"{c}={n}" for c, n in sorted(self.failure_categories.items())
                )
            )
        lines.append("")

        # Problem details
        if self.problems:
            lines.append("### Problem Details")
            for i, prob in enumerate(self.problems[:max_problems], 1):
                lines.append(f"\n**Problem {i}:** `{prob.stage}` → `{prob.category}`")
                if prob.gate_name:
                    lines.append(f"- Gate: {prob.gate_name}")
                lines.append(f"- Message: {prob.message}")
                if prob.error_output:
                    # Truncate error output
                    err = prob.error_output[:500]
                    lines.append(f"- Error snippet:\n```\n{err}\n```")
                if prob.suggested_fix:
                    lines.append(f"- Suggested fix: {prob.suggested_fix}")

            if len(self.problems) > max_problems:
                lines.append(
                    f"\n... and {len(self.problems) - max_problems} more problems"
                )

        # Fix attempts summary
        if self.fix_attempts:
            lines.append("\n### Fix Attempts")
            succeeded = sum(1 for f in self.fix_attempts if f.succeeded)
            failed = len(self.fix_attempts) - succeeded
            lines.append(f"- Total attempts: {len(self.fix_attempts)}")
            lines.append(f"- Succeeded: {succeeded}, Failed: {failed}")

            # Show fix triggers
            triggers = {}
            for fa in self.fix_attempts:
                triggers[fa.trigger] = triggers.get(fa.trigger, 0) + 1
            if triggers:
                lines.append(
                    "- Triggers: "
                    + ", ".join(f"{t}={c}" for t, c in sorted(triggers.items()))
                )

        return "\n".join(lines)

    def get_lessons_learned(self) -> list[str]:
        """Generate lessons learned from problems.

        Returns:
            List of lesson strings.
        """
        lessons = []

        # Pattern: Multiple fix attempts on same gate
        for gate, count in self.gate_failures.items():
            if count >= 2:
                lessons.append(
                    f"Gate `{gate}` failed {count} times. "
                    "Consider checking output before running gates."
                )

        # Pattern: Parse errors
        parse_errors = self.failure_categories.get("parse_error", 0)
        if parse_errors > 0:
            lessons.append(
                f"Parse errors occurred {parse_errors} times. "
                "Ensure output format matches expected schema."
            )

        # Pattern: Timeout
        timeouts = self.failure_categories.get("timeout", 0)
        if timeouts > 0:
            lessons.append(
                f"Timeout occurred {timeouts} times. "
                "Consider breaking down large tasks."
            )

        # Pattern: Empty diff
        empty_diffs = self.failure_categories.get("empty_diff", 0)
        if empty_diffs > 0:
            lessons.append(
                f"Empty diff occurred {empty_diffs} times. "
                "Ensure agent actually modifies files."
            )

        return lessons


class ProblemsCollector:
    """Collects and analyzes problems from run metrics.

    Reads stages.jsonl and extracts problem patterns for
    knowledge update stage.

    Example:
        >>> collector = ProblemsCollector(paths)
        >>> summary = collector.collect()
        >>> print(summary.to_prompt_section())
    """

    def __init__(self, paths: RunPaths) -> None:
        """Initialize problems collector.

        Args:
            paths: RunPaths for locating metrics files.
        """
        self.paths = paths

    def collect(self) -> ProblemsSummary:
        """Collect problems from stages.jsonl.

        Returns:
            ProblemsSummary with all extracted problems.
        """
        log = logger.bind(run_id=self.paths.run_id)
        log.debug("Collecting problems from stages.jsonl")

        summary = ProblemsSummary()
        stages_jsonl = self.paths.metrics / "stages.jsonl"

        if not stages_jsonl.exists():
            log.debug("No stages.jsonl found")
            return summary

        # Track stages for retry detection
        stage_attempts: dict[str, int] = {}  # stage+item_id -> max attempt

        for line in stages_jsonl.read_text().splitlines():
            if not line.strip():
                continue

            try:
                record = json.loads(line)
                self._process_stage_record(record, summary, stage_attempts)
            except json.JSONDecodeError:
                log.warning("Invalid JSON in stages.jsonl", line=line[:100])
                continue

        # Calculate stages retried
        summary.stages_retried = sum(
            1 for max_attempt in stage_attempts.values() if max_attempt > 1
        )

        log.info(
            "Problems collected",
            problems=len(summary.problems),
            fix_attempts=len(summary.fix_attempts),
            stages_failed=summary.stages_failed,
        )

        return summary

    def _process_stage_record(
        self,
        record: dict[str, Any],
        summary: ProblemsSummary,
        stage_attempts: dict[str, int],
    ) -> None:
        """Process a single stage record.

        Args:
            record: Stage metrics record.
            summary: ProblemsSummary to update.
            stage_attempts: Dict tracking attempts per stage.
        """
        stage = record.get("stage", "unknown")
        item_id = record.get("item_id")
        attempt = record.get("attempt", 1)
        status = record.get("status", "unknown")

        # Track attempts
        key = f"{stage}:{item_id or 'none'}"
        stage_attempts[key] = max(stage_attempts.get(key, 0), attempt)

        # Process failures
        if status == "fail":
            summary.stages_failed += 1
            self._extract_problem(record, summary)

        # Process gate results
        gates = record.get("gates", [])
        for gate in gates:
            if not gate.get("passed", True):
                gate_name = gate.get("name", "unknown")
                summary.gate_failures[gate_name] = (
                    summary.gate_failures.get(gate_name, 0) + 1
                )

        # Track fix iterations
        if stage == "fix":
            summary.total_fix_iterations += 1
            self._extract_fix_attempt(record, summary)

    def _extract_problem(
        self,
        record: dict[str, Any],
        summary: ProblemsSummary,
    ) -> None:
        """Extract a problem from a failed stage record.

        Args:
            record: Stage metrics record.
            summary: ProblemsSummary to update.
        """
        category = record.get("failure_category", "unknown")
        message = record.get("failure_message", "No message")

        # Track category
        summary.failure_categories[category] = (
            summary.failure_categories.get(category, 0) + 1
        )

        # Extract error output from gates
        error_output = None
        gates = record.get("gates", [])
        for gate in gates:
            if not gate.get("passed", True) and gate.get("error_output"):
                error_output = gate["error_output"]
                break

        # Check error_info for more details
        error_info = record.get("error_info", {})
        if error_info and not error_output:
            error_output = error_info.get("stack_trace") or error_info.get(
                "details", {}
            ).get("output")

        problem = StageProblem(
            stage=record.get("stage", "unknown"),
            category=category,
            message=message,
            attempt=record.get("attempt", 1),
            item_id=record.get("item_id"),
            gate_name=self._get_failed_gate_name(record),
            error_output=error_output,
            suggested_fix=error_info.get("suggested_action") if error_info else None,
        )
        summary.problems.append(problem)

    def _extract_fix_attempt(
        self,
        record: dict[str, Any],
        summary: ProblemsSummary,
    ) -> None:
        """Extract a fix attempt from a fix stage record.

        Args:
            record: Stage metrics record (fix stage).
            summary: ProblemsSummary to update.
        """
        # Determine trigger from gate failures
        trigger = "unknown"
        gates = record.get("gates", [])
        for gate in gates:
            if not gate.get("passed", True):
                trigger = gate.get("name", "unknown")
                break

        # If no gates, check failure category
        if trigger == "unknown":
            category = record.get("failure_category")
            if category:
                trigger = category

        fix_attempt = FixAttempt(
            item_id=record.get("item_id", "unknown"),
            attempt=record.get("attempt", 1),
            trigger=trigger,
            succeeded=record.get("status") == "success",
            duration_ms=record.get("duration_ms", 0),
            error_before=record.get("failure_message"),
        )
        summary.fix_attempts.append(fix_attempt)

    def _get_failed_gate_name(self, record: dict[str, Any]) -> str | None:
        """Get the name of the first failed gate.

        Args:
            record: Stage metrics record.

        Returns:
            Gate name or None.
        """
        gates = record.get("gates", [])
        for gate in gates:
            if not gate.get("passed", True):
                return gate.get("name")
        return None
