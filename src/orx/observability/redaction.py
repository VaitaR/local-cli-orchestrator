"""Redaction utilities for observability exports."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

_SECRET_VALUE_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]+)",
    re.IGNORECASE,
)

_NON_SECRET_TELEMETRY_KEYS = {
    "tokens",
    "token_usage",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "tool_calls",
}


def _redact_string(value: str) -> str:
    return _SECRET_VALUE_PATTERN.sub("[REDACTED]", value)


def _normalize_key(key: str) -> str:
    with_snake_case = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    return with_snake_case.lower().strip()


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalize_key(key)
    if normalized in _NON_SECRET_TELEMETRY_KEYS:
        return False

    if normalized in {
        "token",
        "api_key",
        "apikey",
        "secret",
        "password",
        "passwd",
        "authorization",
        "access_token",
        "refresh_token",
        "auth_token",
        "private_key",
        "client_secret",
    }:
        return True

    parts = [part for part in re.split(r"[^a-z0-9]+", normalized) if part]
    part_set = set(parts)
    if {"password", "passwd", "secret", "authorization"} & part_set:
        return True
    if "token" in part_set:
        return True
    return bool(
        "key" in part_set
        and {"api", "private", "client", "access", "secret"} & part_set
    )


def redact_obj(value: Any) -> Any:
    """Recursively redact sensitive fields/values."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, child in value.items():
            if _is_sensitive_key(key):
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
    return cast(dict[str, Any], redact_obj(event))


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
