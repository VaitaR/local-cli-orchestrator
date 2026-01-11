"""Unit tests for pipeline module."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from orx.pipeline.artifacts import ArtifactStore
from orx.pipeline.constants import (
    AUTO_EXTRACT_CONTEXTS,
    BUILTIN_PIPELINE_IDS,
    DEFAULT_NODE_TIMEOUT,
    MAX_MAP_CONCURRENCY,
    MAX_NODES_PER_PIPELINE,
    MAX_USER_PIPELINES,
)
from orx.pipeline.context_builder import ContextBuilder
from orx.pipeline.definition import (
    NodeConfig,
    NodeDefinition,
    NodeType,
    PipelineDefinition,
)
from orx.pipeline.registry import PipelineRegistry

# ============================================================================
# Constants Tests
# ============================================================================


def test_constants_values():
    """Test that constants have expected values."""
    assert MAX_USER_PIPELINES == 50
    assert MAX_NODES_PER_PIPELINE == 20
    assert MAX_MAP_CONCURRENCY == 8
    assert DEFAULT_NODE_TIMEOUT == 600
    assert "standard" in BUILTIN_PIPELINE_IDS
    assert "fast_fix" in BUILTIN_PIPELINE_IDS
    assert "plan_only" in BUILTIN_PIPELINE_IDS
    assert "repo_map" in AUTO_EXTRACT_CONTEXTS


# ============================================================================
# Definition Tests
# ============================================================================


class TestNodeType:
    """Tests for NodeType enum."""

    def test_all_types_exist(self):
        """Test that all expected node types exist."""
        assert NodeType.LLM_TEXT.value == "llm_text"
        assert NodeType.LLM_APPLY.value == "llm_apply"
        assert NodeType.MAP.value == "map"
        assert NodeType.GATE.value == "gate"
        assert NodeType.CUSTOM.value == "custom"


class TestNodeConfig:
    """Tests for NodeConfig model."""

    def test_default_config(self):
        """Test default NodeConfig values."""
        config = NodeConfig()
        assert config.gates == []
        assert config.concurrency == 1
        assert config.timeout_seconds == DEFAULT_NODE_TIMEOUT  # Has default
        assert config.item_pipeline == []
        assert config.callable_path is None

    def test_config_with_gates(self):
        """Test NodeConfig with gates."""
        config = NodeConfig(gates=["ruff", "pytest"])
        assert config.gates == ["ruff", "pytest"]

    def test_config_with_concurrency(self):
        """Test NodeConfig with concurrency."""
        config = NodeConfig(concurrency=4)
        assert config.concurrency == 4


class TestNodeDefinition:
    """Tests for NodeDefinition model."""

    def test_minimal_definition(self):
        """Test minimal node definition."""
        node = NodeDefinition(
            id="test_node",
            type=NodeType.LLM_TEXT,
        )
        assert node.id == "test_node"
        assert node.type == NodeType.LLM_TEXT
        assert node.inputs == []
        assert node.outputs == []
        assert node.template is None

    def test_full_definition(self):
        """Test full node definition."""
        node = NodeDefinition(
            id="plan",
            type=NodeType.LLM_TEXT,
            template="plan.md",
            inputs=["task", "repo_map"],
            outputs=["plan"],
            config=NodeConfig(timeout_seconds=300),
        )
        assert node.id == "plan"
        assert node.template == "plan.md"
        assert node.inputs == ["task", "repo_map"]
        assert node.outputs == ["plan"]
        assert node.config.timeout_seconds == 300


class TestPipelineDefinition:
    """Tests for PipelineDefinition model."""

    def test_minimal_pipeline(self):
        """Test minimal pipeline definition."""
        node = NodeDefinition(id="test", type=NodeType.LLM_TEXT)
        pipeline = PipelineDefinition(
            id="test_pipeline",
            name="Test Pipeline",
            nodes=[node],
        )
        assert pipeline.id == "test_pipeline"
        assert pipeline.name == "Test Pipeline"
        assert len(pipeline.nodes) == 1

    def test_validation_empty_nodes(self):
        """Test that pipeline can have empty nodes list (no validation error)."""
        # Note: Current implementation allows empty nodes
        pipeline = PipelineDefinition(
            id="empty",
            name="Empty",
            nodes=[],
        )
        assert len(pipeline.nodes) == 0

    def test_validation_max_nodes(self):
        """Test that pipeline enforces max nodes limit."""
        nodes = [
            NodeDefinition(id=f"node_{i}", type=NodeType.LLM_TEXT)
            for i in range(MAX_NODES_PER_PIPELINE + 1)
        ]
        with pytest.raises(ValueError):
            PipelineDefinition(
                id="too_many",
                name="Too Many Nodes",
                nodes=nodes,
            )

    def test_serialization(self):
        """Test pipeline serialization."""
        node = NodeDefinition(id="test", type=NodeType.LLM_TEXT)
        pipeline = PipelineDefinition(
            id="test",
            name="Test",
            description="A test pipeline",
            nodes=[node],
        )
        data = pipeline.model_dump(mode="json")
        assert data["id"] == "test"
        assert data["nodes"][0]["type"] == "llm_text"


# ============================================================================
# ArtifactStore Tests
# ============================================================================


class TestArtifactStore:
    """Tests for ArtifactStore."""

    @pytest.fixture
    def temp_paths(self):
        """Create temporary run paths."""
        from orx.paths import RunPaths

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = RunPaths.create_new(Path(tmpdir))
            yield paths

    def test_set_and_get(self, temp_paths):
        """Test basic set and get."""
        store = ArtifactStore(temp_paths)
        store.set("test_key", "test_value", source_node="test")
        assert store.get("test_key") == "test_value"

    def test_get_nonexistent(self, temp_paths):
        """Test get for nonexistent key."""
        store = ArtifactStore(temp_paths)
        assert store.get("nonexistent") is None
        # Note: ArtifactStore.get() doesn't support default argument

    def test_exists(self, temp_paths):
        """Test exists check."""
        store = ArtifactStore(temp_paths)
        assert not store.exists("key")
        store.set("key", "value", source_node="test")
        assert store.exists("key")

    def test_keys(self, temp_paths):
        """Test listing keys."""
        store = ArtifactStore(temp_paths)
        store.set("key1", "value1", source_node="test")
        store.set("key2", "value2", source_node="test")
        keys = store.keys()
        assert "key1" in keys
        assert "key2" in keys

    def test_known_key_persistence(self, temp_paths):
        """Test that known keys are persisted to disk."""
        store = ArtifactStore(temp_paths)
        store.set("task", "My task", source_node="input")
        store.set("plan", "My plan", source_node="plan")

        # Check files exist
        assert temp_paths.task_md.exists()
        assert temp_paths.plan_md.exists()

        # Create new store and verify data
        store2 = ArtifactStore(temp_paths)
        assert store2.get("task") == "My task"
        assert store2.get("plan") == "My plan"


# ============================================================================
# ContextBuilder Tests
# ============================================================================


class TestContextBuilder:
    """Tests for ContextBuilder."""

    @pytest.fixture
    def temp_paths(self):
        """Create temporary run paths."""
        from orx.paths import RunPaths

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = RunPaths.create_new(Path(tmpdir))
            yield paths

    def test_build_for_node_empty_context(self, temp_paths):
        """Test building context for node with no context requirements."""
        store = ArtifactStore(temp_paths)
        builder = ContextBuilder(store, temp_paths.run_dir)

        node = NodeDefinition(id="test", type=NodeType.LLM_TEXT, inputs=[])
        ctx = builder.build_for_node(node)
        assert ctx == {}

    def test_build_for_node_with_task(self, temp_paths):
        """Test building context with task."""
        store = ArtifactStore(temp_paths)
        store.set("task", "Test task", source_node="input")

        builder = ContextBuilder(store, temp_paths.run_dir)

        node = NodeDefinition(id="test", type=NodeType.LLM_TEXT, inputs=["task"])
        ctx = builder.build_for_node(node)
        assert ctx["task"] == "Test task"

    def test_build_for_node_missing_context(self, temp_paths):
        """Test that missing required context raises error."""
        from orx.pipeline.context_builder import MissingContextError

        store = ArtifactStore(temp_paths)
        builder = ContextBuilder(store, temp_paths.run_dir)

        node = NodeDefinition(id="test", type=NodeType.LLM_TEXT, inputs=["nonexistent"])
        # Missing context should raise MissingContextError
        with pytest.raises(MissingContextError):
            builder.build_for_node(node)


# ============================================================================
# Registry Tests
# ============================================================================


class TestPipelineRegistry:
    """Tests for PipelineRegistry."""

    @pytest.fixture
    def temp_user_dir(self):
        """Create temporary user pipelines directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_builtin_pipelines_exist(self, temp_user_dir):
        """Test that builtin pipelines are available."""
        registry = PipelineRegistry.load(temp_user_dir)
        assert registry.get("standard") is not None
        assert registry.get("fast_fix") is not None
        assert registry.get("plan_only") is not None

    def test_standard_pipeline_structure(self, temp_user_dir):
        """Test standard pipeline has expected structure."""
        registry = PipelineRegistry.load(temp_user_dir)
        pipeline = registry.get("standard")
        assert pipeline is not None

        node_ids = [n.id for n in pipeline.nodes]
        assert "plan" in node_ids
        assert "spec" in node_ids
        assert "decompose" in node_ids

    def test_fast_fix_pipeline_structure(self, temp_user_dir):
        """Test fast_fix pipeline skips planning."""
        registry = PipelineRegistry.load(temp_user_dir)
        pipeline = registry.get("fast_fix")
        assert pipeline is not None

        node_ids = [n.id for n in pipeline.nodes]
        # fast_fix should not have planning stages
        assert "plan" not in node_ids
        assert "spec" not in node_ids

    def test_plan_only_pipeline_structure(self, temp_user_dir):
        """Test plan_only pipeline ends early."""
        registry = PipelineRegistry.load(temp_user_dir)
        pipeline = registry.get("plan_only")
        assert pipeline is not None

        node_ids = [n.id for n in pipeline.nodes]
        assert "plan" in node_ids
        # Should not have implementation
        assert "implement" not in node_ids
        assert "map_implement" not in node_ids

    def test_add_custom_pipeline(self, temp_user_dir):
        """Test adding a custom pipeline."""
        registry = PipelineRegistry.load(temp_user_dir)

        custom = PipelineDefinition(
            id="my_custom",
            name="My Custom Pipeline",
            nodes=[NodeDefinition(id="test", type=NodeType.LLM_TEXT)],
        )
        registry.add(custom)

        assert registry.get("my_custom") is not None
        assert registry.get("my_custom").name == "My Custom Pipeline"

    def test_delete_custom_pipeline(self, temp_user_dir):
        """Test deleting a custom pipeline."""
        registry = PipelineRegistry.load(temp_user_dir)

        custom = PipelineDefinition(
            id="to_delete",
            name="To Delete",
            nodes=[NodeDefinition(id="test", type=NodeType.LLM_TEXT)],
        )
        registry.add(custom)
        assert registry.get("to_delete") is not None

        registry.delete("to_delete")
        # After delete, get should raise PipelineNotFoundError
        from orx.pipeline.registry import PipelineNotFoundError

        with pytest.raises(PipelineNotFoundError):
            registry.get("to_delete")

    def test_cannot_delete_builtin(self, temp_user_dir):
        """Test that builtin pipelines cannot be deleted."""
        registry = PipelineRegistry.load(temp_user_dir)

        # Should raise ValueError when trying to delete builtin
        with pytest.raises(ValueError, match="Cannot delete built-in pipeline"):
            registry.delete("standard")

    def test_list_all(self, temp_user_dir):
        """Test listing all pipelines."""
        registry = PipelineRegistry.load(temp_user_dir)

        all_pipelines = registry.pipelines
        pipeline_ids = [p.id for p in all_pipelines]

        assert "standard" in pipeline_ids
        assert "fast_fix" in pipeline_ids
        assert "plan_only" in pipeline_ids

    def test_save_and_load(self, temp_user_dir):
        """Test saving and loading custom pipelines."""
        registry = PipelineRegistry.load(temp_user_dir)

        custom = PipelineDefinition(
            id="persistent",
            name="Persistent Pipeline",
            nodes=[NodeDefinition(id="test", type=NodeType.LLM_TEXT)],
        )
        registry.add(custom)
        registry.save()

        # Load fresh registry
        registry2 = PipelineRegistry.load(temp_user_dir)
        loaded = registry2.get("persistent")
        assert loaded is not None
        assert loaded.name == "Persistent Pipeline"
