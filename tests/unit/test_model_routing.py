"""Unit tests for model routing and selection."""

from __future__ import annotations

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
    StageExecutorConfig,
    StagesConfig,
)
from orx.executors.base import ExecResult, LogPaths
from orx.executors.router import ModelRouter
from orx.infra.command import CommandRunner


class TestModelSelector:
    """Test ModelSelector configuration."""

    def test_model_selector_with_model(self) -> None:
        """Model selector with model specified."""
        selector = ModelSelector(model="gpt-5.2")
        assert selector.model == "gpt-5.2"
        assert selector.profile is None
        assert selector.reasoning_effort is None

    def test_model_selector_with_profile(self) -> None:
        """Model selector with profile specified."""
        selector = ModelSelector(profile="deep-review")
        assert selector.model is None
        assert selector.profile == "deep-review"

    def test_model_selector_with_reasoning_effort(self) -> None:
        """Model selector with reasoning effort."""
        selector = ModelSelector(model="gpt-5.2", reasoning_effort="high")
        assert selector.model == "gpt-5.2"
        assert selector.reasoning_effort == "high"

    def test_model_selector_cannot_have_both_model_and_profile(self) -> None:
        """Cannot specify both model and profile."""
        with pytest.raises(ValueError, match="Cannot specify both"):
            ModelSelector(model="gpt-5.2", profile="deep-review")


class TestStageExecutorConfig:
    """Test StageExecutorConfig."""

    def test_stage_config_with_model(self) -> None:
        """Stage config with model override."""
        cfg = StageExecutorConfig(
            executor=EngineType.CODEX,
            model="gpt-5.2",
            reasoning_effort="high",
        )
        assert cfg.executor == EngineType.CODEX
        assert cfg.model == "gpt-5.2"
        assert cfg.reasoning_effort == "high"

    def test_stage_config_to_model_selector(self) -> None:
        """Convert stage config to model selector."""
        cfg = StageExecutorConfig(
            model="gpt-5.2",
            reasoning_effort="high",
        )
        selector = cfg.to_model_selector()
        assert selector.model == "gpt-5.2"
        assert selector.reasoning_effort == "high"

    def test_stage_config_cannot_have_both_model_and_profile(self) -> None:
        """Cannot specify both model and profile in stage config."""
        with pytest.raises(ValueError, match="Cannot specify both"):
            StageExecutorConfig(model="gpt-5.2", profile="deep-review")


