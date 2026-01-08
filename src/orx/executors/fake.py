"""Fake executor for testing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from orx.executors.base import BaseExecutor, ExecResult, LogPaths, ResolvedInvocation

if TYPE_CHECKING:
    from orx.config import ModelSelector

logger = structlog.get_logger()


@dataclass
class FakeAction:
    """Describes an action the fake executor should take.

    Attributes:
        file_path: Relative path to create/modify.
        content: Content to write (None to delete).
        append: If True, append instead of overwrite.
    """

    file_path: str
    content: str | None
    append: bool = False


@dataclass
class FakeScenario:
    """A scenario for the fake executor.

    Attributes:
        name: Name of the scenario.
        text_output: Content to return in text mode.
        actions: List of file actions to take in apply mode.
        returncode: Exit code to return.
        should_fail: If True, simulate failure.
        fail_on_attempt: Only fail on specific attempt number.
    """

    name: str
    text_output: str = ""
    actions: list[FakeAction] = field(default_factory=list)
    returncode: int = 0
    should_fail: bool = False
    fail_on_attempt: int | None = None


class FakeExecutor(BaseExecutor):
    """A fake executor for testing.

    This executor performs deterministic operations based on configured
    scenarios, allowing integration tests without real LLM calls.

    Example:
        >>> executor = FakeExecutor()
        >>> executor.add_scenario(FakeScenario(
        ...     name="implement",
        ...     actions=[FakeAction("src/app.py", "print('hello')")],
        ... ))
        >>> result = executor.run_apply(
        ...     cwd=Path("/workspace"),
        ...     prompt_path=Path("/prompts/implement.md"),
        ...     logs=LogPaths(stdout=Path("out.log"), stderr=Path("err.log")),
        ... )
    """

    def __init__(
        self,
        *,
        scenarios: list[FakeScenario] | None = None,
        default_scenario: FakeScenario | None = None,
        action_callback: Callable[[str, Path, LogPaths], None] | None = None,
    ) -> None:
        """Initialize the fake executor.

        Args:
            scenarios: List of scenarios indexed by stage name.
            default_scenario: Default scenario if no match found.
            action_callback: Optional callback for custom behavior.
        """
        super().__init__(binary="fake", dry_run=False)
        self._scenarios: dict[str, FakeScenario] = {}
        self._default_scenario = default_scenario or FakeScenario(name="default")
        self._attempt_counts: dict[str, int] = {}
        self._action_callback = action_callback

        for scenario in scenarios or []:
            self._scenarios[scenario.name] = scenario

    @property
    def name(self) -> str:
        """Name of the executor."""
        return "fake"

    def add_scenario(self, scenario: FakeScenario) -> None:
        """Add a scenario.

        Args:
            scenario: The scenario to add.
        """
        self._scenarios[scenario.name] = scenario

    def get_scenario(self, stage: str) -> FakeScenario:
        """Get the scenario for a stage.

        Args:
            stage: Stage name to look up.

        Returns:
            The matching scenario or default.
        """
        return self._scenarios.get(stage, self._default_scenario)

    def get_attempt_count(self, stage: str) -> int:
        """Get the attempt count for a stage.

        Args:
            stage: Stage name.

        Returns:
            Number of attempts for this stage.
        """
        return self._attempt_counts.get(stage, 0)

    def reset_attempts(self) -> None:
        """Reset all attempt counters."""
        self._attempt_counts.clear()

    def _extract_stage_from_prompt(self, prompt_path: Path) -> str:
        """Extract stage name from prompt path.

        Args:
            prompt_path: Path to the prompt file.

        Returns:
            Extracted stage name.
        """
        # Prompt files are named like "plan.md", "implement.md", etc.
        return prompt_path.stem

    def _increment_attempt(self, stage: str) -> int:
        """Increment and return attempt count for a stage.

        Args:
            stage: Stage name.

        Returns:
            New attempt count.
        """
        count = self._attempt_counts.get(stage, 0) + 1
        self._attempt_counts[stage] = count
        return count

    def resolve_invocation(
        self,
        *,
        prompt_path: Path,
        cwd: Path,  # noqa: ARG002
        logs: LogPaths,
        out_path: Path | None = None,
        model_selector: ModelSelector | None = None,
    ) -> ResolvedInvocation:
        """Resolve the command invocation without executing.

        Args:
            prompt_path: Path to the prompt file.
            cwd: Working directory.
            logs: Paths for stdout/stderr logs.
            out_path: Optional output path (for text mode).
            model_selector: Optional model selection configuration.

        Returns:
            ResolvedInvocation with command and artifacts.
        """
        stage = self._extract_stage_from_prompt(prompt_path)
        resolved = self._resolve_model(model_selector)

        cmd = ["fake", "exec", "--stage", stage]
        if resolved["model"]:
            cmd.extend(["--model", resolved["model"]])

        artifacts = {
            "stdout": logs.stdout,
            "stderr": logs.stderr,
        }
        if out_path:
            artifacts["output"] = out_path

        return ResolvedInvocation(
            cmd=cmd,
            artifacts=artifacts,
            model_info={
                "executor": self.name,
                "model": resolved["model"],
                "profile": resolved["profile"],
            },
        )

    def run_text(
        self,
        *,
        cwd: Path,
        prompt_path: Path,
        out_path: Path,
        logs: LogPaths,
        timeout: int | None = None,  # noqa: ARG002
        model_selector: ModelSelector | None = None,
    ) -> ExecResult:
        """Run fake executor in text mode.

        Args:
            cwd: Working directory (unused).
            prompt_path: Path to the prompt file.
            out_path: Path to write the output to.
            logs: Paths for stdout/stderr logs.
            timeout: Optional timeout (unused).
            model_selector: Optional model selection configuration.

        Returns:
            ExecResult with execution details.
        """
        stage = self._extract_stage_from_prompt(prompt_path)
        attempt = self._increment_attempt(stage)
        scenario = self.get_scenario(stage)

        invocation = self.resolve_invocation(
            prompt_path=prompt_path,
            cwd=cwd,
            logs=logs,
            out_path=out_path,
            model_selector=model_selector,
        )

        log = logger.bind(
            stage=stage,
            attempt=attempt,
            scenario=scenario.name,
            model=invocation.model_info.get("model"),
        )
        log.info("FakeExecutor running in text mode")

        # Create log files
        logs.stdout.parent.mkdir(parents=True, exist_ok=True)
        logs.stdout.write_text(f"[fake] Text mode for {stage}\n{scenario.text_output}")
        logs.stderr.write_text("")

        # Check for callback
        if self._action_callback:
            self._action_callback(stage, cwd, logs)

        # Check if should fail
        if scenario.should_fail and (
            scenario.fail_on_attempt is None or scenario.fail_on_attempt == attempt
        ):
            log.info("FakeExecutor simulating failure")
            return self._create_result(
                returncode=1,
                logs=logs,
                success=False,
                error_message="Simulated failure",
                invocation=invocation,
            )

        # Write output
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(scenario.text_output)

        log.info("FakeExecutor text mode completed")
        return self._create_result(
            returncode=scenario.returncode,
            logs=logs,
            success=scenario.returncode == 0,
            invocation=invocation,
        )

    def run_apply(
        self,
        *,
        cwd: Path,
        prompt_path: Path,
        logs: LogPaths,
        timeout: int | None = None,  # noqa: ARG002
        model_selector: ModelSelector | None = None,
    ) -> ExecResult:
        """Run fake executor in apply mode.

        Args:
            cwd: Working directory for file modifications.
            prompt_path: Path to the prompt file.
            logs: Paths for stdout/stderr logs.
            timeout: Optional timeout (unused).
            model_selector: Optional model selection configuration.

        Returns:
            ExecResult with execution details.
        """
        stage = self._extract_stage_from_prompt(prompt_path)
        attempt = self._increment_attempt(stage)
        scenario = self.get_scenario(stage)

        invocation = self.resolve_invocation(
            prompt_path=prompt_path,
            cwd=cwd,
            logs=logs,
            model_selector=model_selector,
        )

        log = logger.bind(
            stage=stage,
            attempt=attempt,
            scenario=scenario.name,
            model=invocation.model_info.get("model"),
        )
        log.info("FakeExecutor running in apply mode")

        # Create log files
        logs.stdout.parent.mkdir(parents=True, exist_ok=True)
        logs.stdout.write_text(f"[fake] Apply mode for {stage}\n")
        logs.stderr.write_text("")

        # Check for callback
        if self._action_callback:
            self._action_callback(stage, cwd, logs)

        # Check if should fail
        if scenario.should_fail and (
            scenario.fail_on_attempt is None or scenario.fail_on_attempt == attempt
        ):
            log.info("FakeExecutor simulating failure")
            return self._create_result(
                returncode=1,
                logs=logs,
                success=False,
                error_message="Simulated failure",
                invocation=invocation,
            )

        # Apply file actions
        for action in scenario.actions:
            file_path = cwd / action.file_path
            file_path.parent.mkdir(parents=True, exist_ok=True)

            if action.content is None:
                # Delete file
                if file_path.exists():
                    file_path.unlink()
                log.debug("Deleted file", path=action.file_path)
            elif action.append:
                # Append to file
                existing = file_path.read_text() if file_path.exists() else ""
                file_path.write_text(existing + action.content)
                log.debug("Appended to file", path=action.file_path)
            else:
                # Write/overwrite file
                file_path.write_text(action.content)
                log.debug("Wrote file", path=action.file_path)

        log.info("FakeExecutor apply mode completed", actions=len(scenario.actions))
        return self._create_result(
            returncode=scenario.returncode,
            logs=logs,
            success=scenario.returncode == 0,
            invocation=invocation,
        )


# Pre-built scenarios for common testing needs


def create_happy_path_scenarios() -> list[FakeScenario]:
    """Create scenarios for a happy path test.

    Returns:
        List of scenarios that simulate successful execution.
    """
    return [
        FakeScenario(
            name="plan",
            text_output="""# Plan

