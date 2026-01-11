"""Pipeline configuration constants."""

from __future__ import annotations

# Maximum number of pipelines per user
MAX_USER_PIPELINES: int = 50

# Maximum nodes per pipeline
MAX_NODES_PER_PIPELINE: int = 20

# Maximum concurrency for MapNode
MAX_MAP_CONCURRENCY: int = 8

# Default timeout per node (seconds)
DEFAULT_NODE_TIMEOUT: int = 600

# Maximum retries per node
MAX_NODE_RETRIES: int = 3

# Context block size limits (bytes)
MAX_CONTEXT_BLOCK_SIZE: int = 500_000  # 500KB

# Auto-extracted contexts
AUTO_EXTRACT_CONTEXTS: list[str] = [
    "repo_map",
    "tooling_snapshot",
    "agents_context",
    "architecture",
    "verify_commands",
]

# Built-in pipeline IDs
BUILTIN_PIPELINE_IDS: set[str] = {"standard", "fast_fix", "plan_only"}

# Default pipeline ID
DEFAULT_PIPELINE_ID: str = "standard"
