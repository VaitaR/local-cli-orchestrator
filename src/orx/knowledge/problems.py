"""Problems extraction from observability v2 events for knowledge updates."""

from __future__ import annotations

import json
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from orx.paths import RunPaths

logger = structlog.get_logger()


def _event_ref(event: dict[str, Any]) -> str:
    event_id = str(event.get("event_id") or "unknown")
    step_id = int(event.get("step_id") or 0)
    return f"{event_id} (step {step_id})"


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("payload")
    if isinstance(raw, dict):
        return raw
    return {}


@dataclass
class StageProblem:
    """A detected problem pattern with event references."""

    stage: str
    category: str
    message: str
    attempt: int = 1
    item_id: str | None = None
    gate_name: str | None = None
    error_output: str | None = None
    suggested_fix: str | None = None
    event_refs: list[str] = field(default_factory=list)

    def to_summary(self) -> str:
        parts = [f"[{self.stage}:{self.category}]"]
        if self.gate_name:
            parts.append(f"({self.gate_name})")
        if self.item_id:
            parts.append(f"item={self.item_id}")
        parts.append(self.message[:100])
        return " ".join(parts)


@dataclass
class FixAttempt:
    """A fix attempt and its outcome."""

    item_id: str
    attempt: int
    trigger: str
    succeeded: bool
    duration_ms: int
    error_before: str | None = None
    event_refs: list[str] = field(default_factory=list)


@dataclass
class ProblemsSummary:
    """Summary of detected problems for prompt tuning."""

    problems: list[StageProblem] = field(default_factory=list)
    fix_attempts: list[FixAttempt] = field(default_factory=list)
    gate_failures: dict[str, int] = field(default_factory=dict)
    failure_categories: dict[str, int] = field(default_factory=dict)
    total_fix_iterations: int = 0
    stages_failed: int = 0
    stages_retried: int = 0

    def has_problems(self) -> bool:
        return bool(self.problems) or self.total_fix_iterations > 0

    def to_prompt_section(self, max_problems: int = 10) -> str:
        if not self.has_problems():
            return "No significant problems encountered during this run."

        lines = ["## Problems Encountered During Run", ""]
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

        lines.append("### Problem Details")
        for i, problem in enumerate(self.problems[:max_problems], 1):
            lines.append(f"\n**Problem {i}:** `{problem.stage}` → `{problem.category}`")
            lines.append(f"- Message: {problem.message}")
            if problem.gate_name:
                lines.append(f"- Gate: {problem.gate_name}")
            if problem.event_refs:
                lines.append("- Event refs: " + ", ".join(problem.event_refs[:5]))
            if problem.error_output:
                lines.append(f"- Evidence:\n```\n{problem.error_output[:500]}\n```")
            if problem.suggested_fix:
                lines.append(f"- Proposed prompt/rules fix: {problem.suggested_fix}")
        if len(self.problems) > max_problems:
            lines.append(f"\n... and {len(self.problems) - max_problems} more problems")

        if self.fix_attempts:
            lines.append("\n### Fix Attempts")
            succeeded = sum(1 for x in self.fix_attempts if x.succeeded)
            lines.append(f"- Total attempts: {len(self.fix_attempts)}")
            lines.append(f"- Succeeded: {succeeded}, Failed: {len(self.fix_attempts) - succeeded}")
            for attempt in self.fix_attempts[:10]:
                refs = ", ".join(attempt.event_refs[:2]) if attempt.event_refs else "-"
                lines.append(
                    f"- item={attempt.item_id} attempt={attempt.attempt} trigger={attempt.trigger} "
                    f"succeeded={attempt.succeeded} refs={refs}"
                )

        return "\n".join(lines)

    def get_lessons_learned(self) -> list[str]:
        lessons: list[str] = []
        for gate, count in self.gate_failures.items():
            if count >= 2:
                lessons.append(
                    f"Gate `{gate}` failed {count} times. Add targeted guardrails/checklist before running gates."
                )
        if self.failure_categories.get("context_bloat", 0) > 0:
            lessons.append(
                "Context bloat detected. Add prompt instructions to summarize stale context."
            )
        if self.failure_categories.get("looping", 0) > 0:
            lessons.append(
                "Command loops detected. Add explicit stop conditions and alternative strategy fallback."
            )
        if self.failure_categories.get("premature_edits", 0) > 0:
            lessons.append(
                "Premature edits detected. Require hypothesis validation before broad file modifications."
            )
        return lessons


