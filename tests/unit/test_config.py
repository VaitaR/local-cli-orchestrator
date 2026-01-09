"""Unit tests for configuration schema and serialization."""

from __future__ import annotations

from orx.config import EngineType, OrxConfig


def test_config_serialization() -> None:
    """Verify available_models and stage_models are correctly loaded/saved in YAML."""
    config = OrxConfig.default(EngineType.GEMINI)

    # Custom settings
    config.executors.gemini.available_models = ["model-1", "model-2"]
    config.executors.gemini.stage_models = {"plan": "model-1", "implement": "model-2"}

    # Serialize to YAML
    yaml_content = config.to_yaml()

    # Verify strings are present in YAML
    assert "available_models:" in yaml_content
    assert "- model-1" in yaml_content
    assert "- model-2" in yaml_content
    assert "stage_models:" in yaml_content
    assert "plan: model-1" in yaml_content
    assert "implement: model-2" in yaml_content

    # Reload from YAML
    loaded_config = OrxConfig.from_yaml(yaml_content)

    assert loaded_config.executors.gemini.available_models == ["model-1", "model-2"]
    assert loaded_config.executors.gemini.stage_models["plan"] == "model-1"
    assert loaded_config.executors.gemini.stage_models["implement"] == "model-2"


def test_default_config_population() -> None:
    """Verify default config populates Gemini and Codex models."""
    config = OrxConfig.default()

    required_stages = ["plan", "spec", "decompose", "implement", "fix", "review"]

    # Gemini - now uses dynamic discovery with gemini-2.5-flash as default
    assert config.executors.gemini.available_models
    assert "gemini-2.5-flash" in config.executors.gemini.available_models
    assert config.executors.gemini.default.model == "gemini-2.5-flash"
    for stage in required_stages:
        assert config.executors.gemini.stage_models[stage] == "gemini-2.5-flash"

    # Codex - now uses dynamic discovery with gpt-5.2-codex as default
    assert config.executors.codex.available_models
    assert "gpt-5.2-codex" in config.executors.codex.available_models
    assert config.executors.codex.default.model == "gpt-5.2-codex"
    for stage in required_stages:
        assert config.executors.codex.stage_models[stage] == "gpt-5.2-codex"


def test_from_yaml_backfills_executor_model_config() -> None:
    """Older configs may omit executor model lists and stage defaults."""
    cfg = OrxConfig.from_yaml(
        "engine:\n"
        "  type: gemini\n"
        "executors:\n"
        "  gemini:\n"
        "    stage_models:\n"
        "      plan: gemini-1.5-pro\n"
    )

    # available_models should be filled from defaults (dynamic discovery)
    assert "gemini-2.5-flash" in cfg.executors.gemini.available_models

    # stage_models should preserve explicit overrides and fill missing stages
    assert cfg.executors.gemini.stage_models["plan"] == "gemini-1.5-pro"
    assert cfg.executors.gemini.stage_models["spec"] == "gemini-2.5-flash"
