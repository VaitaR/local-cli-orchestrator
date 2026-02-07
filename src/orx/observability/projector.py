"""Projection utilities from observability v2 events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from orx.observability.writer import EventWriter


@dataclass(slots=True)
class ProjectedRun:
    """Projected run summary derived from events."""

    status: str
    current_stage: str | None
    start_ts: str | None
    end_ts: str | None
    duration_ms: int | None
    tokens: dict[str, int]
    stages: list[dict[str, Any]]


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load_events(path: Path) -> list[dict[str, Any]]:
    """Load observability events from JSONL path."""
    return EventWriter(path).read_all()


def _payload_dict(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("payload")
    if isinstance(raw, dict):
        return raw
    return {}


def _dict_or_empty(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _to_int(value: Any, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def project_run(events: list[dict[str, Any]]) -> ProjectedRun:
    """Project run-level and stage-level metrics from events."""
    run_start_ts: str | None = None
    run_end_ts: str | None = None
    run_status = "running"
    current_stage: str | None = None

    stage_entries: list[dict[str, Any]] = []
    open_stage_idx: dict[tuple[str, str | None, int], int] = {}
    stage_tokens: dict[tuple[str, str | None, int], dict[str, int]] = {}

    total_tokens = {"input": 0, "output": 0, "total": 0, "tool_calls": 0}

    for event in events:
        event_type = str(event.get("event_type") or "")
        payload = _payload_dict(event)

        if event_type == "run.start":
            run_start_ts = str(event.get("ts") or run_start_ts)
            run_status = "running"
        elif event_type == "run.end":
            run_end_ts = str(event.get("ts") or run_end_ts)
            status_raw = payload.get("status")
            run_status = str(status_raw) if status_raw else "success"
        elif event_type == "stage.start":
            stage = str(payload.get("stage") or "unknown")
            item_id = payload.get("item_id")
            attempt = _to_int(payload.get("attempt"), default=1)
            key = (stage, item_id if isinstance(item_id, str) else None, attempt)
            current_stage = stage
            stage_entries.append(
                {
                    "stage": stage,
                    "item_id": key[1],
                    "attempt": attempt,
                    "start_ts": event.get("ts"),
                    "end_ts": None,
                    "duration_ms": None,
                    "status": "running",
                    "executor": payload.get("executor"),
                    "model": payload.get("model"),
                    "tokens": {"input": 0, "output": 0, "total": 0, "tool_calls": 0},
                    "error": None,
                }
            )
            open_stage_idx[key] = len(stage_entries) - 1
            stage_tokens.setdefault(key, {"input": 0, "output": 0, "total": 0, "tool_calls": 0})
        elif event_type == "stage.end":
            stage = str(payload.get("stage") or "unknown")
            item_id = payload.get("item_id")
            attempt = _to_int(payload.get("attempt"), default=1)
            key = (stage, item_id if isinstance(item_id, str) else None, attempt)
            idx = open_stage_idx.get(key)
            if idx is not None:
                stage_entries[idx]["end_ts"] = event.get("ts")
                status_raw = payload.get("status")
                stage_entries[idx]["status"] = str(status_raw) if status_raw else "success"
                stage_entries[idx]["error"] = payload.get("message")
                explicit_duration = payload.get("duration_ms")
                if isinstance(explicit_duration, int):
                    stage_entries[idx]["duration_ms"] = explicit_duration
                else:
                    start_dt = _parse_iso(stage_entries[idx].get("start_ts"))
                    end_dt = _parse_iso(stage_entries[idx].get("end_ts"))
                    if start_dt and end_dt:
                        stage_entries[idx]["duration_ms"] = int((end_dt - start_dt).total_seconds() * 1000)
                stage_entries[idx]["tokens"] = stage_tokens.get(key, stage_entries[idx]["tokens"])
                current_stage = None
        elif event_type == "llm.response":
            stage_raw = payload.get("stage")
            if not isinstance(stage_raw, str):
                continue
            stage = stage_raw
            item_id = payload.get("item_id")
            attempt = _to_int(payload.get("attempt"), default=1)
            key = (stage, item_id if isinstance(item_id, str) else None, attempt)

            tokens = _dict_or_empty(payload.get("tokens"))
            input_tokens = _to_int(tokens.get("input"), default=0)
            output_tokens = _to_int(tokens.get("output"), default=0)
            total = _to_int(tokens.get("total"), default=(input_tokens + output_tokens))
            tool_calls = _to_int(tokens.get("tool_calls"), default=0)

            bucket = stage_tokens.setdefault(
                key,
                {"input": 0, "output": 0, "total": 0, "tool_calls": 0},
            )
            bucket["input"] += input_tokens
            bucket["output"] += output_tokens
            bucket["total"] += total
            bucket["tool_calls"] += tool_calls

            total_tokens["input"] += input_tokens
            total_tokens["output"] += output_tokens
            total_tokens["total"] += total
            total_tokens["tool_calls"] += tool_calls

    start_dt = _parse_iso(run_start_ts)
    end_dt = _parse_iso(run_end_ts)
    duration_ms = None
    if start_dt and end_dt:
        duration_ms = int((end_dt - start_dt).total_seconds() * 1000)

    return ProjectedRun(
        status=run_status,
        current_stage=current_stage,
        start_ts=run_start_ts,
        end_ts=run_end_ts,
        duration_ms=duration_ms,
        tokens=total_tokens,
        stages=stage_entries,
    )


def project_timeline(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Split events into grouped timeline buckets for dashboard rendering."""
    groups: dict[str, list[dict[str, Any]]] = {
        "llm": [],
        "network": [],
        "proc": [],
        "fs": [],
        "tty": [],
        "gate": [],
        "other": [],
    }

    for event in events:
        event_type = str(event.get("event_type") or "")
        if event_type.startswith("llm."):
            groups["llm"].append(event)
        elif event_type.startswith("network."):
            groups["network"].append(event)
        elif event_type.startswith("proc."):
            groups["proc"].append(event)
        elif event_type.startswith("fs."):
            groups["fs"].append(event)
        elif event_type.startswith("tty."):
            groups["tty"].append(event)
        elif event_type.startswith("gate."):
            groups["gate"].append(event)
        else:
            groups["other"].append(event)

    return groups