class TestModelRouter:
    """Test ModelRouter functionality."""

    @pytest.fixture
    def cmd(self) -> CommandRunner:
        """Create a dry-run command runner."""
        return CommandRunner(dry_run=True)

    @pytest.fixture
    def base_engine(self) -> EngineConfig:
        """Create base engine config."""
        return EngineConfig(
            type=EngineType.CODEX,
            model="default-model",
        )

    @pytest.fixture
    def executors_config(self) -> ExecutorsConfig:
        """Create executors config."""
        return ExecutorsConfig(
            codex=ExecutorConfig(
                bin="codex",
                default=ExecutorDefaults(
                    model="codex-default-model",
                    reasoning_effort="medium",
                ),
                profiles={
                    "plan": "lightweight",
                    "review": "deep-review",
                },
            ),
            gemini=ExecutorConfig(
                bin="gemini",
                default=ExecutorDefaults(
                    model="gemini-default-model",
                    output_format="json",
                ),
            ),
        )

    @pytest.fixture
    def stages_config(self) -> StagesConfig:
        """Create stages config with overrides."""
        return StagesConfig(
            plan=StageExecutorConfig(
                executor=EngineType.GEMINI,
                model="gemini-2.5-flash",
            ),
            implement=StageExecutorConfig(
                executor=EngineType.CODEX,
                model="gpt-5.2",
                reasoning_effort="high",
            ),
            review=StageExecutorConfig(
                executor=EngineType.GEMINI,
                model="gemini-2.5-pro",
            ),
        )

    @pytest.fixture
    def fallback_config(self) -> FallbackPolicyConfig:
        """Create fallback policy config."""
        return FallbackPolicyConfig(
            enabled=True,
            rules=[
                FallbackRule(
                    match=FallbackMatchConfig(
                        executor=EngineType.GEMINI,
                        error_contains=["limit", "quota", "capacity"],
                    ),
                    switch_to=FallbackSwitchConfig(model="gemini-2.5-flash"),
                ),
                FallbackRule(
                    match=FallbackMatchConfig(
                        executor=EngineType.CODEX,
                        error_contains=["model not found", "not available"],
                    ),
                    switch_to=FallbackSwitchConfig(model="gpt-4.1"),
                ),
            ],
        )

    @pytest.fixture
    def router(
        self,
        cmd: CommandRunner,
        base_engine: EngineConfig,
        executors_config: ExecutorsConfig,
        stages_config: StagesConfig,
        fallback_config: FallbackPolicyConfig,
    ) -> ModelRouter:
        """Create a model router."""
        return ModelRouter(
            engine=base_engine,
            executors=executors_config,
            stages=stages_config,
            fallback=fallback_config,
            cmd=cmd,
            dry_run=True,
        )

    def test_stage_model_override_takes_priority(self, router: ModelRouter) -> None:
        """Stage-level model override takes highest priority."""
        executor, selector = router.get_executor_for_stage("implement")
        assert selector.model == "gpt-5.2"
        assert selector.reasoning_effort == "high"
        assert executor.name == "codex"

    def test_stage_can_use_different_executor(self, router: ModelRouter) -> None:
        """Stage can specify a different executor than default."""
        executor, selector = router.get_executor_for_stage("plan")
        assert executor.name == "gemini"
        assert selector.model == "gemini-2.5-flash"

    def test_executor_profile_used_when_no_stage_override(
        self,
        cmd: CommandRunner,
        base_engine: EngineConfig,
        executors_config: ExecutorsConfig,
        fallback_config: FallbackPolicyConfig,
    ) -> None:
        """Executor profile is used when no stage model override."""
        # Create stages config without model override for spec
        stages_config = StagesConfig()

        router = ModelRouter(
            engine=base_engine,
            executors=executors_config,
            stages=stages_config,
            fallback=fallback_config,
            cmd=cmd,
            dry_run=True,
        )

        # spec has no override, should use executor default
        executor, selector = router.get_executor_for_stage("spec")
        assert executor.name == "codex"
        assert selector.model == "codex-default-model"
        assert selector.reasoning_effort == "medium"

    def test_fallback_on_quota_error(
        self,
        router: ModelRouter,
        tmp_path: Path,
    ) -> None:
        """Fallback applies when quota error detected."""
        logs = LogPaths(
            stdout=tmp_path / "stdout.log",
            stderr=tmp_path / "stderr.log",
        )
        logs.stdout.parent.mkdir(parents=True, exist_ok=True)
        logs.stdout.write_text("")
        logs.stderr.write_text("Error: quota exceeded - try again later")

        result = ExecResult(
            returncode=1,
            stdout_path=logs.stdout,
            stderr_path=logs.stderr,
            success=False,
            error_message="Command failed",
        )

        current_selector = ModelSelector(model="gemini-2.5-pro")
        new_selector, applied = router.apply_fallback("plan", result, current_selector)

        assert applied is True
        assert new_selector.model == "gemini-2.5-flash"

    def test_fallback_on_model_unavailable(
        self,
        router: ModelRouter,
        tmp_path: Path,
    ) -> None:
        """Fallback applies when model unavailable error detected."""
        logs = LogPaths(
            stdout=tmp_path / "stdout.log",
            stderr=tmp_path / "stderr.log",
        )
        logs.stdout.parent.mkdir(parents=True, exist_ok=True)
        logs.stdout.write_text("")
        logs.stderr.write_text("Error: model not found: gpt-5.2")

        result = ExecResult(
            returncode=1,
            stdout_path=logs.stdout,
            stderr_path=logs.stderr,
            success=False,
            error_message="model not found",
        )

        current_selector = ModelSelector(model="gpt-5.2")
        new_selector, applied = router.apply_fallback(
            "implement", result, current_selector
        )

        assert applied is True
        assert new_selector.model == "gpt-4.1"

    def test_no_fallback_when_disabled(
        self,
        cmd: CommandRunner,
        base_engine: EngineConfig,
        executors_config: ExecutorsConfig,
        stages_config: StagesConfig,
        tmp_path: Path,
    ) -> None:
        """No fallback when policy is disabled."""
        router = ModelRouter(
            engine=base_engine,
            executors=executors_config,
            stages=stages_config,
            fallback=FallbackPolicyConfig(enabled=False),
            cmd=cmd,
            dry_run=True,
        )

        logs = LogPaths(
            stdout=tmp_path / "stdout.log",
            stderr=tmp_path / "stderr.log",
        )
        logs.stdout.parent.mkdir(parents=True, exist_ok=True)
        logs.stdout.write_text("")
        logs.stderr.write_text("Error: quota exceeded")

        result = ExecResult(
            returncode=1,
            stdout_path=logs.stdout,
            stderr_path=logs.stderr,
            success=False,
            error_message="quota exceeded",
        )

        current_selector = ModelSelector(model="gemini-2.5-pro")
        new_selector, applied = router.apply_fallback("plan", result, current_selector)

        assert applied is False
        assert new_selector.model == "gemini-2.5-pro"

    def test_no_fallback_on_success(
        self,
        router: ModelRouter,
        tmp_path: Path,
    ) -> None:
        """No fallback when execution succeeded."""
        logs = LogPaths(
            stdout=tmp_path / "stdout.log",
            stderr=tmp_path / "stderr.log",
        )
        logs.stdout.parent.mkdir(parents=True, exist_ok=True)
        logs.stdout.write_text("Success")
        logs.stderr.write_text("")

        result = ExecResult(
            returncode=0,
            stdout_path=logs.stdout,
            stderr_path=logs.stderr,
            success=True,
        )

        current_selector = ModelSelector(model="gemini-2.5-pro")
        new_selector, applied = router.apply_fallback("plan", result, current_selector)

        assert applied is False
        assert new_selector.model == "gemini-2.5-pro"


