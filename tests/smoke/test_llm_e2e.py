"""E2E smoke tests for Codex/Gemini engines."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PROMPT = "This is just a test run, nothing needs to be fixed."


def _skip_if_no_llm() -> None:
    if os.getenv("RUN_LLM_TESTS") != "1":
        pytest.skip("Set RUN_LLM_TESTS=1 to run LLM smoke tests")


def _write_config(path: Path, *, engine: str, model: str) -> None:
    codex_model = os.getenv("ORX_E2E_CODEX_MODEL") or "gpt-5.2"
    gemini_model = os.getenv("ORX_E2E_GEMINI_MODEL") or "gemini-2.5-pro"
    if engine == "codex":
        codex_model = model
    if engine == "gemini":
        gemini_model = model

    config = f"""version: "1.0"

engine:
  type: {engine}
  timeout: 180

executors:
  codex:
    default:
      model: {codex_model}
  gemini:
    default:
      model: {gemini_model}

stages:
  plan:
    web_search: false
  spec:
    web_search: false
  fix:
    web_search: false

run:
  max_fix_attempts: 1
  stop_on_first_failure: true
  per_item_verify: fast

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


def _run_orx(repo: Path, *, engine: str) -> tuple[int, str]:
    cmd = [
        os.environ.get("PYTHON", "python"),
        "-m",
        "orx.cli",
        "run",
        PROMPT,
        "--dir",
        str(repo),
        "--engine",
        engine,
    ]
    proc = subprocess.run(
        cmd,
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=900,
    )
    output = f"{proc.stdout}\n{proc.stderr}"
    return proc.returncode, output


def _extract_run_id(output: str) -> str:
    match = re.search(r"Run ID:\\s+(\\S+)", output)
    if not match:
        raise AssertionError(f"Run ID not found in output:\\n{output}")
    return match.group(1)


@pytest.mark.parametrize(
    ("engine", "binary", "model_env"),
    [
        ("codex", "codex", "ORX_E2E_CODEX_MODEL"),
        ("gemini", "gemini", "ORX_E2E_GEMINI_MODEL"),
    ],
)
def test_llm_engines_e2e(
    tmp_git_repo: Path,
    engine: str,
    binary: str,
    model_env: str,
) -> None:
    _skip_if_no_llm()

    if shutil.which(binary) is None:
        pytest.skip(f"{binary} binary not found in PATH")

    if not os.getenv(model_env):
        pytest.skip(f"Set {model_env} to run this smoke test")

    config_path = tmp_git_repo / "orx.yaml"
    _write_config(config_path, engine=engine, model=os.environ[model_env])

    code, output = _run_orx(tmp_git_repo, engine=engine)
    run_id = _extract_run_id(output)

    state_path = tmp_git_repo / "runs" / run_id / "state.json"
    assert state_path.exists(), f"Missing state.json for {run_id}"

    state = json.loads(state_path.read_text())
    plan_status = state["stage_statuses"]["plan"]["status"]
    assert plan_status != "failed", output

    # Expect either success or an empty-diff failure (no-op prompt).
    current_stage = state["current_stage"]
    if current_stage == "done":
        return

    assert current_stage == "failed", output
    assert state.get("last_failure_evidence", {}).get("diff_empty") is True
