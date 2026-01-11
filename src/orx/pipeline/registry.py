"""Pipeline registry for managing pipeline definitions."""

from __future__ import annotations

from pathlib import Path

import structlog
import yaml

from orx.pipeline.constants import (
    BUILTIN_PIPELINE_IDS,
    DEFAULT_PIPELINE_ID,
    MAX_USER_PIPELINES,
)
from orx.pipeline.definition import (
    NodeConfig,
    NodeDefinition,
    NodeType,
    PipelineDefinition,
)

logger = structlog.get_logger()


class PipelineNotFoundError(Exception):
    """Raised when a pipeline is not found."""

    pass


class PipelineRegistry:
    """Registry for pipeline definitions.

    Manages built-in and user-defined pipelines with persistence.

    Attributes:
        pipelines: List of all registered pipelines.
    """

    def __init__(self, user_dir: Path | None = None):
        """Initialize the registry.

        Args:
            user_dir: Directory for user-defined pipelines (~/.orx/pipelines/).
        """
        self._user_dir = user_dir or (Path.home() / ".orx" / "pipelines")
        self._pipelines: dict[str, PipelineDefinition] = {}
        self._load_builtin()

    @property
    def pipelines(self) -> list[PipelineDefinition]:
        """Get all registered pipelines."""
        return list(self._pipelines.values())

    def get(self, pipeline_id: str) -> PipelineDefinition:
        """Get a pipeline by ID or load from file path.

        Args:
            pipeline_id: Pipeline identifier or file path.

        Returns:
            PipelineDefinition.

        Raises:
            PipelineNotFoundError: If pipeline not found.
        """
        # Check if it's a file path
        path = Path(pipeline_id)
        if path.exists() and path.is_file():
            try:
                content = path.read_text()
                data = yaml.safe_load(content)
                pipeline = PipelineDefinition.model_validate(data)
                # Mark as non-builtin and cache it
                pipeline.builtin = False
                # Use path as ID for temporary pipelines
                self._pipelines[pipeline_id] = pipeline
                return pipeline
            except Exception as e:
                msg = f"Failed to load pipeline from file '{pipeline_id}': {e}"
                raise PipelineNotFoundError(msg) from e

        # Try loading from registry
        if pipeline_id not in self._pipelines:
            # Try loading from user directory
            self._try_load_user_pipeline(pipeline_id)

        if pipeline_id not in self._pipelines:
            msg = f"Pipeline '{pipeline_id}' not found"
            raise PipelineNotFoundError(msg)

        return self._pipelines[pipeline_id]

    def exists(self, pipeline_id: str) -> bool:
        """Check if a pipeline exists.

        Args:
            pipeline_id: Pipeline identifier.

        Returns:
            True if pipeline exists.
        """
        if pipeline_id in self._pipelines:
            return True
        # Check user directory
        user_path = self._user_dir / f"{pipeline_id}.yaml"
        return user_path.exists()

    def add(self, pipeline: PipelineDefinition) -> None:
        """Add a pipeline to the registry.

        Args:
            pipeline: Pipeline definition to add.

        Raises:
            ValueError: If pipeline ID conflicts with builtin or limit exceeded.
        """
        if pipeline.id in BUILTIN_PIPELINE_IDS and not pipeline.builtin:
            msg = f"Cannot overwrite built-in pipeline: {pipeline.id}"
            raise ValueError(msg)

        user_count = sum(1 for p in self._pipelines.values() if not p.builtin)
        if user_count >= MAX_USER_PIPELINES and pipeline.id not in self._pipelines:
            msg = f"Maximum number of pipelines ({MAX_USER_PIPELINES}) exceeded"
            raise ValueError(msg)

        self._pipelines[pipeline.id] = pipeline

    def delete(self, pipeline_id: str) -> None:
        """Delete a pipeline.

        Args:
            pipeline_id: Pipeline identifier.

        Raises:
            ValueError: If trying to delete a built-in pipeline.
            PipelineNotFoundError: If pipeline not found.
        """
        if pipeline_id in BUILTIN_PIPELINE_IDS:
            msg = f"Cannot delete built-in pipeline: {pipeline_id}"
            raise ValueError(msg)

        if pipeline_id not in self._pipelines:
            msg = f"Pipeline '{pipeline_id}' not found"
            raise PipelineNotFoundError(msg)

        del self._pipelines[pipeline_id]

        # Delete from disk
        user_path = self._user_dir / f"{pipeline_id}.yaml"
        if user_path.exists():
            user_path.unlink()

    def save(self) -> None:
        """Save all user-defined pipelines to disk."""
        self._user_dir.mkdir(parents=True, exist_ok=True)

        for pipeline in self._pipelines.values():
            if not pipeline.builtin:
                path = self._user_dir / f"{pipeline.id}.yaml"
                path.write_text(pipeline.to_yaml())
                logger.debug("Saved pipeline", id=pipeline.id, path=str(path))

    def load_user_pipelines(self) -> None:
        """Load all user-defined pipelines from disk."""
        if not self._user_dir.exists():
            return

        for path in self._user_dir.glob("*.yaml"):
            try:
                content = path.read_text()
                data = yaml.safe_load(content)
                pipeline = PipelineDefinition.model_validate(data)
                pipeline.builtin = False
                self._pipelines[pipeline.id] = pipeline
                logger.debug("Loaded user pipeline", id=pipeline.id)
            except Exception as e:
                logger.warning(
                    "Failed to load user pipeline", path=str(path), error=str(e)
                )

    def _try_load_user_pipeline(self, pipeline_id: str) -> None:
        """Try to load a specific user pipeline from disk.

        Args:
            pipeline_id: Pipeline identifier.
        """
        path = self._user_dir / f"{pipeline_id}.yaml"
        if not path.exists():
            return

        try:
            content = path.read_text()
            data = yaml.safe_load(content)
            pipeline = PipelineDefinition.model_validate(data)
            pipeline.builtin = False
            self._pipelines[pipeline.id] = pipeline
        except Exception as e:
            logger.warning("Failed to load user pipeline", id=pipeline_id, error=str(e))

    def _load_builtin(self) -> None:
        """Load built-in pipeline definitions."""
        # Standard pipeline (full flow)
        self._pipelines["standard"] = self._create_standard_pipeline()
        self._pipelines["fast_fix"] = self._create_fast_fix_pipeline()
        self._pipelines["plan_only"] = self._create_plan_only_pipeline()

    def _create_standard_pipeline(self) -> PipelineDefinition:
        """Create the standard full pipeline."""
        return PipelineDefinition(
            id="standard",
            name="Standard Full Pipeline",
            description="Plan → Spec → Decompose → Implement → Review → Ship",
            builtin=True,
            default_context=[
                "repo_map",
                "tooling_snapshot",
                "agents_context",
                "architecture",
            ],
            nodes=[
                NodeDefinition(
                    id="plan",
                    type=NodeType.LLM_TEXT,
                    template="plan.md",
                    inputs=["task", "repo_map", "agents_context"],
                    outputs=["plan"],
                    description="Generate implementation plan",
                ),
                NodeDefinition(
                    id="spec",
                    type=NodeType.LLM_TEXT,
                    template="spec.md",
                    inputs=["task", "plan", "repo_map", "agents_context"],
                    outputs=["spec"],
                    description="Generate technical specification",
                ),
                NodeDefinition(
                    id="decompose",
                    type=NodeType.LLM_TEXT,
                    template="decompose.md",
                    inputs=["spec", "repo_map", "architecture"],
                    outputs=["backlog"],
                    description="Decompose spec into work items",
                ),
                NodeDefinition(
                    id="implement_loop",
                    type=NodeType.MAP,
                    inputs=["backlog", "spec", "agents_context", "verify_commands"],
                    outputs=["implementation_report"],
                    description="Implement all work items",
                    config=NodeConfig(
                        concurrency=1,
                        item_pipeline=[
                            NodeDefinition(
                                id="implement_item",
                                type=NodeType.LLM_APPLY,
                                template="implement.md",
                                inputs=[
                                    "current_item",
                                    "spec",
                                    "file_snippets",
                                    "agents_context",
                                    "verify_commands",
                                ],
                                outputs=["patch_diff"],
                                description="Implement single work item",
                            ),
                            NodeDefinition(
                                id="verify_item",
                                type=NodeType.GATE,
                                inputs=["patch_diff"],
                                outputs=[],
                                description="Verify changes pass gates",
                                config=NodeConfig(gates=["ruff", "pytest"]),
                            ),
                        ],
                    ),
                ),
                NodeDefinition(
                    id="review",
                    type=NodeType.LLM_TEXT,
                    template="review.md",
                    inputs=["plan", "patch_diff", "backlog"],
                    outputs=["review"],
                    description="Generate code review",
                ),
                NodeDefinition(
                    id="ship",
                    type=NodeType.CUSTOM,
                    inputs=["review", "patch_diff"],
                    outputs=["pr_body"],
                    description="Commit and create PR",
                    config=NodeConfig(
                        callable_path="orx.pipeline.executors.custom:ship_node"
                    ),
                ),
            ],
        )

    def _create_fast_fix_pipeline(self) -> PipelineDefinition:
        """Create the fast fix pipeline (no planning)."""
        return PipelineDefinition(
            id="fast_fix",
            name="Fast Fix",
            description="Directly implement → verify → review → ship",
            builtin=True,
            default_context=["repo_map", "tooling_snapshot", "agents_context"],
            nodes=[
                NodeDefinition(
                    id="implement",
                    type=NodeType.LLM_APPLY,
                    template="implement_direct.md",
                    inputs=["task", "repo_map", "agents_context", "verify_commands"],
                    outputs=["patch_diff"],
                    description="Directly implement the task",
                ),
                NodeDefinition(
                    id="verify",
                    type=NodeType.GATE,
                    inputs=["patch_diff"],
                    outputs=[],
                    description="Verify changes pass gates",
                    config=NodeConfig(gates=["ruff", "pytest"]),
                ),
                NodeDefinition(
                    id="review",
                    type=NodeType.LLM_TEXT,
                    template="review.md",
                    inputs=["task", "patch_diff"],
                    outputs=["review"],
                    description="Generate code review",
                ),
                NodeDefinition(
                    id="ship",
                    type=NodeType.CUSTOM,
                    inputs=["review", "patch_diff"],
                    outputs=["pr_body"],
                    description="Commit and create PR",
                    config=NodeConfig(
                        callable_path="orx.pipeline.executors.custom:ship_node"
                    ),
                ),
            ],
        )

    def _create_plan_only_pipeline(self) -> PipelineDefinition:
        """Create the plan-only pipeline."""
        return PipelineDefinition(
            id="plan_only",
            name="Plan Only",
            description="Generate plan without implementation",
            builtin=True,
            default_context=["repo_map", "agents_context"],
            nodes=[
                NodeDefinition(
                    id="plan",
                    type=NodeType.LLM_TEXT,
                    template="plan.md",
                    inputs=["task", "repo_map", "agents_context"],
                    outputs=["plan"],
                    description="Generate implementation plan",
                ),
            ],
        )

    @classmethod
    def load(cls, user_dir: Path | None = None) -> PipelineRegistry:
        """Load registry with user pipelines.

        Args:
            user_dir: Optional user directory path.

        Returns:
            Loaded PipelineRegistry.
        """
        registry = cls(user_dir)
        registry.load_user_pipelines()
        return registry

    @classmethod
    def get_default_pipeline_id(cls) -> str:
        """Get the default pipeline ID.

        Returns:
            Default pipeline identifier.
        """
        return DEFAULT_PIPELINE_ID
