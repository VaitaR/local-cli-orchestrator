"""Unit tests for observability redaction."""

from __future__ import annotations

import json

from orx.observability.redaction import export_redacted_events, redact_event


def test_redact_event_keeps_telemetry_token_fields() -> None:
    """Non-secret telemetry token fields should not be redacted."""
    event = {
        "event_type": "llm.response",
        "payload": {
            "tokens": 123,
            "token_usage": {
                "input_tokens": 100,
                "output_tokens": 23,
                "total_tokens": 123,
            },
            "tool_calls": 2,
        },
    }

    redacted = redact_event(event)
    payload = redacted["payload"]
    assert payload["tokens"] == 123
    assert payload["token_usage"]["input_tokens"] == 100
    assert payload["token_usage"]["output_tokens"] == 23
    assert payload["token_usage"]["total_tokens"] == 123
    assert payload["tool_calls"] == 2


def test_redact_event_redacts_sensitive_keys_and_values() -> None:
    """Secret keys and secret-like string payloads should be redacted."""
    event = {
        "event_type": "llm.request",
        "payload": {
            "api_key": "super-secret",
            "headers": {"authorization": "Bearer real_token"},
            "message": "please use sk-1234567890abcdefghij",
        },
    }

    redacted = redact_event(event)
    payload = redacted["payload"]
    assert payload["api_key"] == "[REDACTED]"
    assert payload["headers"]["authorization"] == "[REDACTED]"
    assert payload["message"] == "please use [REDACTED]"


def test_export_redacted_events_writes_redacted_jsonl(tmp_path) -> None:
    """Export should redact events line-by-line to output path."""
    events_path = tmp_path / "events.jsonl"
    output_path = tmp_path / "redacted" / "events.redacted.jsonl"

    events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event_type": "llm.response",
                        "payload": {"token_usage": {"total_tokens": 42}},
                    }
                ),
                json.dumps(
                    {
                        "event_type": "llm.request",
                        "payload": {"authorization": "Bearer abc"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    count = export_redacted_events(events_path, output_path)
    assert count == 2
    assert output_path.exists()

    lines = [json.loads(line) for line in output_path.read_text().splitlines() if line]
    assert lines[0]["payload"]["token_usage"]["total_tokens"] == 42
    assert lines[1]["payload"]["authorization"] == "[REDACTED]"
