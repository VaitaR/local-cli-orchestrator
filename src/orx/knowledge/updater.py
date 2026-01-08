"""Knowledge updater - coordinates AGENTS.md and ARCHITECTURE.md updates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog

from orx.config import KnowledgeConfig
from orx.executors.base import Executor
from orx.knowledge.evidence import EvidencePack
from orx.knowledge.guardrails import ChangeStats, KnowledgeGuardrails
from orx.paths import RunPaths
from orx.prompts.renderer import PromptRenderer

logger = structlog.get_logger()


@dataclass
class KnowledgeUpdateResult:
    """Result of a knowledge update operation.

    Attributes:
        agents_updated: Whether AGENTS.md was updated.
        arch_updated: Whether ARCHITECTURE.md was updated.
        arch_gatekeeping: Gatekeeping decision for architecture (YES/NO/SKIPPED).
        agents_stats: Change statistics for AGENTS.md.
        arch_stats: Change statistics for ARCHITECTURE.md.
        report: Full update report.
        agents_patch: Diff for AGENTS.md changes.
        arch_patch: Diff for ARCHITECTURE.md changes.
    """

    agents_updated: bool = False
    arch_updated: bool = False
    arch_gatekeeping: str = "SKIPPED"  # YES, NO, SKIPPED
    agents_stats: ChangeStats | None = None
    arch_stats: ChangeStats | None = None
    report: str = ""
    agents_patch: str = ""
    arch_patch: str = ""


class KnowledgeUpdater:
    """Coordinates knowledge file updates.

    Handles the two-agent approach:
    1. Knowledge Architect (AGENTS.md update)
    2. Principal Architect (ARCHITECTURE.md update with gatekeeping)

    Example:
        >>> updater = KnowledgeUpdater(config, paths, executor, repo_root)
        >>> result = updater.run()
        >>> result.agents_updated
        True
    """

    def __init__(
        self,
        config: KnowledgeConfig,
        paths: RunPaths,
        executor: Executor,
        repo_root: Path,
    ) -> None:
        """Initialize the knowledge updater.

        Args:
            config: Knowledge configuration.
            paths: RunPaths for artifact locations.
            executor: Executor for running prompts.
            repo_root: Root of the target repository.
        """
        self.config = config
        self.paths = paths
        self.executor = executor
        self.repo_root = repo_root
        self.guardrails = KnowledgeGuardrails(config)
        self.renderer = PromptRenderer()

    def run(self, evidence: EvidencePack) -> KnowledgeUpdateResult:
        """Run the knowledge update process.

        Args:
            evidence: EvidencePack with all collected evidence.

        Returns:
            KnowledgeUpdateResult with update details.
        """
        log = logger.bind(run_id=self.paths.run_id)
        log.info("Starting knowledge update")

        result = KnowledgeUpdateResult()
        report_sections: list[str] = ["# Knowledge Update Report\n"]

        # 1. Update AGENTS.md
        if self.guardrails.is_file_allowed("AGENTS.md"):
            try:
                agents_result = self._update_agents(evidence)
                result.agents_updated = agents_result["updated"]
                result.agents_stats = agents_result.get("stats")
                result.agents_patch = agents_result.get("patch", "")
                report_sections.append(self._format_agents_report(agents_result))
            except Exception as e:
                log.error("Failed to update AGENTS.md", error=str(e))
                report_sections.append(f"## AGENTS.md Update: FAILED\n\nError: {e}\n")

        # 2. Update ARCHITECTURE.md (with gatekeeping)
        if self.guardrails.is_file_allowed("ARCHITECTURE.md"):
            try:
                arch_result = self._update_architecture(evidence)
                result.arch_updated = arch_result["updated"]
                result.arch_gatekeeping = arch_result.get("gatekeeping", "SKIPPED")
                result.arch_stats = arch_result.get("stats")
                result.arch_patch = arch_result.get("patch", "")
                report_sections.append(self._format_arch_report(arch_result))
            except Exception as e:
                log.error("Failed to update ARCHITECTURE.md", error=str(e))
                report_sections.append(
                    f"## ARCHITECTURE.md Update: FAILED\n\nError: {e}\n"
                )

        # Generate full report
        result.report = "\n".join(report_sections)

        # Save report
        self._save_report(result)

        log.info(
            "Knowledge update completed",
            agents_updated=result.agents_updated,
            arch_updated=result.arch_updated,
            arch_gatekeeping=result.arch_gatekeeping,
        )

        return result

    def _update_agents(self, evidence: EvidencePack) -> dict:
        """Update AGENTS.md.

        Args:
            evidence: Evidence pack.

        Returns:
            Dict with update results.
        """
        log = logger.bind(file="AGENTS.md")
        log.info("Updating AGENTS.md")

        agents_path = self.repo_root / "AGENTS.md"
        current_content = evidence.current_agents_md

        # Check/create markers
        if not self.guardrails.validate_markers_present(current_content, "agents"):
            log.info("Creating markers in AGENTS.md")
            current_content = current_content + self.guardrails.create_markers("agents")
            agents_path.write_text(current_content)

        # Get current ORX block
        bounds = self.guardrails.find_marker_bounds(current_content, "agents")
        current_orx_block = bounds.content if bounds else ""

        # Render prompt
        prompt = self.renderer.render(
            "knowledge_agents",
            spec=evidence.spec,
            backlog_yaml=evidence.backlog_yaml,
            changed_files=evidence.changed_files,
            patch_diff=evidence.patch_diff,
            review=evidence.review,
            current_orx_block=current_orx_block,
        )

        # Save prompt
        prompt_path = self.paths.prompts / "knowledge_agents.md"
        prompt_path.write_text(prompt)

        # Run executor
        exec_result = self.executor.run_text(
            prompt=prompt,
            log_path=self.paths.log_path("knowledge_agents"),
        )

        if not exec_result.success or not exec_result.output:
            log.warning("Executor failed or returned empty output")
            return {"updated": False, "reason": "Executor failed"}

        # Apply update within markers
        new_content = self.guardrails.replace_marker_content(
            current_content,
            "agents",
            exec_result.output,
        )

        # Validate limits
        stats = self.guardrails.validate_change_limits(
            current_content,
            new_content,
            "AGENTS.md",
        )

        # Apply update if in auto mode
        if self.config.mode == "auto":
            agents_path.write_text(new_content)
            log.info(
                "AGENTS.md updated",
                added=stats.added_lines,
                deleted=stats.deleted_lines,
            )
        else:
            log.info("AGENTS.md update suggested (mode=suggest)")

        # Generate patch
        patch = self._generate_diff(current_content, new_content, "AGENTS.md")

        return {
            "updated": self.config.mode == "auto",
            "stats": stats,
            "patch": patch,
            "new_content": exec_result.output,
        }

    def _update_architecture(self, evidence: EvidencePack) -> dict:
        """Update ARCHITECTURE.md with gatekeeping.

        Args:
            evidence: Evidence pack.

        Returns:
            Dict with update results.
        """
        log = logger.bind(file="ARCHITECTURE.md")
        log.info("Updating ARCHITECTURE.md")

        # Pre-gatekeeping based on changed files
        if not self.guardrails.should_update_architecture(evidence.changed_files):
            log.info("Architecture update not warranted by changed files")
            return {
                "updated": False,
                "gatekeeping": "NO",
                "reason": "Changed files don't affect architecture",
            }

        arch_path = self.repo_root / "ARCHITECTURE.md"
        current_content = evidence.current_arch_md

        if not current_content:
            log.warning("ARCHITECTURE.md not found, skipping")
            return {
                "updated": False,
                "gatekeeping": "SKIPPED",
                "reason": "File not found",
            }

        # Check/create markers
        if not self.guardrails.validate_markers_present(current_content, "arch"):
            log.info("Creating markers in ARCHITECTURE.md")
            current_content = current_content + self.guardrails.create_markers("arch")
            arch_path.write_text(current_content)

        # Get current ORX block
        bounds = self.guardrails.find_marker_bounds(current_content, "arch")
        current_orx_block = bounds.content if bounds else ""

        # Render prompt
        prompt = self.renderer.render(
            "knowledge_arch",
            spec=evidence.spec,
            changed_files=evidence.changed_files,
            patch_diff=evidence.patch_diff,
            current_orx_block=current_orx_block,
        )

        # Save prompt
        prompt_path = self.paths.prompts / "knowledge_arch.md"
        prompt_path.write_text(prompt)

        # Run executor
        exec_result = self.executor.run_text(
            prompt=prompt,
            log_path=self.paths.log_path("knowledge_arch"),
        )

        if not exec_result.success or not exec_result.output:
            log.warning("Executor failed or returned empty output")
            return {
                "updated": False,
                "gatekeeping": "SKIPPED",
                "reason": "Executor failed",
            }

        # Parse gatekeeping decision from output
        output = exec_result.output
        gatekeeping = self._parse_gatekeeping_decision(output)

        if gatekeeping == "NO":
            log.info("Architecture gatekeeping decided NO update needed")
            return {
                "updated": False,
                "gatekeeping": "NO",
                "reason": "Agent decided no update needed",
            }

        # Extract content after gatekeeping decision
        content_to_apply = self._extract_content_after_gatekeeping(output)

        if not content_to_apply.strip():
            log.warning("No content to apply after gatekeeping")
            return {
                "updated": False,
                "gatekeeping": "YES",
                "reason": "No content after gatekeeping",
            }

        # Apply update within markers
        new_content = self.guardrails.replace_marker_content(
            current_content,
            "arch",
            content_to_apply,
        )

        # Validate limits
        stats = self.guardrails.validate_change_limits(
            current_content,
            new_content,
            "ARCHITECTURE.md",
        )

        # Apply update if in auto mode
        if self.config.mode == "auto":
            arch_path.write_text(new_content)
            log.info(
                "ARCHITECTURE.md updated",
                added=stats.added_lines,
                deleted=stats.deleted_lines,
            )
        else:
            log.info("ARCHITECTURE.md update suggested (mode=suggest)")

        # Generate patch
        patch = self._generate_diff(current_content, new_content, "ARCHITECTURE.md")

        return {
            "updated": self.config.mode == "auto",
            "gatekeeping": "YES",
            "stats": stats,
            "patch": patch,
            "new_content": content_to_apply,
        }

    def _parse_gatekeeping_decision(self, output: str) -> str:
        """Parse the gatekeeping decision from executor output.

        Args:
            output: Executor output text.

        Returns:
            "YES" or "NO".
        """
        output_upper = output.upper()
        if "GATEKEEPING: NO" in output_upper or "GATEKEEPING:NO" in output_upper:
            return "NO"
        if "GATEKEEPING: YES" in output_upper or "GATEKEEPING:YES" in output_upper:
            return "YES"
        # Default to YES if unclear (conservative approach)
        return "YES"

    def _extract_content_after_gatekeeping(self, output: str) -> str:
        """Extract content after the gatekeeping decision.

        Args:
            output: Full executor output.

        Returns:
            Content to apply (after GATEKEEPING: YES line).
        """
        lines = output.split("\n")
        start_idx = 0

        for i, line in enumerate(lines):
            if "GATEKEEPING:" in line.upper():
                start_idx = i + 1
                break

        # Skip any "Reason:" line if present
        while start_idx < len(lines) and lines[start_idx].strip().startswith("Reason:"):
            start_idx += 1

        return "\n".join(lines[start_idx:])

    def _generate_diff(self, old: str, new: str, filename: str) -> str:
        """Generate a unified diff between old and new content.

        Args:
            old: Original content.
            new: New content.
            filename: Name of the file.

        Returns:
            Unified diff string.
        """
        import difflib

        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)

        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
        )

        return "".join(diff)

    def _format_agents_report(self, result: dict) -> str:
        """Format AGENTS.md update report section.

        Args:
            result: Update result dict.

        Returns:
            Formatted report section.
        """
        lines = ["## AGENTS.md Update\n"]

        if result.get("updated"):
            lines.append("**Status:** ✅ UPDATED\n")
        else:
            lines.append("**Status:** ⏸️ NOT UPDATED\n")
            if "reason" in result:
                lines.append(f"**Reason:** {result['reason']}\n")

        if result.get("stats"):
            stats = result["stats"]
            lines.append(
                f"**Lines changed:** +{stats.added_lines} / -{stats.deleted_lines}\n"
            )

        return "\n".join(lines)

    def _format_arch_report(self, result: dict) -> str:
        """Format ARCHITECTURE.md update report section.

        Args:
            result: Update result dict.

        Returns:
            Formatted report section.
        """
        lines = ["## ARCHITECTURE.md Update\n"]
        lines.append(
            f"**Gatekeeping Decision:** {result.get('gatekeeping', 'SKIPPED')}\n"
        )

        if result.get("updated"):
            lines.append("**Status:** ✅ UPDATED\n")
        else:
            lines.append("**Status:** ⏸️ NOT UPDATED\n")
            if "reason" in result:
                lines.append(f"**Reason:** {result['reason']}\n")

        if result.get("stats"):
            stats = result["stats"]
            lines.append(
                f"**Lines changed:** +{stats.added_lines} / -{stats.deleted_lines}\n"
            )

        return "\n".join(lines)

    def _save_report(self, result: KnowledgeUpdateResult) -> None:
        """Save the knowledge update report and patches.

        Args:
            result: KnowledgeUpdateResult to save.
        """
        # Save report
        report_path = self.paths.artifacts / "knowledge_update_report.md"
        report_path.write_text(result.report)

        # Save combined patch
        combined_patch = ""
        if result.agents_patch:
            combined_patch += result.agents_patch
        if result.arch_patch:
            combined_patch += "\n" + result.arch_patch

        if combined_patch:
            patch_path = self.paths.artifacts / "knowledge.patch.diff"
            patch_path.write_text(combined_patch)
