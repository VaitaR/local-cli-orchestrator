"""Model definitions and dynamic discovery for CLI executors.

This module provides:
1. Static model definitions with capabilities (fallback when discovery fails)
2. Dynamic model discovery via CLI commands
3. Model capability metadata (reasoning levels, thinking budgets, etc.)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any

import structlog

logger = structlog.get_logger()


class ReasoningLevel(str, Enum):
    """Reasoning effort/thinking level for models."""

    OFF = "off"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class ModelCapabilities:
    """Capabilities and configuration options for a model.

    Attributes:
        supports_reasoning: Whether model supports reasoning effort levels.
        reasoning_levels: Available reasoning levels (if supported).
        default_reasoning: Default reasoning level.
        supports_thinking_budget: Whether model supports thinking token budget.
        max_thinking_budget: Maximum thinking budget (tokens).
        default_thinking_budget: Default thinking budget.
        supports_web_search: Whether model supports web search tool.
        context_window: Context window size in tokens.
        is_preview: Whether this is a preview/experimental model.
        tier: Model tier for fallback ordering (1=best, 3=fallback).
    """

    supports_reasoning: bool = False
    reasoning_levels: list[ReasoningLevel] = field(default_factory=list)
    default_reasoning: ReasoningLevel = ReasoningLevel.MEDIUM
    supports_thinking_budget: bool = False
    max_thinking_budget: int = 0
    default_thinking_budget: int = 0
    supports_web_search: bool = False
    context_window: int = 128000
    is_preview: bool = False
    tier: int = 2


@dataclass
class ModelInfo:
    """Complete information about a model.

    Attributes:
        id: Model identifier (e.g., "gpt-5-codex", "gemini-2.5-pro").
        name: Display name.
        engine: Engine type ("codex" or "gemini").
        capabilities: Model capabilities.
        description: Optional description.
        aliases: Alternative names for this model.
    """

    id: str
    name: str
    engine: str
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    description: str = ""
    aliases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization (API-friendly)."""
        return {
            "id": self.id,
            "name": self.name,
            "engine": self.engine,
            "description": self.description,
            "aliases": self.aliases,
            # Flatten capabilities for easier frontend access
            "supports_reasoning": self.capabilities.supports_reasoning,
            "reasoning_levels": [r.value for r in self.capabilities.reasoning_levels],
            "default_reasoning": self.capabilities.default_reasoning.value,
            "supports_thinking_budget": self.capabilities.supports_thinking_budget,
            "max_thinking_budget": self.capabilities.max_thinking_budget,
            "default_thinking_budget": self.capabilities.default_thinking_budget,
            "supports_web_search": self.capabilities.supports_web_search,
            "context_window": self.capabilities.context_window,
            "is_preview": self.capabilities.is_preview,
            "tier": self.capabilities.tier,
        }


# ============================================================================
# Static Model Definitions (fallback when discovery fails)
# ============================================================================