## Overview
Implement the requested feature.

## Steps
1. Create the function
2. Add tests
3. Verify

## Risks
- None identified
""",
        ),
        FakeScenario(
            name="spec",
            text_output="""# Specification

## Acceptance Criteria
- Function exists and is callable
- All tests pass
- Code follows style guidelines

## Constraints
- Must be Python 3.11+
- Use type hints
""",
        ),
        FakeScenario(
            name="decompose",
            text_output="""run_id: "test_run"
items:
  - id: "W001"
    title: "Implement function"
    objective: "Create the main function"
    acceptance:
      - "Function exists"
      - "Tests pass"
    files_hint:
      - "src/app.py"
    depends_on: []
    status: "todo"
    attempts: 0
    notes: ""
""",
        ),
        FakeScenario(
            name="implement",
            actions=[
                FakeAction(
                    "src/app.py",
                    '''"""Application module."""


def add(a: int, b: int) -> int:
    """Add two numbers.

    Args:
        a: First number.
        b: Second number.

    Returns:
        Sum of a and b.
    """
    return a + b
''',
                ),
                FakeAction(
                    "tests/test_app.py",
                    '''"""Tests for app module."""

from src.app import add


def test_add() -> None:
    """Test add function."""
    assert add(1, 2) == 3
    assert add(0, 0) == 0
    assert add(-1, 1) == 0
''',
                ),
            ],
        ),
        FakeScenario(
            name="review",
            text_output="""# Code Review

## Summary
All changes look good.

## Observations
- Code follows best practices
- Tests are comprehensive
- Type hints are present

## Recommendations
None - ready to merge.
""",
        ),
    ]


def create_fix_loop_scenarios() -> list[FakeScenario]:
    """Create scenarios that require a fix loop.

    Returns:
        List of scenarios where first attempt fails.
    """
    return [
        FakeScenario(
            name="implement",
            actions=[
                FakeAction(
                    "src/app.py",
                    '''"""Application module."""


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a - b  # Bug: should be +
''',
                ),
            ],
            should_fail=False,  # Code is written but tests will fail
        ),
        FakeScenario(
            name="fix",
            actions=[
                FakeAction(
                    "src/app.py",
                    '''"""Application module."""


def add(a: int, b: int) -> int:
    """Add two numbers.

    Args:
        a: First number.
        b: Second number.

    Returns:
        Sum of a and b.
    """
    return a + b  # Fixed
''',
                ),
            ],
        ),
    ]
