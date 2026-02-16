"""Unit tests for agent meta-cognition layer (Hot Notes).

Tests parsing of <orx_meta> tags, <thinking> blocks,
AgentMeta dataclass, and integration with ExecResult + observability.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orx.executors.base import (
    AgentMeta,
    ExecResult,
    ResolvedInvocation,
    extract_reasoning_trace,
    parse_orx_meta,
)
from orx.observability.correlation import StepCounter
from orx.observability.runtime import RunObservability
from orx.observability.writer import EventWriter
from orx.paths import RunPaths

# ---------------------------------------------------------------------------
# AgentMeta.from_dict
# ---------------------------------------------------------------------------


class TestAgentMetaFromDict:
    def test_valid_full(self) -> None:
        data = {
            "confidence": 0.85,
            "context_gap": True,
            "missing_info": ["eslint config", "runtime version"],
            "tool_efficacy": "medium",
            "reasoning_summary": "Used grep to find auth module",
        }
        meta = AgentMeta.from_dict(data)
        assert meta.confidence == 0.85
        assert meta.context_gap is True
        assert meta.missing_info == ["eslint config", "runtime version"]
        assert meta.tool_efficacy == "medium"
        assert meta.reasoning_summary == "Used grep to find auth module"

    def test_clamps_confidence(self) -> None:
        meta = AgentMeta.from_dict({"confidence": 2.5})
        assert meta.confidence == 1.0

        meta = AgentMeta.from_dict({"confidence": -0.3})
        assert meta.confidence == 0.0

    def test_invalid_confidence_type(self) -> None:
        meta = AgentMeta.from_dict({"confidence": "not_a_number"})
        assert meta.confidence == 0.0

    def test_invalid_tool_efficacy_defaults(self) -> None:
        meta = AgentMeta.from_dict({"tool_efficacy": "unknown_value"})
        assert meta.tool_efficacy == "high"

    def test_empty_dict(self) -> None:
        meta = AgentMeta.from_dict({})
        assert meta.confidence == 0.0
        assert meta.context_gap is False
        assert meta.missing_info == []
        assert meta.tool_efficacy == "high"
        assert meta.reasoning_summary == ""

    def test_to_dict_minimal(self) -> None:
        meta = AgentMeta(confidence=0.7)
        d = meta.to_dict()
        assert d["confidence"] == 0.7
        assert d["context_gap"] is False
        assert "missing_info" not in d  # empty list omitted
        assert "reasoning_summary" not in d  # empty string omitted

    def test_to_dict_full(self) -> None:
        meta = AgentMeta(
            confidence=0.5,
            context_gap=True,
            missing_info=["config"],
            tool_efficacy="low",
            reasoning_summary="Struggled",
        )
        d = meta.to_dict()
        assert d["missing_info"] == ["config"]
        assert d["reasoning_summary"] == "Struggled"
        assert d["tool_efficacy"] == "low"


# ---------------------------------------------------------------------------
# parse_orx_meta
# ---------------------------------------------------------------------------


class TestParseOrxMeta:
    def test_extracts_and_strips(self) -> None:
        text = (
            "Here is my plan.\n\n"
            "<orx_meta>\n"
            '{"confidence": 0.9, "context_gap": false, "tool_efficacy": "high", '
            '"reasoning_summary": "Straightforward task"}\n'
            "</orx_meta>"
        )
        cleaned, meta = parse_orx_meta(text)
        assert meta is not None
        assert meta.confidence == 0.9
        assert meta.context_gap is False
        assert "orx_meta" not in cleaned
        assert "Here is my plan." in cleaned

    def test_no_meta_block(self) -> None:
        text = "Just a regular response with no meta."
        cleaned, meta = parse_orx_meta(text)
        assert meta is None
        assert cleaned == text

    def test_malformed_json(self) -> None:
        text = "Output\n<orx_meta>{not valid json}</orx_meta>"
        cleaned, meta = parse_orx_meta(text)
        assert meta is None
        assert cleaned == text  # Original text preserved

    def test_meta_in_middle_of_text(self) -> None:
        text = (
            "First part.\n"
            '<orx_meta>{"confidence": 0.6}</orx_meta>\n'
            "Second part."
        )
        cleaned, meta = parse_orx_meta(text)
        assert meta is not None
        assert meta.confidence == 0.6
        assert "First part." in cleaned
        assert "Second part." in cleaned
        assert "orx_meta" not in cleaned

    def test_meta_with_markdown(self) -> None:
        text = (
            "```python\nprint('hello')\n```\n\n"
            '<orx_meta>{"confidence": 0.95, "context_gap": false}</orx_meta>'
        )
        cleaned, meta = parse_orx_meta(text)
        assert meta is not None
        assert meta.confidence == 0.95
        assert "print('hello')" in cleaned


# ---------------------------------------------------------------------------
# extract_reasoning_trace
# ---------------------------------------------------------------------------


class TestExtractReasoningTrace:
    def test_extracts_thinking(self) -> None:
        text = (
            "<thinking>I need to check the imports first.</thinking>\n"
            "Here is the code."
        )
        cleaned, trace = extract_reasoning_trace(text)
        assert "I need to check the imports first." in trace
        assert "thinking" not in cleaned
        assert "Here is the code." in cleaned

    def test_extracts_scratchpad(self) -> None:
        text = (
            "<scratchpad>Let me reason about this.</scratchpad>\n"
            "The answer is 42."
        )
        cleaned, trace = extract_reasoning_trace(text)
        assert "Let me reason about this." in trace
        assert "scratchpad" not in cleaned

    def test_multiple_thinking_blocks(self) -> None:
        text = (
            "<thinking>Step 1: analyze</thinking>\n"
            "Some code.\n"
            "<thinking>Step 2: implement</thinking>\n"
            "More code."
        )
        cleaned, trace = extract_reasoning_trace(text)
        assert "Step 1: analyze" in trace
        assert "Step 2: implement" in trace
        assert "thinking" not in cleaned

    def test_no_thinking_blocks(self) -> None:
        text = "Plain response without thinking."
        cleaned, trace = extract_reasoning_trace(text)
        assert cleaned == text
        assert trace == ""

    def test_combined_meta_and_thinking(self) -> None:
        text = (
            "<thinking>Need to find auth module</thinking>\n"
            "Here is the implementation.\n"
            '<orx_meta>{"confidence": 0.8}</orx_meta>'
        )
        # First parse meta, then extract thinking
        cleaned, meta = parse_orx_meta(text)
        cleaned, trace = extract_reasoning_trace(cleaned)
        assert meta is not None
        assert meta.confidence == 0.8
        assert "Need to find auth module" in trace
        assert "Here is the implementation." in cleaned
        assert "orx_meta" not in cleaned
        assert "thinking" not in cleaned


# ---------------------------------------------------------------------------
# ExecResult with agent_metadata
# ---------------------------------------------------------------------------


class TestExecResultAgentMeta:
    def test_default_none(self, tmp_path: Path) -> None:
        result = ExecResult(
            returncode=0,
            stdout_path=tmp_path / "out.log",
            stderr_path=tmp_path / "err.log",
        )
        assert result.agent_metadata is None
        assert result.reasoning_trace == ""

    def test_with_meta(self, tmp_path: Path) -> None:
        meta = AgentMeta(confidence=0.9, context_gap=False)
        result = ExecResult(
            returncode=0,
            stdout_path=tmp_path / "out.log",
            stderr_path=tmp_path / "err.log",
            agent_metadata=meta,
            reasoning_trace="I analyzed the code.",
        )
        assert result.agent_metadata is not None
        assert result.agent_metadata.confidence == 0.9
        assert result.reasoning_trace == "I analyzed the code."


# ---------------------------------------------------------------------------
# Observability: llm.response with agent_meta
# ---------------------------------------------------------------------------


def _load_events(events_path: Path) -> list[dict[str, Any]]:
    return EventWriter(events_path).read_all()


def test_llm_response_emits_agent_meta(tmp_path: Path) -> None:
    """llm.response event should include agent_meta and reasoning_trace."""
    paths = RunPaths.create_new(tmp_path, run_id="obs_meta_test")
    runtime = RunObservability(
        paths=paths,
        step_counter=StepCounter(),
        tty_enabled=False,
    )
    runtime.start(engine="fake")
    runtime.run_start()

    # Prepare output with meta
    out_path = paths.context_dir / "plan.md"
    out_path.write_text("The plan is simple.")

    stdout = paths.logs_dir / "agent.stdout.log"
    stderr = paths.logs_dir / "agent.stderr.log"
    stdout.write_text("executor stdout")
    stderr.write_text("")

    meta = AgentMeta(confidence=0.85, context_gap=True, missing_info=["config.yaml"])
    result = ExecResult(
        returncode=0,
        stdout_path=stdout,
        stderr_path=stderr,
        success=True,
        invocation=ResolvedInvocation(
            cmd=["fake"],
            model_info={"executor": "fake", "model": "test"},
        ),
        agent_metadata=meta,
        reasoning_trace="I needed to check the config first.",
    )

    runtime.llm_response(
        stage="plan",
        result=result,
        out_path=out_path,
    )

    events = _load_events(paths.observability_events_jsonl)
    llm_events = [e for e in events if e["event_type"] == "llm.response"]
    assert len(llm_events) >= 1

    payload = llm_events[0]["payload"]
    assert payload["agent_meta"] is not None
    assert payload["agent_meta"]["confidence"] == 0.85
    assert payload["agent_meta"]["context_gap"] is True
    assert payload["reasoning_trace"] == "I needed to check the config first."
    assert payload["reasoning_trace_path"] is not None


def test_llm_response_without_agent_meta(tmp_path: Path) -> None:
    """llm.response event should have None agent_meta when not provided."""
    paths = RunPaths.create_new(tmp_path, run_id="obs_no_meta")
    runtime = RunObservability(
        paths=paths,
        step_counter=StepCounter(),
        tty_enabled=False,
    )
    runtime.start(engine="fake")
    runtime.run_start()

    out_path = paths.context_dir / "plan.md"
    out_path.write_text("Simple plan.")

    stdout = paths.logs_dir / "agent.stdout.log"
    stderr = paths.logs_dir / "agent.stderr.log"
    stdout.write_text("executor stdout")
    stderr.write_text("")

    result = ExecResult(
        returncode=0,
        stdout_path=stdout,
        stderr_path=stderr,
        success=True,
        invocation=ResolvedInvocation(
            cmd=["fake"],
            model_info={"executor": "fake", "model": "test"},
        ),
    )

    runtime.llm_response(
        stage="plan",
        result=result,
        out_path=out_path,
    )

    events = _load_events(paths.observability_events_jsonl)
    llm_events = [e for e in events if e["event_type"] == "llm.response"]
    assert len(llm_events) >= 1

    payload = llm_events[0]["payload"]
    assert payload["agent_meta"] is None
    assert payload["reasoning_trace"] is None


# ---------------------------------------------------------------------------
# CommandExecutionEnd with result_size_bytes / is_useful
# ---------------------------------------------------------------------------


def test_command_execution_end_fields() -> None:
    """CommandExecutionEnd should carry result_size_bytes and is_useful."""
    from orx.infra.command import CommandExecutionEnd

    event = CommandExecutionEnd(
        command_id="abc",
        command=["rg", "foo"],
        cwd=None,
        returncode=0,
        duration_ms=50,
        stdout_path=None,
        stderr_path=None,
        result_size_bytes=1024,
        is_useful=True,
    )
    assert event.result_size_bytes == 1024
    assert event.is_useful is True

    # Default values
    event2 = CommandExecutionEnd(
        command_id="def",
        command=["rg", "bar"],
        cwd=None,
        returncode=1,
        duration_ms=10,
        stdout_path=None,
        stderr_path=None,
    )
    assert event2.result_size_bytes == 0
    assert event2.is_useful is True  # default


# ---------------------------------------------------------------------------
# Metrics: StageMetrics with new fields
# ---------------------------------------------------------------------------


def test_stage_metrics_confidence_serialization() -> None:
    """StageMetrics should serialize confidence and context_gap."""
    from orx.metrics.schema import StageMetrics

    metrics = StageMetrics(
        run_id="test",
        stage="implement",
        start_ts="2026-01-01T00:00:00Z",
        end_ts="2026-01-01T00:01:00Z",
        duration_ms=60000,
        confidence=0.72,
        context_gap=True,
        tokens_per_loc=150.456,
    )
    d = metrics.to_dict()
    assert d["confidence"] == 0.72
    assert d["context_gap"] is True
    assert d["tokens_per_loc"] == 150.46  # rounded

    # Omitted when None
    metrics2 = StageMetrics(
        run_id="test",
        stage="plan",
        start_ts="2026-01-01T00:00:00Z",
        end_ts="2026-01-01T00:01:00Z",
        duration_ms=5000,
    )
    d2 = metrics2.to_dict()
    assert "confidence" not in d2
    assert "context_gap" not in d2
    assert "tokens_per_loc" not in d2


# ---------------------------------------------------------------------------
# MetricsCollector: record_agent_meta / record_tokens_per_loc
# ---------------------------------------------------------------------------


def test_metrics_collector_agent_meta() -> None:
    """MetricsCollector should record confidence and context_gap."""
    from orx.metrics.collector import MetricsCollector

    collector = MetricsCollector(run_id="test_meta")
    with collector.stage("implement"):
        collector.record_agent_meta(confidence=0.8, context_gap=True)
        collector.record_tokens_per_loc(200.5)
        collector.record_success()

    stages = collector.get_stage_metrics()
    assert len(stages) == 1
    assert stages[0].confidence == 0.8
    assert stages[0].context_gap is True
    assert stages[0].tokens_per_loc == 200.5