CODEX_MODELS: dict[str, ModelInfo] = {
    "gpt-5.2-codex": ModelInfo(
        id="gpt-5.2-codex",
        name="GPT-5.2 Codex",
        engine="codex",
        description="Most advanced agentic coding model, optimized for complex code changes and refactors",
        capabilities=ModelCapabilities(
            supports_reasoning=True,
            reasoning_levels=[ReasoningLevel.LOW, ReasoningLevel.MEDIUM, ReasoningLevel.HIGH],
            default_reasoning=ReasoningLevel.MEDIUM,
            supports_web_search=True,
            context_window=200000,
            tier=1,
        ),
    ),
    "gpt-5.2": ModelInfo(
        id="gpt-5.2",
        name="GPT-5.2",
        engine="codex",
        description="Full GPT-5.2 model",
        capabilities=ModelCapabilities(
            supports_reasoning=True,
            reasoning_levels=[ReasoningLevel.LOW, ReasoningLevel.MEDIUM, ReasoningLevel.HIGH],
            default_reasoning=ReasoningLevel.MEDIUM,
            supports_web_search=True,
            context_window=200000,
            tier=1,
        ),
    ),
    "gpt-5-codex": ModelInfo(
        id="gpt-5-codex",
        name="GPT-5 Codex (Legacy)",
        engine="codex",
        description="Previous generation Codex model",
        capabilities=ModelCapabilities(
            supports_reasoning=True,
            reasoning_levels=[ReasoningLevel.LOW, ReasoningLevel.MEDIUM, ReasoningLevel.HIGH],
            default_reasoning=ReasoningLevel.MEDIUM,
            supports_web_search=True,
            context_window=200000,
            tier=2,
        ),
    ),
    "gpt-5": ModelInfo(
        id="gpt-5",
        name="GPT-5 (Legacy)",
        engine="codex",
        description="Previous generation full GPT-5 model",
        capabilities=ModelCapabilities(
            supports_reasoning=True,
            reasoning_levels=[ReasoningLevel.LOW, ReasoningLevel.MEDIUM, ReasoningLevel.HIGH],
            default_reasoning=ReasoningLevel.MEDIUM,
            supports_web_search=True,
            context_window=200000,
            tier=2,
        ),
    ),
}

GEMINI_MODELS: dict[str, ModelInfo] = {
    "gemini-2.5-pro": ModelInfo(
        id="gemini-2.5-pro",
        name="Gemini 2.5 Pro",
        engine="gemini",
        description="Most capable Gemini model",
        capabilities=ModelCapabilities(
            supports_reasoning=False,
            supports_thinking_budget=True,
            max_thinking_budget=32768,
            default_thinking_budget=8192,
            context_window=1000000,
            tier=1,
        ),
    ),
    "gemini-2.5-flash": ModelInfo(
        id="gemini-2.5-flash",
        name="Gemini 2.5 Flash",
        engine="gemini",
        description="Fast and efficient Gemini model",
        capabilities=ModelCapabilities(
            supports_reasoning=False,
            supports_thinking_budget=True,
            max_thinking_budget=16384,
            default_thinking_budget=8192,
            context_window=1000000,
            tier=2,
        ),
    ),
    "gemini-2.5-flash-lite": ModelInfo(
        id="gemini-2.5-flash-lite",
        name="Gemini 2.5 Flash Lite",
        engine="gemini",
        description="Lightweight Gemini for simple tasks",
        capabilities=ModelCapabilities(
            supports_reasoning=False,
            supports_thinking_budget=True,
            max_thinking_budget=8192,
            default_thinking_budget=512,
            context_window=1000000,
            tier=3,
        ),
    ),
    "gemini-3-pro-preview": ModelInfo(
        id="gemini-3-pro-preview",
        name="Gemini 3 Pro (Preview)",
        engine="gemini",
        description="Next-gen Gemini Pro - preview",
        capabilities=ModelCapabilities(
            supports_reasoning=False,
            supports_thinking_budget=True,
            max_thinking_budget=32768,
            default_thinking_budget=8192,
            context_window=1000000,
            is_preview=True,
            tier=1,
        ),
    ),
    "gemini-3-flash-preview": ModelInfo(
        id="gemini-3-flash-preview",
        name="Gemini 3 Flash (Preview)",
        engine="gemini",
        description="Next-gen Gemini Flash - preview",
        capabilities=ModelCapabilities(
            supports_reasoning=False,
            supports_thinking_budget=True,
            max_thinking_budget=16384,
            default_thinking_budget=8192,
            context_window=1000000,
            is_preview=True,
            tier=2,
        ),
    ),
    "gemini-2.0-flash": ModelInfo(
        id="gemini-2.0-flash",
        name="Gemini 2.0 Flash",
        engine="gemini",
        description="Previous generation Flash model",
        aliases=["gemini-2.0-flash-exp"],
        capabilities=ModelCapabilities(
            context_window=1000000,
            tier=3,
        ),
    ),
    "gemini-1.5-pro": ModelInfo(
        id="gemini-1.5-pro",
        name="Gemini 1.5 Pro",
        engine="gemini",
        description="Stable 1.5 Pro model",
        capabilities=ModelCapabilities(
            context_window=2000000,
            tier=2,
        ),
    ),
    "gemini-1.5-flash": ModelInfo(
        id="gemini-1.5-flash",
        name="Gemini 1.5 Flash",
        engine="gemini",
        description="Stable 1.5 Flash model",
        capabilities=ModelCapabilities(
            context_window=1000000,
            tier=3,
        ),
    ),
}

