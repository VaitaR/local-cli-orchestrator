"""Fast E2E smoke tests for Claude Code engine."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SMOKE_PIPELINE_PATH = (
    Path(__file__).resolve().parent / "pipelines" / "smoke_quick.yaml"
)


def _skip_if_no_llm() -> None:
    if os.getenv("RUN_LLM_TESTS") != "1":
        pytest.skip("Set RUN_LLM_TESTS=1 to run LLM smoke tests")


def _write_config(path: Path, *, model: str) -> None:
    claude_model = model or os.getenv("ORX_E2E_CLAUDE_MODEL") or "haiku"

    config = f"""version: "1.0"

engine:
  type: claude_code
  timeout: 120

executors:
  claude_code:
    default:
      model: {claude_model}

stages:
  implement:
    executor: claude_code
    model: {claude_model}
  review:
    executor: claude_code
    model: {claude_model}

run:
  max_fix_attempts: 1
  stop_on_first_failure: true
  per_item_verify: fast
  max_backlog_items: 1

gates:
  - name: ruff
    enabled: false
    command: ruff
    args: ["check", "."]
  - name: pytest
    enabled: false
    command: pytest
    args: ["-q"]
"""
    path.write_text(config)


def _run_orx(repo: Path) -> tuple[int, str]:
    cmd = [
        os.environ.get("PYTHON", "python"),
        "-m",
        "orx.cli",
        "run",
        (
            "Smoke mode: apply exactly one tiny non-breaking edit to src/__init__.py "
            "and finish fast."
        ),
        "--dir",
        str(repo),
        "--engine",
        "claude_code",
        "--pipeline",
        str(SMOKE_PIPELINE_PATH),
    ]
    proc = subprocess.run(
        cmd,
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=420,
    )
    output = f"{proc.stdout}\n{proc.stderr}"
    return proc.returncode, output


def _extract_run_id(output: str) -> str:
    match = re.search(r"Run ID:\s+(\S+)", output)
    if not match:
        raise AssertionError(f"Run ID not found in output:\\n{output}")
    return match.group(1)


def test_claude_code_fast_pipeline_smoke(tmp_git_repo: Path) -> None:
    _skip_if_no_llm()

    if shutil.which("claude") is None:
        pytest.skip("claude binary not found in PATH")

    if not SMOKE_PIPELINE_PATH.exists():
        pytest.fail(f"Missing smoke pipeline: {SMOKE_PIPELINE_PATH}")

    config_path = tmp_git_repo / "orx.yaml"
    _write_config(config_path, model=os.getenv("ORX_E2E_CLAUDE_MODEL") or "haiku")

    code, output = _run_orx(tmp_git_repo)
    run_id = _extract_run_id(output)

    state_path = tmp_git_repo / "runs" / run_id / "state.json"
    assert state_path.exists(), f"Missing state.json for {run_id}"

    run_dir = state_path.parent
    events_path = run_dir / "observability" / "events.jsonl"
    assert events_path.exists(), f"Missing observability events for {run_id}"
    events = [json.loads(line) for line in events_path.read_text().splitlines() if line]

    implement_ends = [
        event
        for event in events
        if event.get("event_type") == "stage.end"
        and event.get("payload", {}).get("stage") == "implement"
    ]
    assert implement_ends, output
    assert implement_ends[-1].get("payload", {}).get("status") == "success", output

    review_ends = [
        event
        for event in events
        if event.get("event_type") == "stage.end"
        and event.get("payload", {}).get("stage") == "review"
    ]
    assert review_ends, output
    assert review_ends[-1].get("payload", {}).get("status") == "success", output

    run_end_events = [event for event in events if event.get("event_type") == "run.end"]
    assert run_end_events, output
    run_end_payload = run_end_events[-1].get("payload", {})
    run_status = run_end_payload.get("status")
    assert run_status == "success", output
    assert code == 0, output
