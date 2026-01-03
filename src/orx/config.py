"""Configuration schema for orx orchestrator."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class EngineType(str, Enum):
    """Supported executor engine types."""

    CODEX = "codex"
    GEMINI = "gemini"
    FAKE = "fake"


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

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if not self.binary:
            # Set default binary based on engine type
            defaults = {
                EngineType.CODEX: "codex",
                EngineType.GEMINI: "gemini",
                EngineType.FAKE: "",
            }
            object.__setattr__(self, "binary", defaults.get(self.type, ""))


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
    """

    max_fix_attempts: int = Field(default=3, ge=1, le=10)
    parallel_items: bool = False
    stop_on_first_failure: bool = False


class OrxConfig(BaseModel):
    """Complete orx configuration.

    Attributes:
        version: Config schema version.
        engine: Primary engine configuration.
        fallback_engine: Optional fallback engine.
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
    fallback_engine: EngineConfig | None = None
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

    def to_yaml(self) -> str:
        """Serialize the config to YAML.

        Returns:
            YAML string representation.
        """
        data = self.model_dump(mode="json")
        return yaml.dump(data, default_flow_style=False, sort_keys=False)

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

        return cls.model_validate(data)

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

        Args:
            engine_type: The primary engine type to use.

        Returns:
            A default OrxConfig instance.
        """
        return cls(engine=EngineConfig(type=engine_type))
