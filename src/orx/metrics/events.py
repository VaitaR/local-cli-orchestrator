"""Event timeline logging for runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class EventLogger:
    """Append-only JSONL event logger for run timelines."""

    path: Path

    def log(self, event: str, **fields: Any) -> None:
        """Append an event entry to events.jsonl.

        Args:
            event: Event name (e.g., "stage_start", "gate_end").
            **fields: Additional event fields.
        """
        payload = {
            "ts": datetime.now(tz=UTC).isoformat(),
            "event": event,
            **fields,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True))
            f.write("\n")
