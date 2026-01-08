"""Pydantic schemas for metrics data."""

from __future__ import annotations

import hashlib
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class StageStatus(str, Enum):
    """Status of a stage execution."""

    SUCCESS = "success"
    FAIL = "fail"
    CANCEL = "cancel"
    TIMEOUT = "timeout"
    SKIP = "skip"


class FailureCategory(str, Enum):
    """Category of failure for a stage."""

    EXECUTOR_ERROR = "executor_error"
    GATE_FAILURE = "gate_failure"
    GUARDRAIL_VIOLATION = "guardrail_violation"
    TIMEOUT = "timeout"
    PARSE_ERROR = "parse_error"
    EMPTY_DIFF = "empty_diff"
    MAX_ATTEMPTS = "max_attempts"
    UNKNOWN = "unknown"


class GateMetrics(BaseModel):
    """Metrics for a single gate execution.

    Attributes:
        name: Gate name (ruff, pytest, docker).
        exit_code: Exit code from the gate.
        duration_ms: Time taken in milliseconds.
        passed: Whether the gate passed.
        tests_failed: Number of failed tests (pytest only).
        tests_total: Total number of tests (pytest only).
        error_output: Tail of error output if failed.
    """

    name: str
    exit_code: int
    duration_ms: int
    passed: bool
    tests_failed: int | None = None
    tests_total: int | None = None
    error_output: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = {
            "name": self.name,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "passed": self.passed,
        }
        if self.tests_failed is not None:
            data["tests_failed"] = self.tests_failed
        if self.tests_total is not None:
            data["tests_total"] = self.tests_total
        if self.error_output:
            data["error_output"] = self.error_output
        return data


class DiffStats(BaseModel):
    """Statistics about code changes.

    Attributes:
        files_changed: Number of files changed.
        lines_added: Number of lines added.
        lines_removed: Number of lines removed.
        files_list: List of changed file paths.
    """

    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    files_list: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "files_changed": self.files_changed,
            "lines_added": self.lines_added,
            "lines_removed": self.lines_removed,
            "files_list": self.files_list,
        }

    @classmethod
    def from_diff(cls, diff_content: str) -> DiffStats:
        """Parse diff statistics from git diff output.

        Args:
            diff_content: Git diff output.

        Returns:
            DiffStats with parsed statistics.
        """
        if not diff_content.strip():
            return cls()

        lines_added = 0
        lines_removed = 0
        files: set[str] = set()

        for line in diff_content.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                # File header - extract filename
                parts = line.split()
                if len(parts) >= 2:
                    path = parts[1]
                    if path.startswith("a/") or path.startswith("b/"):
                        path = path[2:]
                    if path != "/dev/null":
                        files.add(path)
            elif line.startswith("+") and not line.startswith("+++"):
                lines_added += 1
            elif line.startswith("-") and not line.startswith("---"):
                lines_removed += 1

        return cls(
            files_changed=len(files),
            lines_added=lines_added,
            lines_removed=lines_removed,
            files_list=sorted(files),
        )


class QualityMetrics(BaseModel):
    """Quality metrics for stage output.

    Attributes:
        spec_quality: Spec quality score (0.0-1.0).
        has_acceptance_criteria: Whether spec has AC.
        has_file_shortlist: Whether spec has file hints.
        schema_valid: Whether output matches expected schema.
        diff_within_limits: Whether diff is within size limits.
        gates_passed_first_attempt: Whether gates passed on first try.
        pack_files_count: Number of files in context pack.
        pack_chars: Character count of context pack.
        pack_signal_ratio: Ratio of pack files that were modified.
    """

    spec_quality: float | None = None
    has_acceptance_criteria: bool | None = None
    has_file_shortlist: bool | None = None
    schema_valid: bool | None = None
    diff_within_limits: bool | None = None
    gates_passed_first_attempt: bool | None = None
    pack_files_count: int | None = None
    pack_chars: int | None = None
    pack_signal_ratio: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in self.model_dump().items() if v is not None}


