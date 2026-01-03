"""Knowledge update stage - self-improvement of AGENTS.md and ARCHITECTURE.md."""

from __future__ import annotations

import structlog

from orx.knowledge.evidence import EvidenceCollector
from orx.knowledge.updater import KnowledgeUpdater
from orx.stages.base import BaseStage, StageContext, StageResult

logger = structlog.get_logger()


class KnowledgeUpdateStage(BaseStage):
    """Stage that updates knowledge files after successful task completion.

    This stage runs after VERIFY success and updates:
    - AGENTS.md: Coding patterns, gotchas, file locations
    - ARCHITECTURE.md: High-level architectural changes (with gatekeeping)

    The updates are scoped to ORX marker blocks and subject to guardrails.
    """

    @property
    def name(self) -> str:
        """Name of the stage."""
        return "knowledge_update"

    def execute(self, ctx: StageContext) -> StageResult:
        """Execute the knowledge update stage.

        Args:
            ctx: Stage context.

        Returns:
            StageResult indicating success/failure.
        """
        log = logger.bind(stage=self.name)
        log.info("Executing knowledge update stage")

        # Check if knowledge updates are enabled
        knowledge_config = ctx.config.get("knowledge", {})
        if not knowledge_config.get("enabled", True):
            log.info("Knowledge updates disabled")
            return self._success("Knowledge updates disabled", data={"skipped": True})

        mode = knowledge_config.get("mode", "auto")
        if mode == "off":
            log.info("Knowledge update mode is 'off'")
            return self._success("Knowledge update mode is off", data={"skipped": True})

        try:
            # Import here to avoid circular imports
            from orx.config import KnowledgeConfig

            # Parse knowledge config
            k_config = KnowledgeConfig.model_validate(knowledge_config)

            # Collect evidence
            collector = EvidenceCollector(
                paths=ctx.paths,
                pack=ctx.pack,
                repo_root=ctx.workspace.worktree_path.parent.parent,  # Go up from worktree
            )
            evidence = collector.collect()

            # Run updater
            updater = KnowledgeUpdater(
                config=k_config,
                paths=ctx.paths,
                executor=ctx.executor,
                repo_root=ctx.workspace.worktree_path.parent.parent,
            )
            result = updater.run(evidence)

            log.info(
                "Knowledge update completed",
                agents_updated=result.agents_updated,
                arch_updated=result.arch_updated,
                arch_gatekeeping=result.arch_gatekeeping,
            )

            return self._success(
                f"Knowledge update completed: agents={result.agents_updated}, arch={result.arch_updated}",
                data={
                    "agents_updated": result.agents_updated,
                    "arch_updated": result.arch_updated,
                    "arch_gatekeeping": result.arch_gatekeeping,
                },
            )

        except Exception as e:
            log.error("Knowledge update failed", error=str(e))
            # Knowledge update failure should not fail the entire run
            return self._success(
                f"Knowledge update failed (non-fatal): {e}",
                data={"error": str(e), "fatal": False},
            )