COPILOT_MODELS: dict[str, ModelInfo] = {
    "claude-sonnet-4.5": ModelInfo(
        id="claude-sonnet-4.5",
        name="Claude Sonnet 4.5",
        engine="copilot",
        description="Most capable Claude model via Copilot",
        capabilities=ModelCapabilities(
            supports_reasoning=False,
            supports_thinking_budget=True,
            max_thinking_budget=32768,
            default_thinking_budget=8192,
            context_window=200000,
            tier=1,
        ),
    ),
    "claude-sonnet-4": ModelInfo(
        id="claude-sonnet-4",
        name="Claude Sonnet 4",
        engine="copilot",
        description="Previous generation Claude Sonnet",
        capabilities=ModelCapabilities(
            supports_reasoning=False,
            context_window=200000,
            tier=2,
        ),
    ),
    "claude-haiku-4.5": ModelInfo(
        id="claude-haiku-4.5",
        name="Claude Haiku 4.5",
        engine="copilot",
        description="Fast and efficient Claude model",
        capabilities=ModelCapabilities(
            supports_reasoning=False,
            context_window=200000,
            tier=2,
        ),
    ),
    "gpt-5": ModelInfo(
        id="gpt-5",
        name="GPT-5",
        engine="copilot",
        description="OpenAI GPT-5 via Copilot",
        capabilities=ModelCapabilities(
            supports_reasoning=True,
            reasoning_levels=[ReasoningLevel.LOW, ReasoningLevel.MEDIUM, ReasoningLevel.HIGH],
            default_reasoning=ReasoningLevel.MEDIUM,
            context_window=200000,
            tier=1,
        ),
    ),
}


# Claude Code CLI models (claude)
# Supports aliases (sonnet, opus, haiku) or full model names
CLAUDE_CODE_MODELS: dict[str, ModelInfo] = {
    "sonnet": ModelInfo(
        id="sonnet",
        name="Claude Sonnet 4.5",
        engine="claude_code",
        description="Latest Sonnet - balanced performance (default)",
        aliases=["claude-sonnet-4-5-20250929"],
        capabilities=ModelCapabilities(
            supports_thinking_budget=True,
            max_thinking_budget=32768,
            default_thinking_budget=8192,
            context_window=200000,
            tier=1,
        ),
    ),
    "opus": ModelInfo(
        id="opus",
        name="Claude Opus 4",
        engine="claude_code",
        description="Most capable Claude model",
        aliases=["claude-opus-4-20250514"],
        capabilities=ModelCapabilities(
            supports_thinking_budget=True,
            max_thinking_budget=65536,
            default_thinking_budget=16384,
            context_window=200000,
            tier=1,
        ),
    ),
    "haiku": ModelInfo(
        id="haiku",
        name="Claude Haiku 4.5",
        engine="claude_code",
        description="Fast and cost-effective",
        aliases=["claude-haiku-4-5-20250929"],
        capabilities=ModelCapabilities(
            context_window=200000,
            tier=2,
        ),
    ),
}


