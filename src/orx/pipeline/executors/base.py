"""Base protocol and types for node executors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from orx.config import OrxConfig
    from orx.executors.base import Executor
    from orx.gates.base import Gate
    from orx.paths import RunPaths
    from orx.pipeline.artifacts import ArtifactStore
    from orx.pipeline.definition import NodeDefinition
    from orx.prompts.renderer import PromptRenderer
    from orx.workspace.git_worktree import WorkspaceGitWorktree


@dataclass
class NodeResult:
    """Result of node execution.

    Attributes:
        success: Whether the node executed successfully.
        outputs: Dictionary of output artifacts.
        error: Error message if failed.
        metrics: Execution metrics (duration, tokens, etc.).
        metadata: Additional metadata (e.g., review verdict).
    """

    success: bool
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        """Return success status."""
        return self.success


@dataclass
class ExecutionContext:
    """Context for node execution.

    Provides all dependencies needed by node executors.

    Attributes:
        config: ORX configuration.
        paths: Run paths.
        store: Artifact store.
        workspace: Git worktree.
        executor: LLM executor.
        gates: Quality gates.
        renderer: Prompt renderer.
    """

    config: OrxConfig
    paths: RunPaths
    store: ArtifactStore
    workspace: WorkspaceGitWorktree
    executor: Executor
    gates: list[Gate]
    renderer: PromptRenderer
    timeout_seconds: int | None = None


class NodeExecutor(Protocol):
    """Protocol for node executors.

    Each node type has a corresponding executor that implements
    the actual execution logic.
    """

    def execute(
        self,
        node: NodeDefinition,
        context: dict[str, Any],
        exec_ctx: ExecutionContext,
    ) -> NodeResult:
        """Execute the node.

        Args:
            node: Node definition.
            context: Input context dictionary.
            exec_ctx: Execution context with dependencies.

        Returns:
            NodeResult with outputs or error.
        """
        ...
