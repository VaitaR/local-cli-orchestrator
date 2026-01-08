"""Verify commands builder - renders gate commands for prompts.

This module creates a context block showing what commands orx will run
during the VERIFY stage, so the agent knows exactly what checks to expect.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from orx.context.repo_context.blocks import ContextBlock, ContextPriority

if TYPE_CHECKING:
    from orx.gates.base import Gate


def build_verify_commands(gates: list["Gate"]) -> ContextBlock | None:
    """Build a context block describing verify commands.

    Args:
        gates: List of Gate instances that will run during VERIFY.

    Returns:
        ContextBlock with verify command descriptions, or None if no gates.
    """
    if not gates:
        return None

    lines: list[str] = []

    for gate in gates:
        name = gate.name

        # Try to get the full command rendering from gate first
        if hasattr(gate, "render_command"):
            full_cmd = gate.render_command()  # type: ignore[no-any-return]
        else:
            # Fallback: build from command and args attributes
            command = getattr(gate, "command", name)
            args = getattr(gate, "args", [])

            if args:
                full_cmd = f"{command} {' '.join(args)}"
            else:
                full_cmd = str(command)

        # Truncate long commands
        if len(full_cmd) > 80:
            full_cmd = full_cmd[:77] + "..."

        required = getattr(gate, "required", True)
        req_marker = "(required)" if required else "(optional)"
        lines.append(f"- **{name}** {req_marker}: `{full_cmd}`")

    body = "\n".join(lines)

    return ContextBlock(
        priority=ContextPriority.VERIFY_COMMANDS,
        title="VERIFY Will Run",
        body=body,
        sources=[],  # No file source - derived from config
        category="gates",
    )


def render_verify_commands_markdown(gates: list["Gate"]) -> str:
    """Render verify commands as standalone markdown.

    Args:
        gates: List of Gate instances.

    Returns:
        Markdown string with verify command list.
    """
    block = build_verify_commands(gates)
    if not block:
        return ""
    return block.render(include_sources=False)
