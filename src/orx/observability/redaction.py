"""Redaction utilities for observability exports."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|token|secret|password|passwd|authorization)",
    re.IGNORECASE,
)

_SECRET_VALUE_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]+)",
    re.IGNORECASE,
)


def _redact_string(value: str) -> str:
    return _SECRET_VALUE_PATTERN.sub("[REDACTED]", value)


def redact_obj(value: Any) -> Any:
    """Recursively redact sensitive fields/values."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, child in value.items():
            if _SECRET_KEY_PATTERN.search(key):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_obj(child)
        return redacted
    if isinstance(value, list):
        return [redact_obj(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def redact_event(event: dict[str, Any]) -> dict[str, Any]:
    """Return redacted copy of an event dictionary."""
    return redact_obj(event)


def export_redacted_events(events_path: Path, output_path: Path) -> int:
    """Read events JSONL, redact, and write exported JSONL.

    Returns number of exported lines.
    """
    if not events_path.exists():
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8") as out:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            out.write(json.dumps(redact_event(event), ensure_ascii=True))
            out.write("\n")
            count += 1
    return count