class TestCodexCommandBuilder:
    """Test Codex command building with model selection."""

    @pytest.fixture
    def cmd(self) -> CommandRunner:
        """Create a dry-run command runner."""
        return CommandRunner(dry_run=True)

    def test_codex_command_with_model(self, cmd: CommandRunner) -> None:
        """Codex command includes -m flag when model specified."""
        from orx.executors.codex import CodexExecutor

        executor = CodexExecutor(cmd=cmd, dry_run=True)
        selector = ModelSelector(model="gpt-5.2")

        invocation = executor.resolve_invocation(
            prompt_path=Path("/tmp/prompt.md"),
            cwd=Path("/tmp/workspace"),
            logs=LogPaths(
                stdout=Path("/tmp/stdout.log"),
                stderr=Path("/tmp/stderr.log"),
            ),
            model_selector=selector,
        )

        assert "-m" in invocation.cmd
        assert "gpt-5.2" in invocation.cmd
        assert invocation.model_info["model"] == "gpt-5.2"

    def test_codex_command_with_profile(self, cmd: CommandRunner) -> None:
        """Codex command includes -p flag when profile specified."""
        from orx.executors.codex import CodexExecutor

        executor = CodexExecutor(cmd=cmd, dry_run=True)
        selector = ModelSelector(profile="deep-review")

        invocation = executor.resolve_invocation(
            prompt_path=Path("/tmp/prompt.md"),
            cwd=Path("/tmp/workspace"),
            logs=LogPaths(
                stdout=Path("/tmp/stdout.log"),
                stderr=Path("/tmp/stderr.log"),
            ),
            model_selector=selector,
        )

        assert "-p" in invocation.cmd
        assert "deep-review" in invocation.cmd
        assert invocation.model_info["profile"] == "deep-review"

    def test_codex_command_with_reasoning_effort(self, cmd: CommandRunner) -> None:
        """Codex command includes reasoning effort config."""
        from orx.executors.codex import CodexExecutor

        executor = CodexExecutor(cmd=cmd, dry_run=True)
        selector = ModelSelector(model="gpt-5.2", reasoning_effort="high")

        invocation = executor.resolve_invocation(
            prompt_path=Path("/tmp/prompt.md"),
            cwd=Path("/tmp/workspace"),
            logs=LogPaths(
                stdout=Path("/tmp/stdout.log"),
                stderr=Path("/tmp/stderr.log"),
            ),
            model_selector=selector,
        )

        assert "--config" in invocation.cmd
        # Find the config value
        config_idx = invocation.cmd.index("--config")
        assert 'model_reasoning_effort="high"' in invocation.cmd[config_idx + 1]
        assert invocation.model_info["reasoning_effort"] == "high"


class TestGeminiCommandBuilder:
    """Test Gemini command building with model selection."""

    @pytest.fixture
    def cmd(self) -> CommandRunner:
        """Create a dry-run command runner."""
        return CommandRunner(dry_run=True)

    def test_gemini_command_with_model(self, cmd: CommandRunner) -> None:
        """Gemini command includes --model flag when specified."""
        from orx.executors.gemini import GeminiExecutor

        executor = GeminiExecutor(cmd=cmd, dry_run=True)
        selector = ModelSelector(model="gemini-2.5-pro")

        invocation = executor.resolve_invocation(
            prompt_path=Path("/tmp/prompt.md"),
            cwd=Path("/tmp/workspace"),
            logs=LogPaths(
                stdout=Path("/tmp/stdout.log"),
                stderr=Path("/tmp/stderr.log"),
            ),
            model_selector=selector,
        )

        assert "--model" in invocation.cmd
        assert "gemini-2.5-pro" in invocation.cmd
        assert invocation.model_info["model"] == "gemini-2.5-pro"

    def test_gemini_command_includes_output_format(self, cmd: CommandRunner) -> None:
        """Gemini command includes output format."""
        from orx.executors.gemini import GeminiExecutor

        executor = GeminiExecutor(cmd=cmd, dry_run=True, output_format="json")
        selector = ModelSelector(model="gemini-2.5-pro")

        invocation = executor.resolve_invocation(
            prompt_path=Path("/tmp/prompt.md"),
            cwd=Path("/tmp/workspace"),
            logs=LogPaths(
                stdout=Path("/tmp/stdout.log"),
                stderr=Path("/tmp/stderr.log"),
            ),
            model_selector=selector,
        )

        assert "--output-format" in invocation.cmd
        assert "json" in invocation.cmd


