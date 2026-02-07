"""Schema types for observability v2 events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "2.0"


@dataclass(slots=True)
class Correlation:
    """Correlation identifiers for linking related events."""

    call_id: str | None = None
    parent_id: str | None = None
    span_id: str | None = None

    def to_dict(self) -> dict[str, str]:
        """Serialize non-empty fields to a dictionary."""
        result: dict[str, str] = {}
        if self.call_id:
            result["call_id"] = self.call_id
        if self.parent_id:
            result["parent_id"] = self.parent_id
        if self.span_id:
            result["span_id"] = self.span_id
        return result


@dataclass(slots=True)
class ObsEvent:
    """Canonical observability event envelope."""

    event_id: str
    run_id: str
    source: str
    event_type: str
    step_id: int
    payload: dict[str, Any] = field(default_factory=dict)
    correlation: Correlation = field(default_factory=Correlation)
    ts: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Convert event to JSON-serializable dictionary."""
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "ts": self.ts,
            "run_id": self.run_id,
            "source": self.source,
            "event_type": self.event_type,
            "step_id": self.step_id,
            "correlation": self.correlation.to_dict(),
            "payload": self.payload,
        }


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO8601 format."""
    return datetime.now(tz=UTC).isoformat()
