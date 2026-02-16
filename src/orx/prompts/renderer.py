"""Prompt template renderer using Jinja2."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jinja2
import structlog

logger = structlog.get_logger()

# Template directory is relative to this module
TEMPLATES_DIR = Path(__file__).parent / "templates"

# Context keys that contain static (cacheable) content.
# These do not change between stages within a single run.
STATIC_CONTEXT_KEYS = frozenset(
    {
        "agents_context",
        "architecture_overview",
        "architecture",
        "project_context",
        "repo_context",
        "repo_tags",
        "smart_context",
        "verify_commands",
        "definition_of_done",
    }
)


@dataclass
class RenderedPrompt:
    """A rendered prompt with optional system/user split for caching.

    When context caching is enabled, the prompt is split into:
    - system_prompt_path: Static context (AGENTS.md, ARCHITECTURE.md, etc.)
    - prompt_path: Dynamic, stage-specific content only

    Executors that support system prompts (e.g. Claude Code via
    ``--system-prompt``) use both files. Others prepend the system
    content to the main prompt for prefix-caching benefits.
    """

    prompt_path: Path
    system_prompt_path: Path | None = None


class PromptRenderer:
    """Renders prompt templates with context.

    Uses Jinja2 for template rendering with a custom loader that
    looks for templates in the templates directory.

    Example:
        >>> renderer = PromptRenderer()
        >>> content = renderer.render("plan", task="Build a CLI tool")
        >>> "Build a CLI tool" in content
        True
    """

    def __init__(self, templates_dir: Path | None = None) -> None:
        """Initialize the renderer.

        Args:
            templates_dir: Directory containing templates.
                          Defaults to built-in templates.
        """
        self.templates_dir = templates_dir or TEMPLATES_DIR
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(self.templates_dir)),
            autoescape=False,  # We're generating markdown, not HTML
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=jinja2.StrictUndefined,
        )

    def render(self, template_name: str, **context: Any) -> str:
        """Render a template with the given context.

        Args:
            template_name: Name of the template (without .md extension).
            **context: Variables to pass to the template.

        Returns:
            Rendered template content.

        Raises:
            jinja2.TemplateNotFound: If template doesn't exist.
            jinja2.UndefinedError: If required variable is missing.
        """
        log = logger.bind(template=template_name)
        log.debug("Rendering prompt template")

        template_file = f"{template_name}.md"
        template = self.env.get_template(template_file)
        rendered = template.render(**context)

        log.debug("Template rendered", length=len(rendered))
        return rendered

    def render_to_file(
        self,
        template_name: str,
        out_path: Path,
        **context: Any,
    ) -> None:
        """Render a template and write to file.

        Args:
            template_name: Name of the template.
            out_path: Path to write the rendered content.
            **context: Variables to pass to the template.
        """
        content = self.render(template_name, **context)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content)
        logger.debug("Wrote prompt to file", path=str(out_path))

    def render_with_context_split(
        self,
        template_name: str,
        out_dir: Path,
        **context: Any,
    ) -> RenderedPrompt:
        """Render a template with static/dynamic split for context caching.

        Static context (AGENTS.md, ARCHITECTURE.md, repo context, etc.) is
        rendered to a separate ``<name>_system.md`` file.  The stage template
        is rendered *without* those variables so it contains only the dynamic,
        per-stage content.

        Executors that support a dedicated system-prompt field (Claude Code)
        will pass the two files separately.  Others prepend the system content
        to the main prompt to benefit from prefix caching.

        Args:
            template_name: Name of the template (without .md extension).
            out_dir: Directory to write prompt files.
            **context: Variables to pass to the template.

        Returns:
            RenderedPrompt with paths to both files.
        """
        log = logger.bind(template=template_name)
        log.debug("Rendering prompt with context split")

        # Separate static vs. dynamic context
        static_ctx = {k: v for k, v in context.items() if k in STATIC_CONTEXT_KEYS and v}
        dynamic_ctx = {k: v for k, v in context.items() if k not in STATIC_CONTEXT_KEYS}

        out_dir.mkdir(parents=True, exist_ok=True)

        # Render system (static) context
        system_path: Path | None = None
        if static_ctx and self.template_exists("system_context"):
            system_path = out_dir / f"{template_name}_system.md"
            system_content = self.render("system_context", **static_ctx)
            system_path.write_text(system_content)
            log.debug(
                "System context rendered",
                path=str(system_path),
                length=len(system_content),
            )

        # Render main prompt with only dynamic context
        prompt_path = out_dir / f"{template_name}.md"
        main_content = self.render(template_name, **dynamic_ctx)
        prompt_path.write_text(main_content)
        log.debug("Dynamic prompt rendered", path=str(prompt_path), length=len(main_content))

        return RenderedPrompt(prompt_path=prompt_path, system_prompt_path=system_path)

    def list_templates(self) -> list[str]:
        """List available template names.

        Returns:
            List of template names (without .md extension).
        """
        templates = []
        if self.templates_dir.exists():
            for path in self.templates_dir.glob("*.md"):
                templates.append(path.stem)
        return sorted(templates)

    def template_exists(self, template_name: str) -> bool:
        """Check if a template exists.

        Args:
            template_name: Name of the template.

        Returns:
            True if template exists.
        """
        template_file = self.templates_dir / f"{template_name}.md"
        return template_file.exists()


# Convenience function for simple rendering
def render_prompt(template_name: str, **context: Any) -> str:
    """Render a prompt template.

    Args:
        template_name: Name of the template.
        **context: Variables to pass to the template.

    Returns:
        Rendered template content.
    """
    renderer = PromptRenderer()
    return renderer.render(template_name, **context)