# Cursor CLI models (agent)
# Cursor provides access to multiple model providers
CURSOR_MODELS: dict[str, ModelInfo] = {
    "auto": ModelInfo(
        id="auto",
        name="Auto (Cursor Selects)",
        engine="cursor",
        description="Cursor auto-selects the best model for the task",
        capabilities=ModelCapabilities(
            supports_reasoning=True,
            context_window=200000,
            tier=1,
        ),
    ),
    "sonnet-4.5": ModelInfo(
        id="sonnet-4.5",
        name="Claude Sonnet 4.5",
        engine="cursor",
        description="Claude Sonnet 4.5 via Cursor",
        aliases=["claude-sonnet-4.5"],
        capabilities=ModelCapabilities(
            supports_thinking_budget=True,
            max_thinking_budget=32768,
            default_thinking_budget=8192,
            context_window=200000,
            tier=1,
        ),
    ),
    "opus-4.5": ModelInfo(
        id="opus-4.5",
        name="Claude Opus 4.5",
        engine="cursor",
        description="Claude Opus 4.5 via Cursor - most capable",
        aliases=["claude-opus-4.5"],
        capabilities=ModelCapabilities(
            supports_thinking_budget=True,
            max_thinking_budget=65536,
            default_thinking_budget=16384,
            context_window=200000,
            tier=1,
        ),
    ),
    "gpt-5.2": ModelInfo(
        id="gpt-5.2",
        name="GPT-5.2",
        engine="cursor",
        description="OpenAI GPT-5.2 via Cursor",
        capabilities=ModelCapabilities(
            supports_reasoning=True,
            reasoning_levels=[ReasoningLevel.LOW, ReasoningLevel.MEDIUM, ReasoningLevel.HIGH],
            default_reasoning=ReasoningLevel.MEDIUM,
            context_window=272000,
            tier=1,
        ),
    ),
    "gemini-3-pro": ModelInfo(
        id="gemini-3-pro",
        name="Gemini 3 Pro",
        engine="cursor",
        description="Google Gemini 3 Pro via Cursor",
        capabilities=ModelCapabilities(
            supports_thinking_budget=True,
            max_thinking_budget=32768,
            default_thinking_budget=8192,
            context_window=200000,
            tier=1,
        ),
    ),
    "gemini-3-flash": ModelInfo(
        id="gemini-3-flash",
        name="Gemini 3 Flash",
        engine="cursor",
        description="Google Gemini 3 Flash via Cursor - fast",
        capabilities=ModelCapabilities(
            supports_thinking_budget=True,
            max_thinking_budget=16384,
            default_thinking_budget=8192,
            context_window=200000,
            tier=2,
        ),
    ),
    "grok": ModelInfo(
        id="grok",
        name="Grok Code",
        engine="cursor",
        description="xAI Grok via Cursor",
        capabilities=ModelCapabilities(
            supports_reasoning=True,
            context_window=256000,
            tier=2,
        ),
    ),
    "composer-1": ModelInfo(
        id="composer-1",
        name="Composer 1",
        engine="cursor",
        description="Cursor's own Composer model",
        capabilities=ModelCapabilities(
            context_window=200000,
            tier=2,
        ),
    ),
}


# ============================================================================
# Dynamic Model Discovery
# ============================================================================


