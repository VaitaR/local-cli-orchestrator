"""Validation helpers for observability v2 bundles."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from orx.observability.schema import SCHEMA_VERSION

_REQUIRED_EVENT_FIELDS = {
    "schema_version",
    "event_id",
    "ts",
    "run_id",
    "source",
    "event_type",
    "step_id",
    "correlation",
    "payload",
}


@dataclass(slots=True)
class ValidationResult:
    """Validation report for one observability events file."""

    run_id: str
    events: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when no validation errors were found."""
        return not self.errors


def validate_events_file(events_path: Path, run_id: str) -> ValidationResult:
    """Validate event envelope and monotonic step ids."""
    result = ValidationResult(run_id=run_id)
    if not events_path.exists():
        result.errors.append(f"events file missing: {events_path}")
        return result

    prev_step = 0
    for line_no, line in enumerate(events_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        result.events += 1
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            result.errors.append(f"line {line_no}: invalid JSON ({exc})")
            continue
        if not isinstance(data, dict):
            result.errors.append(f"line {line_no}: event is not an object")
            continue

        missing = sorted(_REQUIRED_EVENT_FIELDS - data.keys())
        if missing:
            result.errors.append(f"line {line_no}: missing fields {', '.join(missing)}")
            continue

        schema_version = str(data.get("schema_version"))
        if schema_version != SCHEMA_VERSION:
            result.errors.append(
                f"line {line_no}: schema_version={schema_version} expected={SCHEMA_VERSION}"
            )

        event_run_id = str(data.get("run_id") or "")
        if event_run_id != run_id:
            result.errors.append(f"line {line_no}: run_id={event_run_id} expected={run_id}")

        step_id_raw = data.get("step_id")
        if not isinstance(step_id_raw, int) or step_id_raw <= 0:
            result.errors.append(f"line {line_no}: invalid step_id={step_id_raw!r}")
            continue
        if step_id_raw <= prev_step:
            result.errors.append(
                f"line {line_no}: non-monotonic step_id={step_id_raw} previous={prev_step}"
            )
        prev_step = step_id_raw

        corr = data.get("correlation")
        payload = data.get("payload")
        if not isinstance(corr, dict):
            result.errors.append(f"line {line_no}: correlation must be object")
        if not isinstance(payload, dict):
            result.errors.append(f"line {line_no}: payload must be object")

    if result.events == 0:
        result.errors.append("events file is empty")
    return result


def load_event_types(events_path: Path) -> dict[str, int]:
    """Count events by type for reporting."""
    counts: dict[str, int] = {}
    if not events_path.exists():
        return counts

    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        event_type = str(data.get("event_type") or "unknown")
        counts[event_type] = counts.get(event_type, 0) + 1
    return counts
