"""Integration tests for model routing with fake CLI binaries."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from orx.config import (
    EngineConfig,
    EngineType,
    ExecutorConfig,
    ExecutorDefaults,
    ExecutorsConfig,
    FallbackMatchConfig,
    FallbackPolicyConfig,
    FallbackRule,
    FallbackSwitchConfig,
    ModelSelector,
    OrxConfig,
    StageExecutorConfig,
    StagesConfig,
)
from orx.executors.base import LogPaths
from orx.executors.codex import CodexExecutor
from orx.executors.gemini import GeminiExecutor
from orx.infra.command import CommandRunner


@pytest.fixture
def fake_codex_script(tmp_path: Path) -> Path:
    """Create a fake codex CLI that records its invocation."""
    fake_bin = tmp_path / "bin" / "fake_codex"
    fake_bin.parent.mkdir(parents=True, exist_ok=True)

    script = '''#!/bin/bash
# Fake Codex CLI for testing

# Write all arguments to a JSON file
ARGS_FILE="${FAKE_CODEX_ARGS_FILE:-/tmp/fake_codex_args.json}"

# Build JSON array of args
ARGS_JSON="["
FIRST=1
for arg in "$@"; do
    if [ $FIRST -eq 1 ]; then
        FIRST=0
    else
        ARGS_JSON+=","
    fi
    # Escape quotes in argument
    escaped=$(echo "$arg" | sed 's/"/\\\\"/g')
    ARGS_JSON+="\\\"$escaped\\\""
done
ARGS_JSON+="]"

echo "{" > "$ARGS_FILE"
echo "  \\"args\\": $ARGS_JSON," >> "$ARGS_FILE"
echo "  \\"cwd\\": \\"$(pwd)\\"" >> "$ARGS_FILE"
echo "}" >> "$ARGS_FILE"

# Check for simulated errors
if [ "$FAKE_CODEX_EXIT_CODE" != "" ]; then
    if [ "$FAKE_CODEX_STDERR" != "" ]; then
        echo "$FAKE_CODEX_STDERR" >&2
    fi
    exit $FAKE_CODEX_EXIT_CODE
fi

# Normal output
echo "Fake codex executed successfully"
echo "Model selection recorded"
'''
    fake_bin.write_text(script)
    fake_bin.chmod(fake_bin.stat().st_mode | stat.S_IEXEC)
    return fake_bin


@pytest.fixture
def fake_gemini_script(tmp_path: Path) -> Path:
    """Create a fake gemini CLI that records its invocation."""
    fake_bin = tmp_path / "bin" / "fake_gemini"
    fake_bin.parent.mkdir(parents=True, exist_ok=True)

    script = '''#!/bin/bash
# Fake Gemini CLI for testing

# Write all arguments to a JSON file
ARGS_FILE="${FAKE_GEMINI_ARGS_FILE:-/tmp/fake_gemini_args.json}"

# Build JSON array of args
ARGS_JSON="["
FIRST=1
for arg in "$@"; do
    if [ $FIRST -eq 1 ]; then
        FIRST=0
    else
        ARGS_JSON+=","
    fi
    # Escape quotes in argument
    escaped=$(echo "$arg" | sed 's/"/\\\\"/g')
    ARGS_JSON+="\\\"$escaped\\\""
done
ARGS_JSON+="]"

echo "{" > "$ARGS_FILE"
echo "  \\"args\\": $ARGS_JSON," >> "$ARGS_FILE"
echo "  \\"cwd\\": \\"$(pwd)\\"" >> "$ARGS_FILE"
echo "}" >> "$ARGS_FILE"

# Check for simulated errors
if [ "$FAKE_GEMINI_EXIT_CODE" != "" ]; then
    if [ "$FAKE_GEMINI_STDERR" != "" ]; then
        echo "$FAKE_GEMINI_STDERR" >&2
    fi
    exit $FAKE_GEMINI_EXIT_CODE
fi

# Normal JSON output
echo "{\\"response\\": \\"Fake gemini response\\", \\"status\\": \\"success\\"}"
'''
    fake_bin.write_text(script)
    fake_bin.chmod(fake_bin.stat().st_mode | stat.S_IEXEC)
    return fake_bin


class TestCodexModelSelection:
    """Integration tests for Codex model selection."""

    def test_codex_receives_model_flag(
        self,
        fake_codex_script: Path,
        tmp_path: Path,
    ) -> None:
        """Codex CLI receives --model/-m flag when model is specified."""
        args_file = tmp_path / "args.json"
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("Test prompt")

        env = os.environ.copy()
        env["FAKE_CODEX_ARGS_FILE"] = str(args_file)

        cmd = CommandRunner()
        executor = CodexExecutor(
            cmd=cmd,
            binary=str(fake_codex_script),
        )

        logs = LogPaths(
            stdout=tmp_path / "stdout.log",
            stderr=tmp_path / "stderr.log",
        )

        selector = ModelSelector(model="gpt-5.2")

        # Run with custom env
        invocation = executor.resolve_invocation(
            prompt_path=prompt_file,
            cwd=tmp_path,
            logs=logs,
            model_selector=selector,
        )

        # Execute the command directly to verify args
        result = subprocess.run(
            invocation.cmd,
            cwd=tmp_path,
            capture_output=True,
            env=env,
        )

        assert result.returncode == 0

        # Check recorded args
        recorded = json.loads(args_file.read_text())
        args = recorded["args"]

        assert "-m" in args
        model_idx = args.index("-m")
        assert args[model_idx + 1] == "gpt-5.2"

    def test_codex_receives_profile_flag(
        self,
        fake_codex_script: Path,
        tmp_path: Path,
    ) -> None:
        """Codex CLI receives --profile/-p flag when profile is specified."""
        args_file = tmp_path / "args.json"
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("Test prompt")

        env = os.environ.copy()
        env["FAKE_CODEX_ARGS_FILE"] = str(args_file)

        cmd = CommandRunner()
        executor = CodexExecutor(
            cmd=cmd,
            binary=str(fake_codex_script),
        )

        logs = LogPaths(
            stdout=tmp_path / "stdout.log",
            stderr=tmp_path / "stderr.log",
        )

        selector = ModelSelector(profile="deep-review")

        invocation = executor.resolve_invocation(
            prompt_path=prompt_file,
            cwd=tmp_path,
            logs=logs,
            model_selector=selector,
        )

        result = subprocess.run(
            invocation.cmd,
            cwd=tmp_path,
            capture_output=True,
            env=env,
        )

        assert result.returncode == 0

        recorded = json.loads(args_file.read_text())
        args = recorded["args"]

        assert "-p" in args
        profile_idx = args.index("-p")
        assert args[profile_idx + 1] == "deep-review"

    def test_codex_receives_reasoning_effort(
        self,
        fake_codex_script: Path,
        tmp_path: Path,
    ) -> None:
        """Codex CLI receives reasoning effort config."""
        args_file = tmp_path / "args.json"
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("Test prompt")

        env = os.environ.copy()
        env["FAKE_CODEX_ARGS_FILE"] = str(args_file)

        cmd = CommandRunner()
        executor = CodexExecutor(
            cmd=cmd,
            binary=str(fake_codex_script),
        )

        logs = LogPaths(
            stdout=tmp_path / "stdout.log",
            stderr=tmp_path / "stderr.log",
        )

        selector = ModelSelector(model="gpt-5.2", reasoning_effort="high")

        invocation = executor.resolve_invocation(
            prompt_path=prompt_file,
            cwd=tmp_path,
            logs=logs,
            model_selector=selector,
        )

        result = subprocess.run(
            invocation.cmd,
            cwd=tmp_path,
            capture_output=True,
            env=env,
        )

        assert result.returncode == 0

        recorded = json.loads(args_file.read_text())
        args = recorded["args"]

        assert "--config" in args
        config_idx = args.index("--config")
        assert "model_reasoning_effort" in args[config_idx + 1]
        assert "high" in args[config_idx + 1]


class TestGeminiModelSelection:
    """Integration tests for Gemini model selection."""

    def test_gemini_receives_model_flag(
        self,
        fake_gemini_script: Path,
        tmp_path: Path,
    ) -> None:
        """Gemini CLI receives --model flag when model is specified."""
        args_file = tmp_path / "args.json"
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("Test prompt")

        env = os.environ.copy()
        env["FAKE_GEMINI_ARGS_FILE"] = str(args_file)

        cmd = CommandRunner()
        executor = GeminiExecutor(
            cmd=cmd,
            binary=str(fake_gemini_script),
        )

        logs = LogPaths(
            stdout=tmp_path / "stdout.log",
            stderr=tmp_path / "stderr.log",
        )

        selector = ModelSelector(model="gemini-2.5-pro")

        invocation = executor.resolve_invocation(
            prompt_path=prompt_file,
            cwd=tmp_path,
            logs=logs,
            model_selector=selector,
        )

        result = subprocess.run(
            invocation.cmd,
            cwd=tmp_path,
            capture_output=True,
            env=env,
        )

        assert result.returncode == 0

        recorded = json.loads(args_file.read_text())
        args = recorded["args"]

        assert "--model" in args
        model_idx = args.index("--model")
        assert args[model_idx + 1] == "gemini-2.5-pro"


class TestFallbackWithFakeBinaries:
    """Integration tests for fallback behavior with fake CLIs."""

    def test_fallback_on_quota_error(
        self,
        tmp_path: Path,
    ) -> None:
        """Fallback triggered when CLI returns quota error."""
        from orx.executors.base import ExecResult
        from orx.executors.router import ModelRouter

        cmd = CommandRunner()

        # Simulate a failed result with quota error
        stderr_path = tmp_path / "stderr.log"
        stderr_path.write_text("Error: quota exceeded for model gemini-2.5-pro")

        result = ExecResult(
            returncode=1,
            stdout_path=tmp_path / "stdout.log",
            stderr_path=stderr_path,
            success=False,
            error_message="Error: quota exceeded for model gemini-2.5-pro",
        )

        assert result.failed
        assert result.is_quota_error()

        selector = ModelSelector(model="gemini-2.5-pro")

        # Create router and check fallback
        router = ModelRouter(
            engine=EngineConfig(type=EngineType.GEMINI),
            executors=ExecutorsConfig(),
            stages=StagesConfig(),
            fallback=FallbackPolicyConfig(
                enabled=True,
                rules=[
                    FallbackRule(
                        match=FallbackMatchConfig(
                            executor=EngineType.GEMINI,
                            error_contains=["quota"],
                        ),
                        switch_to=FallbackSwitchConfig(model="gemini-2.5-flash"),
                    ),
                ],
            ),
            cmd=cmd,
            dry_run=True,
        )

        new_selector, applied = router.apply_fallback("plan", result, selector)
        assert applied is True
        assert new_selector.model == "gemini-2.5-flash"


class TestArtifactCreation:
    """Test that artifacts are created correctly."""

    def test_stdout_stderr_logs_created(
        self,
        fake_codex_script: Path,
        tmp_path: Path,
    ) -> None:
        """Stdout and stderr logs are created."""
        args_file = tmp_path / "args.json"
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("Test prompt")

        env = os.environ.copy()
        env["FAKE_CODEX_ARGS_FILE"] = str(args_file)

        cmd = CommandRunner()
        executor = CodexExecutor(
            cmd=cmd,
            binary=str(fake_codex_script),
        )

        logs = LogPaths(
            stdout=tmp_path / "logs" / "stdout.log",
            stderr=tmp_path / "logs" / "stderr.log",
        )

        selector = ModelSelector(model="gpt-5.2")

        # Run executor (will use the fake binary)
        result = executor.run_apply(
            cwd=tmp_path,
            prompt_path=prompt_file,
            logs=logs,
            model_selector=selector,
        )

        # Note: The fake binary runs but our CommandRunner captures output
        # The logs should exist after execution
        assert logs.stdout.parent.exists()

    def test_invocation_recorded_in_result(
        self,
        fake_codex_script: Path,
        tmp_path: Path,
    ) -> None:
        """Invocation details recorded in result."""
        args_file = tmp_path / "args.json"

        env = os.environ.copy()
        env["FAKE_CODEX_ARGS_FILE"] = str(args_file)

        cmd = CommandRunner()
        executor = CodexExecutor(
            cmd=cmd,
            binary=str(fake_codex_script),
        )

        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("Test prompt")

        logs = LogPaths(
            stdout=tmp_path / "stdout.log",
            stderr=tmp_path / "stderr.log",
        )

        selector = ModelSelector(model="gpt-5.2", reasoning_effort="high")

        # Run with real fake binary (not dry run)
        result = executor.run_apply(
            cwd=tmp_path,
            prompt_path=prompt_file,
            logs=logs,
            model_selector=selector,
        )

        # Should succeed (fake binary returns 0)
        assert result.success

        # Invocation should be recorded
        invocation = result.invocation
        assert invocation is not None
        assert invocation.model_info["executor"] == "codex"
        assert invocation.model_info["model"] == "gpt-5.2"
        assert invocation.model_info["reasoning_effort"] == "high"
        assert "-m" in invocation.cmd
        assert "gpt-5.2" in invocation.cmd
