"""Prompt template renderer using Jinja2."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import jinja2
import structlog

logger = structlog.get_logger()

# Template directory is relative to this module
TEMPLATES_DIR = Path(__file__).parent / "templates"


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