class ProblemsCollector:
    """Collect and analyze problems from observability/events.jsonl."""

    def __init__(self, paths: RunPaths) -> None:
        self.paths = paths

    def collect(self) -> ProblemsSummary:
        log = logger.bind(run_id=self.paths.run_id)
        summary = ProblemsSummary()
        events_path = self.paths.observability_events_jsonl
        if not events_path.exists():
            log.debug("No observability events found", path=str(events_path))
            return summary

        events = self._load_events(events_path)
        if not events:
            return summary

        self._collect_stage_stats(events, summary)
        self._collect_gate_failures(events, summary)
        self._collect_fix_attempts(events, summary)
        self._detect_looping(events, summary)
        self._detect_repeated_tool_failures(events, summary)
        self._detect_context_bloat(events, summary)
        self._detect_premature_edits(events, summary)
        self._detect_instruction_drift(events, summary)

        log.info(
            "Problems collected from observability",
            problems=len(summary.problems),
            fix_attempts=len(summary.fix_attempts),
            stages_failed=summary.stages_failed,
        )
        return summary

    def _load_events(self, path: Path) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                events.append(data)
        events.sort(key=lambda e: int(e.get("step_id") or 0))
        return events

    def _collect_stage_stats(
        self, events: list[dict[str, Any]], summary: ProblemsSummary
    ) -> None:
        stage_attempts: dict[tuple[str, str | None], int] = {}
        for event in events:
            if event.get("event_type") != "stage.end":
                continue
            payload = _payload(event)
            stage = str(payload.get("stage") or "unknown")
            item_id = payload.get("item_id")
            attempt = int(payload.get("attempt") or 1)
            key = (stage, str(item_id) if item_id else None)
            stage_attempts[key] = max(stage_attempts.get(key, 1), attempt)

            status = str(payload.get("status") or "unknown")
            if status in {"failure", "failed", "fail"}:
                summary.stages_failed += 1
                category = "stage_failure"
                summary.failure_categories[category] = (
                    summary.failure_categories.get(category, 0) + 1
                )
                summary.problems.append(
                    StageProblem(
                        stage=stage,
                        category=category,
                        message=str(payload.get("message") or "Stage failed"),
                        attempt=attempt,
                        item_id=str(item_id) if item_id else None,
                        event_refs=[_event_ref(event)],
                    )
                )

        summary.stages_retried = sum(1 for attempts in stage_attempts.values() if attempts > 1)

    def _collect_gate_failures(
        self, events: list[dict[str, Any]], summary: ProblemsSummary
    ) -> None:
        for event in events:
            if event.get("event_type") != "gate.approval":
                continue
            payload = _payload(event)
            status = str(payload.get("status") or "unknown")
            gate = str(payload.get("gate") or "unknown")
            if status == "rejected":
                summary.gate_failures[gate] = summary.gate_failures.get(gate, 0) + 1
                summary.failure_categories["gate_failure"] = (
                    summary.failure_categories.get("gate_failure", 0) + 1
                )
                details = payload.get("details")
                message = f"Gate {gate} rejected"
                if isinstance(details, dict):
                    ret = details.get("returncode")
                    if isinstance(ret, int):
                        message += f" (returncode={ret})"
                summary.problems.append(
                    StageProblem(
                        stage="verify",
                        category="gate_failure",
                        gate_name=gate,
                        message=message,
                        item_id=str(payload.get("item_id")) if payload.get("item_id") else None,
                        attempt=int(payload.get("attempt") or 1),
                        event_refs=[_event_ref(event)],
                        suggested_fix=(
                            "Refine tool instructions for failing gate and add a pre-gate checklist."
                        ),
                    )
                )

    def _collect_fix_attempts(
        self, events: list[dict[str, Any]], summary: ProblemsSummary
    ) -> None:
        for event in events:
            if event.get("event_type") != "stage.end":
                continue
            payload = _payload(event)
            stage = str(payload.get("stage") or "")
            if stage not in {"fix", "implement"}:
                continue
            attempt = int(payload.get("attempt") or 1)
            if stage == "fix" or attempt > 1:
                summary.total_fix_iterations += 1
                summary.fix_attempts.append(
                    FixAttempt(
                        item_id=str(payload.get("item_id") or "unknown"),
                        attempt=attempt,
                        trigger="verify_failure",
                        succeeded=str(payload.get("status") or "") == "success",
                        duration_ms=int(payload.get("duration_ms") or 0),
                        error_before=str(payload.get("message"))
                        if payload.get("message")
                        else None,
                        event_refs=[_event_ref(event)],
                    )
                )

    def _detect_looping(
        self, events: list[dict[str, Any]], summary: ProblemsSummary
    ) -> None:
        window: deque[str] = deque(maxlen=6)
        refs: deque[str] = deque(maxlen=6)
        for event in events:
            if event.get("event_type") != "proc.exec.start":
                continue
            cmd_val = _payload(event).get("cmd")
            cmd = " ".join(str(x) for x in cmd_val) if isinstance(cmd_val, list) else ""
            if not cmd:
                continue
            window.append(cmd)
            refs.append(_event_ref(event))
            if len(window) == 6:
                common = Counter(window).most_common(1)
                if common and common[0][1] >= 4:
                    repeated_cmd = common[0][0]
                    summary.failure_categories["looping"] = (
                        summary.failure_categories.get("looping", 0) + 1
                    )
                    summary.problems.append(
                        StageProblem(
                            stage="runtime",
                            category="looping",
                            message=f"Repeated command loop detected: `{repeated_cmd}`",
                            event_refs=list(refs),
                            suggested_fix=(
                                "Add stop condition after repeated command failures and force strategy switch."
                            ),
                        )
                    )
                    return

    def _detect_repeated_tool_failures(
        self, events: list[dict[str, Any]], summary: ProblemsSummary
    ) -> None:
        failures: dict[str, list[str]] = {}
        for event in events:
            if event.get("event_type") != "proc.exec.end":
                continue
            payload = _payload(event)
            returncode = payload.get("returncode")
            if not isinstance(returncode, int) or returncode == 0:
                continue
            command_id = str(payload.get("command_id") or "unknown")
            failures.setdefault(command_id, []).append(_event_ref(event))

        if len(failures) >= 3:
            refs = [ref for values in failures.values() for ref in values][:6]
            summary.failure_categories["repeated_tool_failures"] = (
                summary.failure_categories.get("repeated_tool_failures", 0) + 1
            )
            summary.problems.append(
                StageProblem(
                    stage="runtime",
                    category="repeated_tool_failures",
                    message=f"Detected {len(failures)} distinct failed process executions.",
                    event_refs=refs,
                    suggested_fix=(
                        "Prompt should require immediate diagnosis after second identical tool failure."
                    ),
                )
            )

    def _detect_context_bloat(
        self, events: list[dict[str, Any]], summary: ProblemsSummary
    ) -> None:
        req_chars: list[tuple[int, str]] = []
        for event in events:
            if event.get("event_type") != "llm.request":
                continue
            chars = _payload(event).get("chars")
            if isinstance(chars, int):
                req_chars.append((chars, _event_ref(event)))
        if len(req_chars) < 3:
            return
        first = req_chars[0][0]
        last = req_chars[-1][0]
        if first > 0 and last >= first * 2:
            summary.failure_categories["context_bloat"] = (
                summary.failure_categories.get("context_bloat", 0) + 1
            )
            summary.problems.append(
                StageProblem(
                    stage="llm",
                    category="context_bloat",
                    message=f"Prompt context grew from {first} to {last} characters.",
                    event_refs=[req_chars[0][1], req_chars[-1][1]],
                    suggested_fix=(
                        "Add rolling summary policy and explicit context budget in system prompt."
                    ),
                )
            )

    def _detect_premature_edits(
        self, events: list[dict[str, Any]], summary: ProblemsSummary
    ) -> None:
        first_patch: dict[str, Any] | None = None
        first_gate: dict[str, Any] | None = None
        for event in events:
            event_type = str(event.get("event_type") or "")
            if event_type == "fs.patch" and first_patch is None:
                first_patch = event
            if event_type == "gate.approval" and first_gate is None:
                first_gate = event
        if first_patch and first_gate:
            patch_step = int(first_patch.get("step_id") or 0)
            gate_step = int(first_gate.get("step_id") or 0)
            if patch_step < gate_step:
                summary.failure_categories["premature_edits"] = (
                    summary.failure_categories.get("premature_edits", 0) + 1
                )
                summary.problems.append(
                    StageProblem(
                        stage="implement",
                        category="premature_edits",
                        message="Filesystem edits happened before any gate result was available.",
                        event_refs=[_event_ref(first_patch), _event_ref(first_gate)],
                        suggested_fix=(
                            "Require hypothesis + minimal validation before broad edits."
                        ),
                    )
                )

    def _detect_instruction_drift(
        self, events: list[dict[str, Any]], summary: ProblemsSummary
    ) -> None:
        for event in events:
            if event.get("event_type") != "observability.warning":
                continue
            payload = _payload(event)
            code = str(payload.get("code") or "unknown")
            if "forbidden" in code or "guardrail" in code:
                summary.failure_categories["instruction_drift"] = (
                    summary.failure_categories.get("instruction_drift", 0) + 1
                )
                summary.problems.append(
                    StageProblem(
                        stage="runtime",
                        category="instruction_drift",
                        message=f"Warning indicates policy drift: {code}",
                        event_refs=[_event_ref(event)],
                        suggested_fix=(
                            "Strengthen system prompt with explicit forbidden-actions checklist."
                        ),
                    )
                )
