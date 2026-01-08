"""Metrics collector for tracking stage execution."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from orx.metrics.schema import (
    DiffStats,
    FailureCategory,
    GateMetrics,
    QualityMetrics,
    RunMetrics,
    StageMetrics,
    StageStatus,
    compute_fingerprint,
)

if TYPE_CHECKING:
    from orx.config import ModelSelector
    from orx.gates.base import GateResult

logger = structlog.get_logger()


@dataclass
class StageTimer:
    """Timer for tracking stage duration.

    Attributes:
        stage: Stage name.
        item_id: Optional work item ID.
        attempt: Attempt number.
        start_time: Start timestamp.
        end_time: End timestamp.
        llm_start: LLM call start time.
        verify_start: Verify start time.
        llm_duration_ms: Total LLM duration.
        verify_duration_ms: Total verify duration.
    """

    stage: str
    item_id: str | None = None
    attempt: int = 1
    start_time: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    end_time: datetime | None = None
    _llm_start: float | None = field(default=None, repr=False)
    _verify_start: float | None = field(default=None, repr=False)
    llm_duration_ms: int = 0
    verify_duration_ms: int = 0

    def start_llm(self) -> None:
        """Mark start of LLM call."""
        self._llm_start = time.perf_counter()

    def end_llm(self) -> None:
        """Mark end of LLM call and accumulate duration."""
        if self._llm_start is not None:
            elapsed = (time.perf_counter() - self._llm_start) * 1000
            self.llm_duration_ms += int(elapsed)
            self._llm_start = None

    def start_verify(self) -> None:
        """Mark start of verification."""
        self._verify_start = time.perf_counter()

    def end_verify(self) -> None:
        """Mark end of verification and accumulate duration."""
        if self._verify_start is not None:
            elapsed = (time.perf_counter() - self._verify_start) * 1000
            self.verify_duration_ms += int(elapsed)
            self._verify_start = None

    def stop(self) -> None:
        """Stop the timer."""
        self.end_time = datetime.now(tz=UTC)

    @property
    def duration_ms(self) -> int:
        """Get duration in milliseconds."""
        end = self.end_time or datetime.now(tz=UTC)
        delta = end - self.start_time
        return int(delta.total_seconds() * 1000)


class MetricsCollector:
    """Collects metrics during an orx run.

    This class tracks:
    - Stage-level metrics (timing, status, artifacts)
    - Gate metrics (timing, pass/fail)
    - Quality metrics (spec quality, diff hygiene)
    - Run-level aggregates

    Example:
        >>> collector = MetricsCollector(run_id="20240101_120000_abc12345")
        >>> with collector.stage("plan") as timer:
        ...     # Execute stage
        ...     timer.start_llm()
        ...     # ... LLM call ...
        ...     timer.end_llm()
        >>> collector.record_success()
        >>> # Later: collector.finish() and writer.write()
    """

    def __init__(
        self,
        run_id: str,
        *,
        engine: str | None = None,
        model: str | None = None,
        base_branch: str | None = None,
    ) -> None:
        """Initialize the metrics collector.

        Args:
            run_id: Run identifier.
            engine: Primary engine name.
            model: Primary model name.
            base_branch: Base branch.
        """
        self.run_id = run_id
        self._engine = engine
        self._model = model
        self._base_branch = base_branch
        self._start_ts = datetime.now(tz=UTC)
        self._stage_metrics: list[StageMetrics] = []
        self._current_timer: StageTimer | None = None
        self._current_stage_data: dict[str, Any] = {}
        self._first_green_ts: datetime | None = None
        self._pr_ready_ts: datetime | None = None
        self._fix_attempts: int = 0
        self._items_total: int = 0
        self._items_completed: int = 0
        self._items_failed: int = 0
        self._task_fingerprint: str | None = None
        self._log = logger.bind(run_id=run_id)

    @contextmanager
    def stage(
        self,
        stage: str,
        *,
        item_id: str | None = None,
        attempt: int = 1,
    ) -> Iterator[StageTimer]:
        """Context manager for tracking a stage execution.

        Args:
            stage: Stage name.
            item_id: Optional work item ID.
            attempt: Attempt number.

        Yields:
            StageTimer for tracking sub-timings.

        Example:
            >>> with collector.stage("implement", item_id="W001", attempt=1) as timer:
            ...     timer.start_llm()
            ...     result = executor.run_apply(...)
            ...     timer.end_llm()
        """
        timer = StageTimer(stage=stage, item_id=item_id, attempt=attempt)
        self._current_timer = timer
        self._current_stage_data = {
            "stage": stage,
            "item_id": item_id,
            "attempt": attempt,
        }

        try:
            yield timer
        finally:
            timer.stop()
            self._current_timer = None

    def record_model_selection(
        self,
        executor: str,
        model: str | None = None,
        profile: str | None = None,
        reasoning_effort: str | None = None,
        model_selector: ModelSelector | None = None,
    ) -> None:
        """Record the model selection for the current stage.

        Args:
            executor: Executor name.
            model: Model name.
            profile: Profile name.
            reasoning_effort: Reasoning effort level.
            model_selector: Optional ModelSelector to extract from.
        """
        if model_selector:
            model = model_selector.model or model
            profile = model_selector.profile or profile
            reasoning_effort = model_selector.reasoning_effort or reasoning_effort

        self._current_stage_data.update({
            "executor": executor,
            "model": model,
            "profile": profile,
            "reasoning_effort": reasoning_effort,
        })

    def record_artifacts(self, artifacts: dict[str, Path | str]) -> None:
        """Record artifact paths for the current stage.

        Args:
            artifacts: Dict of artifact name to path.
        """
        self._current_stage_data["artifacts"] = {
            k: str(v) for k, v in artifacts.items()
        }

    def record_inputs_fingerprint(self, *contents: str | bytes | Path) -> None:
        """Record fingerprint of stage inputs.

        Args:
            *contents: Content to fingerprint.
        """
        self._current_stage_data["inputs_fingerprint"] = compute_fingerprint(*contents)

    def record_outputs_fingerprint(self, *contents: str | bytes | Path) -> None:
        """Record fingerprint of stage outputs.

        Args:
            *contents: Content to fingerprint.
        """
        self._current_stage_data["outputs_fingerprint"] = compute_fingerprint(
            *contents
        )

    def record_diff_stats(self, diff_content: str) -> None:
        """Record diff statistics.

        Args:
            diff_content: Git diff output.
        """
        self._current_stage_data["diff_stats"] = DiffStats.from_diff(diff_content)

    def record_gate(
        self,
        name: str,
        result: GateResult,
        duration_ms: int,
        tests_failed: int | None = None,
        tests_total: int | None = None,
    ) -> None:
        """Record a gate execution.

        Args:
            name: Gate name.
            result: GateResult from gate execution.
            duration_ms: Duration in milliseconds.
            tests_failed: Number of failed tests (pytest).
            tests_total: Total number of tests (pytest).
        """
        gates = self._current_stage_data.setdefault("gates", [])
        error_output = None
        if result.failed:
            error_output = result.get_log_tail(20)

        gates.append(GateMetrics(
            name=name,
            exit_code=result.returncode,
            duration_ms=duration_ms,
            passed=result.ok,
            tests_failed=tests_failed,
            tests_total=tests_total,
            error_output=error_output,
        ))

    def record_quality(self, quality: QualityMetrics | None = None, **kwargs: Any) -> None:
        """Record quality metrics for the current stage.

        Args:
            quality: Optional QualityMetrics object.
            **kwargs: Quality metric values.
        """
        if quality:
            self._current_stage_data["quality"] = quality
        elif kwargs:
            existing = self._current_stage_data.get("quality") or QualityMetrics()
            for k, v in kwargs.items():
                setattr(existing, k, v)
            self._current_stage_data["quality"] = existing

    def record_agent_invocations(self, count: int) -> None:
        """Record number of agent CLI invocations.

        Args:
            count: Number of invocations.
        """
        self._current_stage_data["agent_invocations"] = count

    def record_success(self) -> None:
        """Record current stage as successful and save metrics."""
        self._finalize_stage(StageStatus.SUCCESS)

    def record_failure(
        self,
        category: FailureCategory = FailureCategory.UNKNOWN,
        message: str | None = None,
    ) -> None:
        """Record current stage as failed and save metrics.

        Args:
            category: Failure category.
            message: Error message.
        """
        self._current_stage_data["failure_category"] = category
        self._current_stage_data["failure_message"] = message
        self._finalize_stage(StageStatus.FAIL)

    def record_timeout(self) -> None:
        """Record current stage as timed out."""
        self._current_stage_data["failure_category"] = FailureCategory.TIMEOUT
        self._finalize_stage(StageStatus.TIMEOUT)

    def record_skip(self) -> None:
        """Record current stage as skipped."""
        self._finalize_stage(StageStatus.SKIP)

    def mark_first_green(self) -> None:
        """Mark that gates have passed for the first time."""
        if self._first_green_ts is None:
            self._first_green_ts = datetime.now(tz=UTC)

    def mark_pr_ready(self) -> None:
        """Mark that PR is ready."""
        if self._pr_ready_ts is None:
            self._pr_ready_ts = datetime.now(tz=UTC)

    def add_fix_attempt(self) -> None:
        """Increment fix attempts counter."""
        self._fix_attempts += 1

    def set_items_count(
        self,
        total: int,
        completed: int = 0,
        failed: int = 0,
    ) -> None:
        """Set work items counts.

        Args:
            total: Total items.
            completed: Completed items.
            failed: Failed items.
        """
        self._items_total = total
        self._items_completed = completed
        self._items_failed = failed

    def set_task_fingerprint(self, task: str | Path) -> None:
        """Set task fingerprint.

        Args:
            task: Task content or path.
        """
        self._task_fingerprint = compute_fingerprint(task)

    def _finalize_stage(self, status: StageStatus) -> None:
        """Finalize and save stage metrics.

        Args:
            status: Final stage status.
        """
        timer = self._current_timer
        if timer is None:
            self._log.warning("No timer active when finalizing stage")
            return

        # Ensure timer is stopped
        if timer.end_time is None:
            timer.stop()

        metrics = StageMetrics(
            run_id=self.run_id,
            stage=self._current_stage_data.get("stage", "unknown"),
            item_id=self._current_stage_data.get("item_id"),
            attempt=self._current_stage_data.get("attempt", 1),
            start_ts=timer.start_time.isoformat(),
            end_ts=timer.end_time.isoformat() if timer.end_time else "",
            duration_ms=timer.duration_ms,
            status=status,
            failure_category=self._current_stage_data.get("failure_category"),
            failure_message=self._current_stage_data.get("failure_message"),
            executor=self._current_stage_data.get("executor"),
            model=self._current_stage_data.get("model"),
            profile=self._current_stage_data.get("profile"),
            reasoning_effort=self._current_stage_data.get("reasoning_effort"),
            inputs_fingerprint=self._current_stage_data.get("inputs_fingerprint"),
            outputs_fingerprint=self._current_stage_data.get("outputs_fingerprint"),
            artifacts=self._current_stage_data.get("artifacts", {}),
            diff_stats=self._current_stage_data.get("diff_stats"),
            gates=self._current_stage_data.get("gates", []),
            quality=self._current_stage_data.get("quality"),
            agent_invocations=self._current_stage_data.get("agent_invocations", 1),
            llm_duration_ms=timer.llm_duration_ms if timer.llm_duration_ms > 0 else None,
            verify_duration_ms=(
                timer.verify_duration_ms if timer.verify_duration_ms > 0 else None
            ),
        )

        self._stage_metrics.append(metrics)
        self._current_stage_data = {}

        self._log.debug(
            "Stage metrics recorded",
            stage=metrics.stage,
            status=status.value,
            duration_ms=metrics.duration_ms,
        )

    def get_stage_metrics(self) -> list[StageMetrics]:
        """Get all recorded stage metrics.

        Returns:
            List of StageMetrics.
        """
        return self._stage_metrics

    def build_run_metrics(
        self,
        *,
        final_status: StageStatus = StageStatus.SUCCESS,
        failure_reason: str | None = None,
        final_diff: str | None = None,
    ) -> RunMetrics:
        """Build aggregated run metrics.

        Args:
            final_status: Final run status.
            failure_reason: Failure reason if failed.
            final_diff: Final diff content.

        Returns:
            RunMetrics with aggregated data.
        """
        end_ts = datetime.now(tz=UTC)
        total_duration = int((end_ts - self._start_ts).total_seconds() * 1000)

        # Aggregate from stage metrics
        total_stage_time = sum(m.duration_ms for m in self._stage_metrics)
        total_llm_time = sum(m.llm_duration_ms or 0 for m in self._stage_metrics)
        total_verify_time = sum(m.verify_duration_ms or 0 for m in self._stage_metrics)
        stages_failed = sum(1 for m in self._stage_metrics if m.status == StageStatus.FAIL)

        # Stage breakdown
        stage_breakdown: dict[str, int] = {}
        for m in self._stage_metrics:
            stage_breakdown[m.stage] = stage_breakdown.get(m.stage, 0) + m.duration_ms

        # Compute rework ratio (stages with attempt > 1)
        rework_count = sum(1 for m in self._stage_metrics if m.attempt > 1)
        rework_ratio = rework_count / len(self._stage_metrics) if self._stage_metrics else 0.0

        # Time to green
        time_to_green = None
        if self._first_green_ts:
            delta = self._first_green_ts - self._start_ts
            time_to_green = int(delta.total_seconds() * 1000)

        # Time to PR
        time_to_pr = None
        if self._pr_ready_ts:
            delta = self._pr_ready_ts - self._start_ts
            time_to_pr = int(delta.total_seconds() * 1000)

        # Final diff stats
        final_diff_stats = None
        if final_diff:
            final_diff_stats = DiffStats.from_diff(final_diff)

        return RunMetrics(
            run_id=self.run_id,
            task_fingerprint=self._task_fingerprint,
            start_ts=self._start_ts.isoformat(),
            end_ts=end_ts.isoformat(),
            total_duration_ms=total_duration,
            final_status=final_status,
            final_failure_reason=failure_reason,
            engine=self._engine,
            model=self._model,
            base_branch=self._base_branch,
            stages_executed=len(self._stage_metrics),
            stages_failed=stages_failed,
            time_to_green_ms=time_to_green,
            time_to_pr_ms=time_to_pr,
            total_stage_time_ms=total_stage_time,
            total_llm_time_ms=total_llm_time,
            total_verify_time_ms=total_verify_time,
            fix_attempts_total=self._fix_attempts,
            items_total=self._items_total,
            items_completed=self._items_completed,
            items_failed=self._items_failed,
            rework_ratio=rework_ratio,
            final_diff_stats=final_diff_stats,
            stage_breakdown=stage_breakdown,
        )
