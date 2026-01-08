"""Context packer with budget management."""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from orx.context.repo_context.blocks import ContextBlock

logger = structlog.get_logger()


# Default budget is ~3000 tokens → ~12k chars with headroom
DEFAULT_CHAR_BUDGET = 11000


@dataclass
class PackResult:
    """Result of packing context blocks.

    Attributes:
        content: Packed markdown content.
        included_blocks: Blocks that fit within budget.
        excluded_blocks: Blocks that didn't fit.
        total_chars: Total character count.
        budget_used_pct: Percentage of budget used.
    """

    content: str
    included_blocks: list[ContextBlock]
    excluded_blocks: list[ContextBlock]
    total_chars: int
    budget_used_pct: float


@dataclass
class ContextPacker:
    """Packs context blocks within a character budget.

    Uses priority to decide which blocks to include. Higher priority
    blocks are included first. When a block doesn't fit, it may be
    rendered in compact form or excluded.

    Attributes:
        char_budget: Maximum characters to include.
        compact_threshold: Char budget percentage at which to use compact rendering.
    """

    char_budget: int = DEFAULT_CHAR_BUDGET
    compact_threshold: float = 0.8  # Start using compact after 80% budget used
    _current_chars: int = field(default=0, init=False)

    def pack(self, blocks: list[ContextBlock]) -> PackResult:
        """Pack blocks within budget.

        Args:
            blocks: List of context blocks to pack.

        Returns:
            PackResult with content and metadata.
        """
        if not blocks:
            return PackResult(
                content="",
                included_blocks=[],
                excluded_blocks=[],
                total_chars=0,
                budget_used_pct=0.0,
            )

        # Sort by priority (descending) and then by title (for determinism)
        sorted_blocks = sorted(
            blocks,
            key=lambda b: (-b.priority, b.title),
        )

        included: list[ContextBlock] = []
        excluded: list[ContextBlock] = []
        content_parts: list[str] = []
        current_chars = 0

        for block in sorted_blocks:
            # Decide rendering mode
            budget_used_pct = current_chars / self.char_budget if self.char_budget > 0 else 0

            if budget_used_pct >= self.compact_threshold:
                # Use compact rendering
                rendered = block.render_compact()
            else:
                rendered = block.render()

            new_chars = current_chars + len(rendered) + 10  # +10 for spacing

            if new_chars <= self.char_budget:
                content_parts.append(rendered)
                included.append(block)
                current_chars = new_chars
            else:
                # Try compact version if we weren't already using it
                if budget_used_pct < self.compact_threshold:
                    compact = block.render_compact(max_lines=2)
                    if current_chars + len(compact) + 10 <= self.char_budget:
                        content_parts.append(compact)
                        included.append(block)
                        current_chars += len(compact) + 10
                        continue

                # Block doesn't fit
                excluded.append(block)
                logger.debug(
                    "Block excluded from context pack",
                    title=block.title,
                    priority=block.priority,
                    size=block.estimated_chars,
                )

        content = "\n\n".join(content_parts) if content_parts else ""

        result = PackResult(
            content=content,
            included_blocks=included,
            excluded_blocks=excluded,
            total_chars=current_chars,
            budget_used_pct=current_chars / self.char_budget if self.char_budget > 0 else 0,
        )

        logger.debug(
            "Context pack complete",
            included_count=len(included),
            excluded_count=len(excluded),
            chars=current_chars,
            budget_pct=f"{result.budget_used_pct:.1%}",
        )

        return result


def pack_for_stage(
    blocks: list[ContextBlock],
    stage: str,
    *,
    char_budget: int | None = None,
) -> str:
    """Pack blocks for a specific stage with appropriate budget.

    Args:
        blocks: List of context blocks.
        stage: Stage name (affects budget allocation).
        char_budget: Override character budget.

    Returns:
        Packed markdown content.
    """
    # Stage-specific budgets
    if char_budget is None:
        if stage in ("plan", "spec"):
            # Stack-only for planning stages
            char_budget = 3000
        else:
            # Full context for implement/fix
            char_budget = DEFAULT_CHAR_BUDGET

    packer = ContextPacker(char_budget=char_budget)
    result = packer.pack(blocks)
    return result.content
