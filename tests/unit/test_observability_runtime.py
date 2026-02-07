"""Unit tests for observability runtime event emission."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orx.executors.base import ExecResult, ResolvedInvocation
from orx.observability.correlation import StepCounter
from orx.observability.runtime import RunObservability
from orx.observability.writer import EventWriter
from orx.paths import RunPaths


def _load_events(events_path: Path) -> list[dict[str, Any]]:
    return EventWriter(events_path).read_all()


def _make_exec_result(
    *,
    paths: RunPaths,
    extra: dict[str, Any] | None = None,
    model: str = "haiku",
) -> ExecResult:
    stdout = paths.logs_dir / "agent.stdout.log"
    stderr = paths.logs_dir / "agent.stderr.log"
    stdout.write_text("executor stdout")
    stderr.write_text("")
    invocation = ResolvedInvocation(
        cmd=["claude", "-p"],
        model_info={"executor": "claude_code", "model": model},
    )
    return ExecResult(
        returncode=0,
        stdout_path=stdout,
        stderr_path=stderr,
        extra=extra or {},
        success=True,
        invocation=invocation,
    )


def test_runtime_emits_network_events_and_llm_cost_fields(tmp_path: Path) -> None:
    """Run observability should emit network+llm events with extended metrics."""
    paths = RunPaths.create_new(tmp_path, run_id="obs_runtime_full")
    runtime = RunObservability(
        paths=paths,
        step_counter=StepCounter(),
        tty_enabled=True,
        network_mode="full_payload",
    )

    runtime.start(engine="claude_code", base_branch="main")
    runtime.run_start()

    prompt = paths.prompts_dir / "implement.md"
    prompt.write_text("Implement quickly.")
    corr = runtime.llm_request(
        stage="implement",
        prompt_path=prompt,
        attempt=1,
        model="haiku",
        executor="claude_code",
    )

    result = _make_exec_result(
        paths=paths,
        extra={
            "cost_usd": 0.12,
            "total_cost_usd": 0.12,
            "duration_api_ms": 990,
            "num_turns": 3,
            "session_id": "sess-1",
            "type": "result",
            "subtype": "success",
            "usage": {"input_tokens": 100, "output_tokens": 25},
        },
    )
    runtime.llm_response(
        stage="implement",
        result=result,
        out_path=None,
        attempt=1,
        correlation_ids=corr,
        duration_ms=1100,
    )
    runtime.run_end(status="success")
    runtime.finish(status="success")

    events = _load_events(paths.observability_events_jsonl)

    warnings = [
        event.get("payload", {}).get("code")
        for event in events
        if event.get("event_type") == "observability.warning"
    ]
    assert "network_capture_not_implemented" not in warnings
    assert "tty_unavailable" not in warnings

    llm_response = next(
        event for event in events if event.get("event_type") == "llm.response"
    )
    payload = llm_response["payload"]
    assert payload["cost_usd"] == 0.12
    assert payload["total_cost_usd"] == 0.12
    assert payload["duration_api_ms"] == 990
    assert payload["num_turns"] == 3
    assert payload["session_id"] == "sess-1"
    assert payload["executor"] == "claude_code"

    network_request = next(
        event for event in events if event.get("event_type") == "network.request"
    )
    network_response = next(
        event for event in events if event.get("event_type") == "network.response"
    )

    assert network_request["payload"]["destination_host"] == "api.anthropic.com"
    assert network_response["payload"]["destination_host"] == "api.anthropic.com"
    assert "request_path" in network_request["payload"]
    assert "response_path" in network_response["payload"]
    assert network_request["correlation"]["call_id"] == corr.call_id
    assert network_response["correlation"]["call_id"] == corr.call_id


def test_runtime_network_metadata_mode_omits_payload_paths(tmp_path: Path) -> None:
    """Metadata-only mode should omit request/response payload paths."""
    paths = RunPaths.create_new(tmp_path, run_id="obs_runtime_meta")
    runtime = RunObservability(
        paths=paths,
        step_counter=StepCounter(),
        tty_enabled=False,
        network_mode="metadata_only",
    )
    runtime.start(engine="claude_code", base_branch="main")

    prompt = paths.prompts_dir / "review.md"
    prompt.write_text("Review quickly.")
    corr = runtime.llm_request(
        stage="review",
        prompt_path=prompt,
        attempt=1,
        model="haiku",
        executor="claude_code",
    )
    result = _make_exec_result(paths=paths)
    runtime.llm_response(
        stage="review",
        result=result,
        out_path=None,
        attempt=1,
        correlation_ids=corr,
        duration_ms=200,
    )
    runtime.finish(status="success")

    events = _load_events(paths.observability_events_jsonl)
    network_request = next(
        event for event in events if event.get("event_type") == "network.request"
    )
    network_response = next(
        event for event in events if event.get("event_type") == "network.response"
    )
    assert network_request["payload"]["mode"] == "metadata_only"
    assert network_response["payload"]["mode"] == "metadata_only"
    assert "request_path" not in network_request["payload"]
    assert "response_path" not in network_response["payload"]