class StageMetrics(BaseModel):
    """Metrics for a single stage execution attempt.

    This is the core record written to stages.jsonl.
    Each record = one stage attempt.

    Attributes:
        run_id: Run identifier.
        stage: Stage name (plan/spec/decompose/implement/verify/review/fix/ship).
        item_id: Work item ID (for implement/fix/verify).
        attempt: Attempt number (1..N).
        start_ts: Start timestamp ISO format.
        end_ts: End timestamp ISO format.
        duration_ms: Duration in milliseconds.
        status: Execution status.
        failure_category: Category if failed.
        failure_message: Error message if failed.
        executor: Executor used (codex/gemini/fake).
        model: Model used.
        profile: Profile used.
        reasoning_effort: Reasoning effort level.
        inputs_fingerprint: Hash of inputs.
        outputs_fingerprint: Hash of outputs.
        artifacts: Dict of artifact paths.
        diff_stats: Diff statistics.
        gates: List of gate metrics.
        quality: Quality metrics.
        agent_invocations: Number of agent CLI invocations.
        llm_duration_ms: Time spent in LLM calls.
        verify_duration_ms: Time spent in verification.
    """

    run_id: str
    stage: str
    item_id: str | None = None
    attempt: int = 1
    start_ts: str
    end_ts: str
    duration_ms: int
    status: StageStatus = StageStatus.SUCCESS
    failure_category: FailureCategory | None = None
    failure_message: str | None = None
    executor: str | None = None
    model: str | None = None
    profile: str | None = None
    reasoning_effort: str | None = None
    inputs_fingerprint: str | None = None
    outputs_fingerprint: str | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    diff_stats: DiffStats | None = None
    gates: list[GateMetrics] = Field(default_factory=list)
    quality: QualityMetrics | None = None
    agent_invocations: int = 1
    llm_duration_ms: int | None = None
    verify_duration_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data: dict[str, Any] = {
            "run_id": self.run_id,
            "stage": self.stage,
            "attempt": self.attempt,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "duration_ms": self.duration_ms,
            "status": self.status.value,
        }

        if self.item_id:
            data["item_id"] = self.item_id
        if self.failure_category:
            data["failure_category"] = self.failure_category.value
        if self.failure_message:
            data["failure_message"] = self.failure_message
        if self.executor:
            data["executor"] = self.executor
        if self.model:
            data["model"] = self.model
        if self.profile:
            data["profile"] = self.profile
        if self.reasoning_effort:
            data["reasoning_effort"] = self.reasoning_effort
        if self.inputs_fingerprint:
            data["inputs_fingerprint"] = self.inputs_fingerprint
        if self.outputs_fingerprint:
            data["outputs_fingerprint"] = self.outputs_fingerprint
        if self.artifacts:
            data["artifacts"] = self.artifacts
        if self.diff_stats:
            data["diff_stats"] = self.diff_stats.to_dict()
        if self.gates:
            data["gates"] = [g.to_dict() for g in self.gates]
        if self.quality:
            data["quality"] = self.quality.to_dict()
        if self.agent_invocations > 1:
            data["agent_invocations"] = self.agent_invocations
        if self.llm_duration_ms is not None:
            data["llm_duration_ms"] = self.llm_duration_ms
        if self.verify_duration_ms is not None:
            data["verify_duration_ms"] = self.verify_duration_ms

        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StageMetrics:
        """Create from dictionary."""
        # Handle enums
        if "status" in data and isinstance(data["status"], str):
            data["status"] = StageStatus(data["status"])
        if "failure_category" in data and isinstance(data["failure_category"], str):
            data["failure_category"] = FailureCategory(data["failure_category"])

        # Handle nested objects
        if "diff_stats" in data and isinstance(data["diff_stats"], dict):
            data["diff_stats"] = DiffStats(**data["diff_stats"])
        if "gates" in data:
            data["gates"] = [
                GateMetrics(**g) if isinstance(g, dict) else g for g in data["gates"]
            ]
        if "quality" in data and isinstance(data["quality"], dict):
            data["quality"] = QualityMetrics(**data["quality"])

        return cls(**data)


