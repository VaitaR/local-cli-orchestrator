"""Configuration schema for orx orchestrator."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class EngineType(str, Enum):
    """Supported executor engine types."""

    CODEX = "codex"
    GEMINI = "gemini"
    COPILOT = "copilot"
    CLAUDE_CODE = "claude_code"
    CURSOR = "cursor"
    FAKE = "fake"


class StageName(str, Enum):
    """Stage names for model routing."""

    PLAN = "plan"
    SPEC = "spec"
    DECOMPOSE = "decompose"
    IMPLEMENT = "implement"
    FIX = "fix"
    REVIEW = "review"
    KNOWLEDGE_UPDATE = "knowledge_update"


class ModelSelector(BaseModel):
    """Model selection configuration for a stage.

    Attributes:
        model: Model name to use (e.g., "gpt-5-codex", "gemini-2.5-pro").
        profile: Codex profile name (alternative to model).
        reasoning_effort: Codex reasoning effort level (low/medium/high).
        thinking_budget: Gemini thinking budget in tokens (0 to disable).
        web_search: Enable Codex web search tool for this stage.
    """

    model: str | None = None
    profile: str | None = None
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    thinking_budget: int | None = None
    web_search: bool = False

    @model_validator(mode="after")
    def validate_model_or_profile(self) -> ModelSelector:
        """Validate that model and profile are not both set."""
        if self.model and self.profile:
            msg = "Cannot specify both 'model' and 'profile'"
            raise ValueError(msg)
        return self


class ExecutorDefaults(BaseModel):
    """Default settings for an executor.

    Attributes:
        model: Default model name.
        reasoning_effort: Default reasoning effort for Codex.
        output_format: Output format (e.g., "json" for Gemini).
    """

    model: str | None = None
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    output_format: str | None = None


class ExecutorConfig(BaseModel):
    """Configuration for an executor type.

    Attributes:
        bin: Path or name of the CLI binary.
        default: Default settings for this executor.
        profiles: Named profiles (for Codex) keyed by stage name.
        available_models: List of model names available for this executor.
        stage_models: Default model name for each stage.
        use_yolo: For Gemini: enable YOLO mode (auto-approve all tool calls).
        approval_mode: For Gemini: approval mode (e.g., "auto_edit", "reject_all").
    """

    bin: str | None = None
    default: ExecutorDefaults = Field(default_factory=ExecutorDefaults)
    profiles: dict[str, str] = Field(default_factory=dict)
    available_models: list[str] = Field(default_factory=list)
    stage_models: dict[str, str] = Field(default_factory=dict)
    use_yolo: bool = Field(default=True, description="Enable YOLO mode for Gemini")
    approval_mode: str = Field(
        default="auto_edit", description="Approval mode for Gemini"
    )


class StageExecutorConfig(BaseModel):
    """Configuration for a specific stage's executor.

    Attributes:
        executor: Which executor to use ("codex", "gemini").
        model: Model override for this stage.
        profile: Profile override (for Codex).
        reasoning_effort: Reasoning effort override (for Codex).
        thinking_budget: Thinking budget override for Gemini (tokens).
        web_search: Enable Codex web search tool for this stage.
    """

    executor: EngineType | None = None
    model: str | None = None
    profile: str | None = None
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    thinking_budget: int | None = None
    web_search: bool = False

    @model_validator(mode="after")
    def validate_model_or_profile(self) -> StageExecutorConfig:
        """Validate that model and profile are not both set."""
        if self.model and self.profile:
            msg = "Cannot specify both 'model' and 'profile' for a stage"
            raise ValueError(msg)
        return self

    def to_model_selector(self) -> ModelSelector:
        """Convert to a ModelSelector."""
        return ModelSelector(
            model=self.model,
            profile=self.profile,
            reasoning_effort=self.reasoning_effort,
            thinking_budget=self.thinking_budget,
            web_search=self.web_search,
        )


class FallbackMatchConfig(BaseModel):
    """Configuration for fallback matching.

    Attributes:
        executor: Match fallback for this executor type.
        error_contains: Match if error contains any of these strings.
    """

    executor: EngineType | None = None
    error_contains: list[str] = Field(default_factory=list)


class FallbackSwitchConfig(BaseModel):
    """Configuration for fallback switch action.

    Attributes:
        model: Switch to this model.
        profile: Switch to this profile (for Codex).
    """

    model: str | None = None
    profile: str | None = None


class FallbackRule(BaseModel):
    """A single fallback rule.

    Attributes:
        match: Conditions to match.
        switch_to: Action to take on match.
        max_retries: Maximum retries with this fallback (default: 1).
    """

    match: FallbackMatchConfig
    switch_to: FallbackSwitchConfig
    max_retries: int = Field(default=1, ge=1, le=5)


class FallbackPolicyConfig(BaseModel):
    """Configuration for fallback policies.

    Attributes:
        enabled: Whether fallback is enabled.
        rules: List of fallback rules to apply.
    """

    enabled: bool = True
    rules: list[FallbackRule] = Field(default_factory=list)


class ExecutorsConfig(BaseModel):
    """Configuration for all executors.

    Attributes:
        codex: Codex executor configuration.
        gemini: Gemini executor configuration.
        copilot: GitHub Copilot CLI executor configuration.
        claude_code: Claude Code CLI executor configuration.
        cursor: Cursor CLI executor configuration.
    """

    codex: ExecutorConfig = Field(default_factory=ExecutorConfig)
    gemini: ExecutorConfig = Field(default_factory=ExecutorConfig)
    copilot: ExecutorConfig = Field(default_factory=ExecutorConfig)
    claude_code: ExecutorConfig = Field(default_factory=ExecutorConfig)
    cursor: ExecutorConfig = Field(default_factory=ExecutorConfig)


class StagesConfig(BaseModel):
    """Configuration for per-stage executor settings.

    Attributes:
        plan: Configuration for plan stage.
        spec: Configuration for spec stage.
        decompose: Configuration for decompose stage.
        implement: Configuration for implement stage.
        fix: Configuration for fix stage.
        review: Configuration for review stage.
        knowledge_update: Configuration for knowledge update stage.
    """

    plan: StageExecutorConfig = Field(default_factory=StageExecutorConfig)
    spec: StageExecutorConfig = Field(default_factory=StageExecutorConfig)
    decompose: StageExecutorConfig = Field(default_factory=StageExecutorConfig)
    implement: StageExecutorConfig = Field(default_factory=StageExecutorConfig)
    fix: StageExecutorConfig = Field(default_factory=StageExecutorConfig)
    review: StageExecutorConfig = Field(default_factory=StageExecutorConfig)
    knowledge_update: StageExecutorConfig = Field(default_factory=StageExecutorConfig)

    def get_stage_config(self, stage: str) -> StageExecutorConfig:
        """Get configuration for a specific stage.

        Args:
            stage: Stage name.

        Returns:
            StageExecutorConfig for the stage.
        """
        stage_map = {
            "plan": self.plan,
            "spec": self.spec,
            "decompose": self.decompose,
            "implement": self.implement,
            "fix": self.fix,
            "review": self.review,
            "knowledge_update": self.knowledge_update,
        }
        return stage_map.get(stage, StageExecutorConfig())


class EngineConfig(BaseModel):
    """Configuration for a specific engine.

    Attributes:
        type: The engine type.
        enabled: Whether the engine is enabled.
        binary: Path or name of the CLI binary.
        extra_args: Additional arguments to pass to the CLI.
        timeout: Default timeout in seconds for engine operations.
        stage_timeouts: Stage-specific timeouts (overrides default timeout).
                        Example: {"implement": 1800, "review": 300}
        model: Default model for this engine.
        profile: Default profile for this engine (Codex only).
        reasoning_effort: Default reasoning effort (Codex only).
        output_format: Default output format (Gemini only).
    """

    type: EngineType
    enabled: bool = True
    binary: str = ""
    extra_args: list[str] = Field(default_factory=list)
    timeout: int = Field(default=600, ge=30)
    stage_timeouts: dict[str, int] = Field(
        default_factory=dict,
        description="Stage-specific timeouts in seconds",
    )
    model: str | None = None
    profile: str | None = None
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    output_format: str | None = None

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if not self.binary:
            # Set default binary based on engine type
            defaults = {
                EngineType.CODEX: "codex",
                EngineType.GEMINI: "gemini",
                EngineType.COPILOT: "copilot",
                EngineType.CLAUDE_CODE: "claude",
                EngineType.CURSOR: "cursor",
                EngineType.FAKE: "",
            }
            object.__setattr__(self, "binary", defaults.get(self.type, ""))

    def to_model_selector(self) -> ModelSelector:
        """Convert engine config to a ModelSelector."""
        return ModelSelector(
            model=self.model,
            profile=self.profile,
            reasoning_effort=self.reasoning_effort,
        )

    def __hash__(self) -> int:
        """Make EngineConfig hashable for use in sets/dicts.

        Converts unhashable types (lists, dicts) to tuples.
        """
        return hash(
            (
                self.type,
                self.binary,
                self.model,
                self.profile,
                self.reasoning_effort,
                self.output_format,
                self.timeout,
                self.enabled,
                tuple(self.extra_args),
                tuple(sorted(self.stage_timeouts.items())),
            )
        )


class GateConfig(BaseModel):
    """Configuration for a quality gate.

    Attributes:
        name: Name of the gate.
        enabled: Whether the gate is enabled.
        command: Command to run (if custom).
        args: Arguments for the command.
        required: Whether failure blocks the run.
    """

    name: str
    enabled: bool = True
    command: str = ""
    args: list[str] = Field(default_factory=list)
    required: bool = True


class GitConfig(BaseModel):
    """Git-related configuration.

    Attributes:
        base_branch: The base branch to create worktrees from.
        remote: The remote name for pushing.
        auto_commit: Whether to auto-commit changes.
        auto_push: Whether to auto-push changes.
        create_pr: Whether to create a PR.
        pr_draft: Whether to create PR as draft.
    """

    base_branch: str = "main"
    remote: str = "origin"
    auto_commit: bool = True
    auto_push: bool = False
    create_pr: bool = False
    pr_draft: bool = True


class GuardrailConfig(BaseModel):
    """Configuration for guardrails.

    Attributes:
        enabled: Whether guardrails are enabled.
        mode: Guardrail mode - "blacklist" (default) or "allowlist".
              In allowlist mode, only files matching allowed_patterns can be modified.
        allowed_patterns: File patterns that are allowed to be modified (allowlist mode only).
        forbidden_patterns: File patterns that must not be modified (blacklist mode).
        forbidden_paths: Exact paths that must not be modified (blacklist mode).
        forbidden_new_files: Patterns for files that must not be created
                             (e.g., artifacts in worktree root).
        max_files_changed: Maximum number of files that can be changed.
    """

    enabled: bool = True
    mode: Literal["blacklist", "allowlist"] = "blacklist"
    allowed_patterns: list[str] = Field(
        default_factory=list,
        description="Patterns for files allowed in allowlist mode (e.g., ['src/**/*.py', 'tests/**'])",
    )
    forbidden_patterns: list[str] = Field(
        default_factory=lambda: [
            "*.env",
            "*.env.*",
            "*secrets*",
            "*.pem",
            "*.key",
            ".git/*",
        ]
    )
    forbidden_paths: list[str] = Field(
        default_factory=lambda: [
            ".env",
            ".env.local",
            ".env.production",
            "secrets.yaml",
            "secrets.json",
        ]
    )
    forbidden_new_files: list[str] = Field(
        default_factory=lambda: [
            "pr_body.md",
            "review.md",
            "*.orx.md",
        ]
    )
    max_files_changed: int = Field(default=50, ge=1)


class KnowledgeMarkersConfig(BaseModel):
    """Markers for scoped updates in knowledge files."""

    agents_start: str = "<!-- ORX:START AGENTS -->"
    agents_end: str = "<!-- ORX:END AGENTS -->"
    arch_start: str = "<!-- ORX:START ARCH -->"
    arch_end: str = "<!-- ORX:END ARCH -->"


class KnowledgeLimitsConfig(BaseModel):
    """Limits for knowledge file changes."""

    max_total_changed_lines: int = Field(default=300, ge=10)
    max_changed_lines_per_file: int = Field(default=200, ge=10)
    max_deleted_lines: int = Field(default=50, ge=0)


class KnowledgeConfig(BaseModel):
    """Configuration for self-improvement / knowledge update stage.

    This stage automatically updates AGENTS.md and ARCHITECTURE.md
    after successful task completion.

    Attributes:
        enabled: Whether knowledge updates are enabled.
        mode: Update mode - "off", "suggest" (propose only), or "auto" (apply).
        trigger: When to run - "per_item" or "per_run".
        branch_mode: Git strategy - "separate" (knowledge/<run_id>) or "in_code_pr".
        allowlist: Files that can be modified by knowledge updates.
        markers: Start/end markers for scoped updates.
        limits: Limits on change size.
        architecture_gatekeeping: Whether to apply strict gatekeeping for ARCHITECTURE.md.
    """

    enabled: bool = True
    mode: Literal["off", "suggest", "auto"] = "auto"
    trigger: Literal["per_item", "per_run"] = "per_run"
    branch_mode: Literal["separate", "in_code_pr"] = "separate"
    allowlist: list[str] = Field(
        default_factory=lambda: [
            "AGENTS.md",
            "ARCHITECTURE.md",
        ]
    )
    markers: KnowledgeMarkersConfig = Field(default_factory=KnowledgeMarkersConfig)
    limits: KnowledgeLimitsConfig = Field(default_factory=KnowledgeLimitsConfig)
    architecture_gatekeeping: bool = True


class RunConfig(BaseModel):
    """Configuration for run behavior.

    Attributes:
        max_fix_attempts: Maximum fix-loop iterations per work item.
        parallel_items: Whether to run independent items in parallel.
        stop_on_first_failure: Whether to stop on first work item failure.
        per_item_verify: Verification mode for each work item (full or fast).
        fast_verify_max_pytest_targets: Max targeted pytest paths for fast verify.
        fast_verify_skip_pytest_if_no_targets: Skip pytest when no targets are found.
        auto_fix_ruff: Whether to auto-apply ruff fixes on gate failures.
        max_backlog_items: Target maximum number of backlog items.
        coalesce_backlog_items: Whether to merge excess backlog items.
    """

    max_fix_attempts: int = Field(default=3, ge=1, le=10)
    parallel_items: bool = False
    stop_on_first_failure: bool = False
    per_item_verify: Literal["full", "fast"] = "fast"
    fast_verify_max_pytest_targets: int = Field(default=6, ge=1, le=50)
    fast_verify_skip_pytest_if_no_targets: bool = True
    auto_fix_ruff: bool = True
    max_backlog_items: int = Field(default=4, ge=1, le=50)
    coalesce_backlog_items: bool = True


class OrxConfig(BaseModel):
    """Complete orx configuration.

    Attributes:
        version: Config schema version.
        engine: Primary engine configuration.
        stage_engines: Optional per-stage engine overrides (legacy).
        fallback_engine: Optional fallback engine.
        executors: Configuration for executor types (codex, gemini).
        stages: Per-stage executor and model configuration.
        fallback: Fallback policy configuration.
        gates: List of gate configurations.
        git: Git configuration.
        guardrails: Guardrail configuration.
        run: Run behavior configuration.

    Example:
        >>> config = OrxConfig(
        ...     engine=EngineConfig(type=EngineType.CODEX),
        ... )
        >>> config.engine.type
        <EngineType.CODEX: 'codex'>
    """

    version: str = "1.0"
    engine: EngineConfig
    stage_engines: dict[str, EngineConfig] = Field(
        default_factory=dict,
        description="Per-stage engine overrides (keyed by stage name)",
    )
    fallback_engine: EngineConfig | None = None
    executors: ExecutorsConfig = Field(default_factory=ExecutorsConfig)
    stages: StagesConfig = Field(default_factory=StagesConfig)
    fallback: FallbackPolicyConfig = Field(default_factory=FallbackPolicyConfig)
    gates: list[GateConfig] = Field(
        default_factory=lambda: [
            GateConfig(name="ruff", command="ruff", args=["check", "."]),
            GateConfig(name="pytest", command="pytest", args=["-q"]),
        ]
    )
    git: GitConfig = Field(default_factory=GitConfig)
    guardrails: GuardrailConfig = Field(default_factory=GuardrailConfig)
    run: RunConfig = Field(default_factory=RunConfig)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)

    @field_validator("gates")
    @classmethod
    def validate_unique_gate_names(cls, v: list[GateConfig]) -> list[GateConfig]:
        """Ensure gate names are unique."""
        names = [g.name for g in v]
        if len(names) != len(set(names)):
            msg = "Gate names must be unique"
            raise ValueError(msg)
        return v

    def get_enabled_gates(self) -> list[GateConfig]:
        """Get list of enabled gates."""
        return [g for g in self.gates if g.enabled]

    def apply_overrides(
        self,
        *,
        engine: EngineType | None = None,
        model: str | None = None,
        reasoning_effort: Literal["low", "medium", "high"] | None = None,
        thinking_budget: int | None = None,
        base_branch: str | None = None,
        stages: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Apply common CLI/dashboard overrides to the config.

        Args:
            engine: Engine type override.
            model: Model override for the selected engine.
            reasoning_effort: Reasoning effort override (for Codex).
            thinking_budget: Thinking budget override in tokens (for Gemini).
            base_branch: Base branch override.
            stages: Per-stage overrides dict, e.g. {"plan": {"executor": "gemini"}}.

        Notes:
            - `engine` is treated as a global override: it clears per-stage executor
              overrides (including legacy `stage_engines`) so the selected engine is
              consistently used across stages.
            - `model` is treated as a global model override for the selected engine:
              it updates `executors.<engine>.default.model` and
              `executors.<engine>.stage_models[*]` so ModelRouter resolves it above
              executor defaults and `engine.model`.
            - `reasoning_effort` sets Codex reasoning effort globally.
            - `thinking_budget` sets Gemini thinking budget globally.
        """
        if engine is not None:
            self.engine.type = engine

            # Ensure global engine selection actually takes effect.
            self.stage_engines.clear()
            for stage in StageName:
                stage_cfg = self.stages.get_stage_config(stage.value)
                stage_cfg.executor = None
                stage_cfg.model = None
                stage_cfg.profile = None

        if model is not None:
            self.engine.model = model

            if self.engine.type == EngineType.CODEX:
                exec_cfg = self.executors.codex
            elif self.engine.type == EngineType.GEMINI:
                exec_cfg = self.executors.gemini
            else:
                exec_cfg = None

            if exec_cfg is not None:
                exec_cfg.default.model = model
                for stage in StageName:
                    exec_cfg.stage_models[stage.value] = model

        if reasoning_effort is not None:
            self.engine.reasoning_effort = reasoning_effort
            self.executors.codex.default.reasoning_effort = reasoning_effort
            # Apply to all stages so ModelRouter picks it up
            for stage in StageName:
                stage_cfg = self.stages.get_stage_config(stage.value)
                stage_cfg.reasoning_effort = reasoning_effort

        if thinking_budget is not None:
            # Apply thinking_budget to all stages for ModelRouter
            for stage in StageName:
                stage_cfg = self.stages.get_stage_config(stage.value)
                stage_cfg.thinking_budget = thinking_budget

        if base_branch is not None:
            self.git.base_branch = base_branch

        # Per-stage overrides from dashboard/CLI
        if stages:
            for stage_name, overrides in stages.items():
                stage_cfg = self.stages.get_stage_config(stage_name)
                if "executor" in overrides:
                    stage_cfg.executor = EngineType(overrides["executor"])
                if "model" in overrides:
                    stage_cfg.model = overrides["model"]
                if "reasoning_effort" in overrides:
                    stage_cfg.reasoning_effort = overrides["reasoning_effort"]
                if "thinking_budget" in overrides:
                    stage_cfg.thinking_budget = overrides["thinking_budget"]

    def to_yaml(self) -> str:
        """Serialize the config to YAML.

        Returns:
            YAML string representation.
        """
        data = self.model_dump(mode="json")
        return yaml.dump(data, default_flow_style=False, sort_keys=False)

    def _apply_executor_model_defaults(self) -> None:
        """Backfill executor model config for backward compatibility.

        Older `orx.yaml` files may omit `available_models` and/or `stage_models`.
        For the dashboard and ModelRouter to behave predictably, we merge in
        sensible defaults without overwriting explicitly provided values.
        """

        default_cfg = OrxConfig.default(engine_type=self.engine.type)

        def merge_executor(name: str) -> None:
            exec_cfg: ExecutorConfig = getattr(self.executors, name)
            default_exec: ExecutorConfig = getattr(default_cfg.executors, name)
            fields_set = getattr(exec_cfg, "model_fields_set", set())

            if "available_models" not in fields_set:
                exec_cfg.available_models = list(default_exec.available_models)

            if "stage_models" not in fields_set:
                exec_cfg.stage_models = dict(default_exec.stage_models)
            else:
                fallback_model = (
                    exec_cfg.default.model
                    or default_exec.default.model
                    or self.engine.model
                    or ""
                )
                for stage in StageName:
                    exec_cfg.stage_models.setdefault(stage.value, fallback_model)

        merge_executor("codex")
        merge_executor("gemini")

    def save(self, path: Path) -> None:
        """Save the config to a YAML file.

        Args:
            path: Path to save the file.
        """
        path.write_text(self.to_yaml())

    @classmethod
    def from_yaml(cls, yaml_content: str) -> OrxConfig:
        """Parse config from YAML content.

        Args:
            yaml_content: YAML string to parse.

        Returns:
            Parsed OrxConfig instance.

        Raises:
            ValueError: If the YAML is invalid.
        """
        try:
            data: dict[str, Any] = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            msg = f"Invalid YAML: {e}"
            raise ValueError(msg) from e

        if not isinstance(data, dict):
            msg = "Config YAML must be a mapping"
            raise ValueError(msg)

        cfg = cls.model_validate(data)
        cfg._apply_executor_model_defaults()
        return cfg

    @classmethod
    def load(cls, path: Path) -> OrxConfig:
        """Load config from a YAML file.

        Args:
            path: Path to the YAML file.

        Returns:
            Parsed OrxConfig instance.

        Raises:
            FileNotFoundError: If the file doesn't exist.
            ValueError: If the YAML is invalid.
        """
        if not path.exists():
            msg = f"Config file not found: {path}"
            raise FileNotFoundError(msg)
        return cls.from_yaml(path.read_text())

    @classmethod
    def default(cls, engine_type: EngineType = EngineType.CODEX) -> OrxConfig:
        """Create a default configuration.

        Uses dynamic model discovery when available, falls back to static definitions.

        Args:
            engine_type: The primary engine type to use.

        Returns:
            A default OrxConfig instance.
        """
        from orx.executors.models import get_default_model, get_model_ids

        config = cls(engine=EngineConfig(type=engine_type))

        standard_stages = [
            StageName.PLAN.value,
            StageName.SPEC.value,
            StageName.DECOMPOSE.value,
            StageName.IMPLEMENT.value,
            StageName.FIX.value,
            StageName.REVIEW.value,
            StageName.KNOWLEDGE_UPDATE.value,
        ]

        # Gemini defaults from dynamic discovery
        gemini_default = get_default_model("gemini")
        gemini_models = get_model_ids("gemini", include_preview=True)
        config.executors.gemini.available_models = gemini_models
        config.executors.gemini.default.model = gemini_default
        config.executors.gemini.default.output_format = "json"
        config.executors.gemini.stage_models = dict.fromkeys(
            standard_stages, gemini_default
        )

        # Codex defaults from dynamic discovery
        codex_default = get_default_model("codex")
        codex_models = get_model_ids("codex", include_preview=True)
        config.executors.codex.available_models = codex_models
        config.executors.codex.default.model = codex_default
        config.executors.codex.default.reasoning_effort = "medium"
        config.executors.codex.stage_models = dict.fromkeys(
            standard_stages, codex_default
        )

        return config
