"""Pipeline and Node definition models."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from orx.pipeline.constants import (
    DEFAULT_NODE_TIMEOUT,
    MAX_MAP_CONCURRENCY,
    MAX_NODE_RETRIES,
    MAX_NODES_PER_PIPELINE,
)


class NodeType(str, Enum):
    """Type of pipeline node."""

    LLM_TEXT = "llm_text"  # LLM generates text output (plan, spec, review)
    LLM_APPLY = "llm_apply"  # LLM applies filesystem changes (implement)
    MAP = "map"  # Iterates over a collection (backlog items)
    GATE = "gate"  # Runs verification gates (ruff, pytest)
    CUSTOM = "custom"  # Custom Python callable


class NodeConfig(BaseModel):
    """Configuration for a pipeline node.

    Attributes:
        model: Override model for this node.
        timeout_seconds: Timeout for node execution.
        max_retries: Maximum retry attempts on failure.
        gates: List of gate names (for type=gate).
        concurrency: Parallel workers (for type=map).
        item_pipeline: Nested pipeline for each item (for type=map).
        callable_path: Python path to callable (for type=custom).
        extra: Additional node-specific configuration.
    """

    model: str | None = None
    timeout_seconds: int = Field(default=DEFAULT_NODE_TIMEOUT, ge=30)
    max_retries: int = Field(default=0, ge=0, le=MAX_NODE_RETRIES)
    gates: list[str] = Field(default_factory=list)
    concurrency: int = Field(default=1, ge=1, le=MAX_MAP_CONCURRENCY)
    item_pipeline: list[NodeDefinition] = Field(default_factory=list)
    callable_path: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    class Config:
        """Pydantic config."""

        extra = "allow"


class NodeDefinition(BaseModel):
    """Definition of a single pipeline node.

    Attributes:
        id: Unique identifier for the node.
        type: The node type (llm_text, llm_apply, map, gate, custom).
        template: Path to prompt template (relative to templates/).
        inputs: List of context block keys required as input.
        outputs: List of context block keys produced as output.
        config: Node-specific configuration.
        description: Human-readable description.
        skip_on_resume: Whether to skip this node when resuming.
    """

    id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    type: NodeType
    template: str | None = None
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    config: NodeConfig = Field(default_factory=NodeConfig)
    description: str = ""
    skip_on_resume: bool = False

    @field_validator("inputs", "outputs")
    @classmethod
    def validate_context_keys(cls, v: list[str]) -> list[str]:
        """Validate context block keys are valid identifiers."""
        for key in v:
            if not key.isidentifier():
                msg = f"Invalid context key: {key}"
                raise ValueError(msg)
        return v

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = self.model_dump(mode="json")
        # Recursively handle nested item_pipeline
        if self.config.item_pipeline:
            data["config"]["item_pipeline"] = [
                n.to_dict() for n in self.config.item_pipeline
            ]
        return data


# Update forward reference
NodeConfig.model_rebuild()


class PipelineDefinition(BaseModel):
    """Complete definition of a pipeline.

    Attributes:
        id: Unique identifier for the pipeline.
        name: Human-readable name.
        description: Description of the pipeline purpose.
        nodes: Ordered list of nodes to execute.
        default_context: Context blocks to auto-extract before execution.
        builtin: Whether this is a built-in pipeline (cannot be deleted).
        version: Schema version for future compatibility.
    """

    id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(..., min_length=1, max_length=128)
    description: str = ""
    nodes: list[NodeDefinition] = Field(default_factory=list)
    default_context: list[str] = Field(default_factory=list)
    builtin: bool = False
    version: str = "1.0"

    @field_validator("nodes")
    @classmethod
    def validate_nodes(cls, v: list[NodeDefinition]) -> list[NodeDefinition]:
        """Validate node list."""
        if len(v) > MAX_NODES_PER_PIPELINE:
            msg = f"Pipeline cannot have more than {MAX_NODES_PER_PIPELINE} nodes"
            raise ValueError(msg)

        # Check for duplicate node IDs
        ids = [n.id for n in v]
        if len(ids) != len(set(ids)):
            msg = "Duplicate node IDs found"
            raise ValueError(msg)

        return v

    def get_node(self, node_id: str) -> NodeDefinition | None:
        """Get a node by ID."""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "nodes": [n.to_dict() for n in self.nodes],
            "default_context": self.default_context,
            "builtin": self.builtin,
            "version": self.version,
        }

    def to_yaml(self) -> str:
        """Serialize to YAML string."""
        import yaml

        return yaml.dump(self.to_dict(), default_flow_style=False, sort_keys=False)