class RunMetrics(BaseModel):
    """Aggregated metrics for an entire run.

    Attributes:
        run_id: Run identifier.
        task_fingerprint: Hash of the task.
        start_ts: Run start timestamp.
        end_ts: Run end timestamp.
        total_duration_ms: Total run duration.
        final_status: Final run status.
        final_failure_reason: Reason if failed.
        engine: Primary engine used.
        model: Primary model used.
        base_branch: Base branch.
        stages_executed: Number of stages executed.
        stages_failed: Number of stages that failed.
        time_to_green_ms: Time until first green gates.
        time_to_pr_ms: Time until PR ready.
        total_stage_time_ms: Sum of all stage durations.
        total_llm_time_ms: Sum of all LLM call durations.
        total_verify_time_ms: Sum of all verify durations.
        fix_attempts_total: Total fix attempts across all items.
        items_total: Total work items.
        items_completed: Successfully completed items.
        items_failed: Failed items.
        rework_ratio: Ratio of stages that needed retries.
        final_diff_stats: Final diff statistics.
        stage_breakdown: Time breakdown by stage.
    """

    run_id: str
    task_fingerprint: str | None = None
    start_ts: str
    end_ts: str | None = None
    total_duration_ms: int | None = None
    final_status: StageStatus = StageStatus.SUCCESS
    final_failure_reason: str | None = None
    engine: str | None = None
    model: str | None = None
    base_branch: str | None = None
    stages_executed: int = 0
    stages_failed: int = 0
    time_to_green_ms: int | None = None
    time_to_pr_ms: int | None = None
    total_stage_time_ms: int = 0
    total_llm_time_ms: int = 0
    total_verify_time_ms: int = 0
    fix_attempts_total: int = 0
    items_total: int = 0
    items_completed: int = 0
    items_failed: int = 0
    rework_ratio: float = 0.0
    final_diff_stats: DiffStats | None = None
    stage_breakdown: dict[str, int] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data: dict[str, Any] = {
            "run_id": self.run_id,
            "start_ts": self.start_ts,
            "final_status": self.final_status.value,
            "stages_executed": self.stages_executed,
            "stages_failed": self.stages_failed,
            "total_stage_time_ms": self.total_stage_time_ms,
            "total_llm_time_ms": self.total_llm_time_ms,
            "total_verify_time_ms": self.total_verify_time_ms,
            "fix_attempts_total": self.fix_attempts_total,
            "items_total": self.items_total,
            "items_completed": self.items_completed,
            "items_failed": self.items_failed,
            "rework_ratio": self.rework_ratio,
            "stage_breakdown": self.stage_breakdown,
        }

        if self.task_fingerprint:
            data["task_fingerprint"] = self.task_fingerprint
        if self.end_ts:
            data["end_ts"] = self.end_ts
        if self.total_duration_ms is not None:
            data["total_duration_ms"] = self.total_duration_ms
        if self.final_failure_reason:
            data["final_failure_reason"] = self.final_failure_reason
        if self.engine:
            data["engine"] = self.engine
        if self.model:
            data["model"] = self.model
        if self.base_branch:
            data["base_branch"] = self.base_branch
        if self.time_to_green_ms is not None:
            data["time_to_green_ms"] = self.time_to_green_ms
        if self.time_to_pr_ms is not None:
            data["time_to_pr_ms"] = self.time_to_pr_ms
        if self.final_diff_stats:
            data["final_diff_stats"] = self.final_diff_stats.to_dict()

        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunMetrics:
        """Create from dictionary."""
        if "final_status" in data and isinstance(data["final_status"], str):
            data["final_status"] = StageStatus(data["final_status"])
        if "final_diff_stats" in data and isinstance(data["final_diff_stats"], dict):
            data["final_diff_stats"] = DiffStats(**data["final_diff_stats"])
        return cls(**data)


def compute_fingerprint(*contents: str | bytes | Path) -> str:
    """Compute a fingerprint hash of the given contents.

    Args:
        *contents: Strings, bytes, or Paths to hash.

    Returns:
        Short hex fingerprint (16 chars).
    """
    hasher = hashlib.sha256()
    for content in contents:
        if isinstance(content, Path):
            content = content.read_bytes() if content.exists() else b""
        if isinstance(content, str):
            content = content.encode("utf-8")
        hasher.update(content)
    return hasher.hexdigest()[:16]