def _run_cli_command(cmd: list[str], timeout: int = 10) -> str | None:
    """Run a CLI command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout
        logger.debug("CLI command failed", cmd=cmd, stderr=result.stderr)
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug("CLI command error", cmd=cmd, error=str(e))
        return None


def discover_codex_models(binary: str = "codex") -> list[ModelInfo] | None:
    """Attempt to discover available Codex models via CLI.

    Args:
        binary: Path to codex binary.

    Returns:
        List of ModelInfo if discovery succeeds, None otherwise.
    """
    # Try codex --help or codex models list (if available)
    # Currently Codex doesn't have a models list command, so we return None
    # to fall back to static definitions
    output = _run_cli_command([binary, "--version"])
    if output is None:
        return None

    # Codex CLI doesn't expose model list via command
    # Return None to use static definitions
    logger.debug("Codex discovery: using static model definitions")
    return None


def discover_gemini_models(binary: str = "gemini") -> list[ModelInfo] | None:
    """Attempt to discover available Gemini models via CLI.

    Args:
        binary: Path to gemini binary.

    Returns:
        List of ModelInfo if discovery succeeds, None otherwise.
    """
    # Check if gemini CLI is available
    output = _run_cli_command([binary, "--version"])
    if output is None:
        return None

    # Gemini CLI doesn't have a direct model list command
    # The models are defined in settings.json with aliases
    # We could parse ~/.gemini/settings.json but that's user-specific
    # Return None to use static definitions
    logger.debug("Gemini discovery: using static model definitions")
    return None


def discover_copilot_models(binary: str = "copilot") -> list[ModelInfo] | None:
    """Attempt to discover available Copilot models via CLI.

    Args:
        binary: Path to copilot binary.

    Returns:
        List of ModelInfo if discovery succeeds, None otherwise.
    """
    # Check if copilot CLI is available
    output = _run_cli_command([binary, "--version"])
    if output is None:
        return None

    # Copilot CLI shows models in --help but doesn't have a list command
    # Return None to use static definitions
    logger.debug("Copilot discovery: using static model definitions")
    return None


def discover_claude_code_models(binary: str = "claude") -> list[ModelInfo] | None:
    """Attempt to discover available Claude Code models via CLI.

    Args:
        binary: Path to claude binary.

    Returns:
        List of ModelInfo if discovery succeeds, None otherwise.
    """
    # Check if claude CLI is available
    output = _run_cli_command([binary, "--version"])
    if output is None:
        return None

    # Claude Code uses aliases (sonnet, opus, haiku) or full model names
    # No discovery command available, use static definitions
    logger.debug("Claude Code discovery: using static model definitions")
    return None


def discover_cursor_models(binary: str = "agent") -> list[ModelInfo] | None:
    """Attempt to discover available Cursor models via CLI.

    Args:
        binary: Path to agent binary.

    Returns:
        List of ModelInfo if discovery succeeds, None otherwise.
    """
    # Check if agent CLI is available
    output = _run_cli_command([binary, "--version"])
    if output is None:
        return None

    # Cursor CLI doesn't expose a model list command
    # Models are listed in documentation, use static definitions
    logger.debug("Cursor discovery: using static model definitions")
    return None


@lru_cache(maxsize=1)
def get_available_models(
    engine: str,
    binary: str | None = None,
    include_preview: bool = True,
) -> list[ModelInfo]:
    """Get available models for an engine.

    Attempts dynamic discovery first, falls back to static definitions.

    Args:
        engine: Engine type ("codex", "gemini", or "copilot").
        binary: Optional path to CLI binary.
        include_preview: Whether to include preview models.

    Returns:
        List of ModelInfo for available models.
    """
    models: list[ModelInfo] = []

    if engine == "codex":
        discovered = discover_codex_models(binary or "codex")
        models = discovered or list(CODEX_MODELS.values())
    elif engine == "gemini":
        discovered = discover_gemini_models(binary or "gemini")
        models = discovered or list(GEMINI_MODELS.values())
    elif engine == "copilot":
        discovered = discover_copilot_models(binary or "copilot")
        models = discovered or list(COPILOT_MODELS.values())
    elif engine == "claude_code":
        discovered = discover_claude_code_models(binary or "claude")
        models = discovered or list(CLAUDE_CODE_MODELS.values())
    elif engine == "cursor":
        discovered = discover_cursor_models(binary or "agent")
        models = discovered or list(CURSOR_MODELS.values())

    if not include_preview:
        models = [m for m in models if not m.capabilities.is_preview]

    # Sort by tier (best first), then by name
    models.sort(key=lambda m: (m.capabilities.tier, m.name))

    return models


def get_model_info(model_id: str, engine: str | None = None) -> ModelInfo | None:
    """Get information about a specific model.

    Args:
        model_id: Model identifier.
        engine: Optional engine hint.

    Returns:
        ModelInfo if found, None otherwise.
    """
    # Check Codex models
    if engine is None or engine == "codex":
        if model_id in CODEX_MODELS:
            return CODEX_MODELS[model_id]
        # Check aliases
        for model in CODEX_MODELS.values():
            if model_id in model.aliases:
                return model

    # Check Gemini models
    if engine is None or engine == "gemini":
        if model_id in GEMINI_MODELS:
            return GEMINI_MODELS[model_id]
        # Check aliases
        for model in GEMINI_MODELS.values():
            if model_id in model.aliases:
                return model

    # Check Copilot models
    if engine is None or engine == "copilot":
        if model_id in COPILOT_MODELS:
            return COPILOT_MODELS[model_id]
        # Check aliases
        for model in COPILOT_MODELS.values():
            if model_id in model.aliases:
                return model

    # Check Claude Code models
    if engine is None or engine == "claude_code":
        if model_id in CLAUDE_CODE_MODELS:
            return CLAUDE_CODE_MODELS[model_id]
        # Check aliases
        for model in CLAUDE_CODE_MODELS.values():
            if model_id in model.aliases:
                return model

    # Check Cursor models
    if engine is None or engine == "cursor":
        if model_id in CURSOR_MODELS:
            return CURSOR_MODELS[model_id]
        # Check aliases
        for model in CURSOR_MODELS.values():
            if model_id in model.aliases:
                return model

    return None


def get_fallback_model(
    current_model: str,
    engine: str,
    error_type: str | None = None,  # noqa: ARG001  Reserved for future error-specific fallback
) -> ModelInfo | None:
    """Get a fallback model when the current one fails.

    Args:
        current_model: Current model that failed.
        engine: Engine type.
        error_type: Optional error type hint (e.g., "quota", "capacity").
                    Reserved for future use in smarter fallback selection.

    Returns:
        Fallback ModelInfo, or None if no fallback available.
    """
    current_info = get_model_info(current_model, engine)
    if current_info is None:
        return None

    current_tier = current_info.capabilities.tier
    available = get_available_models(engine, include_preview=False)

    # Find models in lower tiers (higher tier number = lower priority)
    fallbacks = [m for m in available if m.capabilities.tier > current_tier and m.id != current_model]

    if not fallbacks:
        # No lower tier, try same tier but different model
        fallbacks = [m for m in available if m.capabilities.tier == current_tier and m.id != current_model]

    if fallbacks:
        return fallbacks[0]

    return None

def get_default_model(engine: str) -> str:
    """Get the default model for an engine.

    Args:
        engine: Engine type.

    Returns:
        Default model ID.
    """
    if engine == "codex":
        return "gpt-5.2-codex"
    elif engine == "gemini":
        return "gemini-2.5-flash"
    elif engine == "copilot":
        return "claude-haiku-4.5"  # Fast, efficient default
    elif engine == "claude_code":
        return "sonnet"  # Balanced default
    elif engine == "cursor":
        return "auto"  # Cursor auto-selects best model
    return ""


def get_model_ids(engine: str, include_preview: bool = True) -> list[str]:
    """Get list of model IDs for an engine.

    Args:
        engine: Engine type.
        include_preview: Whether to include preview models.

    Returns:
        List of model ID strings.
    """
    models = get_available_models(engine, include_preview=include_preview)
    return [m.id for m in models]


def serialize_models_for_api(engine: str, include_preview: bool = True) -> list[dict[str, Any]]:
    """Serialize models for API response.

    Args:
        engine: Engine type.
        include_preview: Whether to include preview models.

    Returns:
        List of model dicts for JSON response.
    """
    models = get_available_models(engine, include_preview=include_preview)
    return [m.to_dict() for m in models]