class TestModelResolutionPriority:
    """Test model resolution priority order."""

    @pytest.fixture
    def cmd(self) -> CommandRunner:
        """Create a dry-run command runner."""
        return CommandRunner(dry_run=True)

    def test_priority_order(self, cmd: CommandRunner) -> None:
        """Test that model resolution follows correct priority."""
        # Priority: stage.model > executor.profiles[stage] > executor.default.model > engine.model

        engine = EngineConfig(
            type=EngineType.CODEX,
            model="engine-model",
        )

        executors = ExecutorsConfig(
            codex=ExecutorConfig(
                default=ExecutorDefaults(model="executor-default-model"),
                profiles={"plan": "executor-profile"},
            ),
        )

        # Test 1: Stage model takes priority
        stages_with_model = StagesConfig(
            plan=StageExecutorConfig(model="stage-model"),
        )
        router1 = ModelRouter(
            engine=engine,
            executors=executors,
            stages=stages_with_model,
            fallback=FallbackPolicyConfig(enabled=False),
            cmd=cmd,
            dry_run=True,
        )
        _, selector1 = router1.get_executor_for_stage("plan")
        assert selector1.model == "stage-model"

        # Test 2: Executor default used when no stage override
        stages_empty = StagesConfig()
        router2 = ModelRouter(
            engine=engine,
            executors=executors,
            stages=stages_empty,
            fallback=FallbackPolicyConfig(enabled=False),
            cmd=cmd,
            dry_run=True,
        )
        _, selector2 = router2.get_executor_for_stage("spec")
        assert selector2.model == "executor-default-model"

        # Test 3: Engine model as fallback
        executors_no_default = ExecutorsConfig(
            codex=ExecutorConfig(default=ExecutorDefaults()),
        )
        router3 = ModelRouter(
            engine=engine,
            executors=executors_no_default,
            stages=stages_empty,
            fallback=FallbackPolicyConfig(enabled=False),
            cmd=cmd,
            dry_run=True,
        )
        _, selector3 = router3.get_executor_for_stage("spec")
        assert selector3.model == "engine-model"


class TestExecResultErrorDetection:
    """Test ExecResult error detection methods."""

    def test_is_quota_error(self, tmp_path: Path) -> None:
        """Detect quota errors in stderr."""
        logs = LogPaths(
            stdout=tmp_path / "stdout.log",
            stderr=tmp_path / "stderr.log",
        )
        logs.stdout.parent.mkdir(parents=True, exist_ok=True)
        logs.stdout.write_text("")
        logs.stderr.write_text("Error: Rate limit exceeded. Please try again.")

        result = ExecResult(
            returncode=1,
            stdout_path=logs.stdout,
            stderr_path=logs.stderr,
            success=False,
        )

        assert result.is_quota_error() is True
        assert result.is_model_unavailable_error() is False

    def test_is_model_unavailable_error(self, tmp_path: Path) -> None:
        """Detect model unavailable errors."""
        logs = LogPaths(
            stdout=tmp_path / "stdout.log",
            stderr=tmp_path / "stderr.log",
        )
        logs.stdout.parent.mkdir(parents=True, exist_ok=True)
        logs.stdout.write_text("")
        logs.stderr.write_text("Error: Model not found: gpt-5.5")

        result = ExecResult(
            returncode=1,
            stdout_path=logs.stdout,
            stderr_path=logs.stderr,
            success=False,
            error_message="Model not found",
        )

        assert result.is_quota_error() is False
        assert result.is_model_unavailable_error() is True

    def test_no_error_on_success(self, tmp_path: Path) -> None:
        """No error detection on successful result."""
        logs = LogPaths(
            stdout=tmp_path / "stdout.log",
            stderr=tmp_path / "stderr.log",
        )
        logs.stdout.parent.mkdir(parents=True, exist_ok=True)
        logs.stdout.write_text("Success")
        logs.stderr.write_text("")

        result = ExecResult(
            returncode=0,
            stdout_path=logs.stdout,
            stderr_path=logs.stderr,
            success=True,
        )

        assert result.is_quota_error() is False
        assert result.is_model_unavailable_error() is False
