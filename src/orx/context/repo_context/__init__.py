"""Repo Context Pack - automatic context extraction from target repositories.

This module provides automatic extraction of stack, tooling, and configuration
information from target repositories to include in prompts.

Key components:
- ContextBlock: Unit of context with priority and budget tracking
- ContextPacker: Assembles blocks within token budget
- Extractors: Language-specific config parsers (Python, TypeScript)
- build_verify_commands: Renders gate commands as markdown
- RepoContextBuilder: Main entry point that coordinates extraction
"""

from orx.context.repo_context.blocks import ContextBlock, ContextPriority
from orx.context.repo_context.builder import RepoContextBuilder
from orx.context.repo_context.packer import ContextPacker
from orx.context.repo_context.python_extractor import PythonExtractor
from orx.context.repo_context.ts_extractor import TypeScriptExtractor
from orx.context.repo_context.verify_commands import build_verify_commands

__all__ = [
    "ContextBlock",
    "ContextPacker",
    "ContextPriority",
    "PythonExtractor",
    "RepoContextBuilder",
    "TypeScriptExtractor",
    "build_verify_commands",
]
