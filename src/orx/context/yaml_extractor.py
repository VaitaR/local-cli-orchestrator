"""Robust YAML extraction from LLM responses.

This module provides a multi-layer approach to extracting valid YAML from
potentially noisy LLM outputs. It handles common failure modes:
- YAML wrapped in markdown code fences
- YAML preceded/followed by explanatory text
- JSON wrapper with 'response' field containing YAML
- Mixed content with YAML blocks embedded in prose
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog
import yaml

logger = structlog.get_logger()


class YAMLExtractionError(Exception):
    """Raised when YAML cannot be extracted from response."""

    def __init__(self, message: str, *, original_content: str) -> None:
        """Initialize the error.

        Args:
            message: Error message.
            original_content: The original content that failed extraction.
        """
        super().__init__(message)
        self.original_content = original_content


class YAMLExtractor:
    """Multi-strategy YAML extractor with fallbacks.

    Strategies (tried in order):
    1. Direct YAML parse (content is already clean YAML)
    2. Strip markdown code fences (```yaml...```)
    3. Extract from JSON wrapper ({'response': '...'})
    4. Find YAML block markers (---...--- or # YAML START/END)
    5. Heuristic extraction (find first valid YAML mapping in text)
    6. Template-based reconstruction (last resort, requires schema)
    """

    def __init__(self, *, strict: bool = False) -> None:
        """Initialize the extractor.

        Args:
            strict: If True, only try the first two strategies (direct + fence).
        """
        self.strict = strict

    def extract(self, content: str) -> dict[str, Any]:
        """Extract YAML mapping from potentially noisy content.

        Args:
            content: Raw content from LLM.

        Returns:
            Parsed YAML as dictionary.

        Raises:
            YAMLExtractionError: If no valid YAML can be extracted.
        """
        content = content.strip()
        if not content:
            raise YAMLExtractionError("Empty content", original_content=content)

        strategies = [
            ("direct", self._try_direct),
            ("markdown_fence", self._try_markdown_fence),
        ]

        if not self.strict:
            strategies.extend(
                [
                    ("json_wrapper", self._try_json_wrapper),
                    ("yaml_markers", self._try_yaml_markers),
                    ("heuristic", self._try_heuristic),
                ]
            )

        for strategy_name, strategy_func in strategies:
            try:
                result = strategy_func(content)
                if result is not None:
                    logger.debug(
                        "YAML extraction succeeded",
                        strategy=strategy_name,
                        preview=str(result)[:200],
                    )
                    return result
            except Exception as e:
                logger.debug(
                    "YAML extraction strategy failed",
                    strategy=strategy_name,
                    error=str(e),
                )
                continue

        # All strategies failed
        preview = content[:500] if len(content) > 500 else content
        raise YAMLExtractionError(
            f"Could not extract valid YAML mapping using any strategy. "
            f"Content preview: {preview}",
            original_content=content,
        )

    def _try_direct(self, content: str) -> dict[str, Any] | None:
        """Try parsing content directly as YAML.
        
        Note: Skips if content looks like JSON (starts with {) since
        JSON is valid YAML but we want to try JSON extraction strategies first.
        """
        # Skip if content looks like JSON wrapper
        stripped = content.strip()
        if stripped.startswith("{") and '"response"' in stripped[:300]:
            return None
            
        try:
            data = yaml.safe_load(content)
            if isinstance(data, dict):
                return data
        except yaml.YAMLError:
            pass
        return None

    def _try_markdown_fence(self, content: str) -> dict[str, Any] | None:
        """Try extracting YAML from markdown code fence."""
        # Pattern: ```yaml (optional) ... ```
        fence_pattern = r"```(?:yaml|yml)?\s*\n(.*?)\n```"
        match = re.search(fence_pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            yaml_content = match.group(1).strip()
            try:
                data = yaml.safe_load(yaml_content)
                if isinstance(data, dict):
                    return data
            except yaml.YAMLError:
                pass
        return None

    def _try_json_wrapper(self, content: str) -> dict[str, Any] | None:
        """Try extracting YAML from JSON wrapper with 'response' field."""
        try:
            # First try: parse as JSON
            json_data = json.loads(content)
            if isinstance(json_data, dict):
                # Look for common wrapper fields
                for field in ["response", "yaml", "content", "result"]:
                    if field in json_data:
                        yaml_str = json_data[field]
                        if isinstance(yaml_str, str):
                            # Parse the extracted string as YAML
                            data = yaml.safe_load(yaml_str)
                            if isinstance(data, dict):
                                return data
                        elif isinstance(yaml_str, dict):
                            # Already a dict, return it
                            return yaml_str
        except (json.JSONDecodeError, yaml.YAMLError):
            pass
        return None

    def _try_yaml_markers(self, content: str) -> dict[str, Any] | None:
        """Try extracting YAML between explicit markers."""
        # Pattern 1: YAML document separators (---)
        doc_pattern = r"---\s*\n(.*?)\n(?:---|\.\.\.)"
        match = re.search(doc_pattern, content, re.DOTALL)
        if match:
            yaml_content = match.group(1).strip()
            try:
                data = yaml.safe_load(yaml_content)
                if isinstance(data, dict):
                    return data
            except yaml.YAMLError:
                pass

        # Pattern 2: Comment markers (# YAML START / # YAML END)
        comment_pattern = r"#\s*YAML\s*START\s*\n(.*?)\n#\s*YAML\s*END"
        match = re.search(comment_pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            yaml_content = match.group(1).strip()
            try:
                data = yaml.safe_load(yaml_content)
                if isinstance(data, dict):
                    return data
            except yaml.YAMLError:
                pass

        return None

    def _try_heuristic(self, content: str) -> dict[str, Any] | None:
        """Try heuristic extraction: find first valid YAML mapping.
        
        Strategy: Find the first line that looks like a YAML key, then
        keep adding lines until we either find a complete valid YAML block
        or hit a line that breaks the YAML structure.
        """
        lines = content.splitlines()

        # Look for lines that start a YAML mapping (key:)
        yaml_key_pattern = re.compile(r"^\s*[\w_]+\s*:")

        # Find potential YAML start
        start_idx = None
        for i, line in enumerate(lines):
            if yaml_key_pattern.match(line):
                start_idx = i
                break

        if start_idx is None:
            return None

        # Heuristic: Find where YAML block likely ends
        # YAML ends when we hit:
        # - Empty line followed by non-indented text
        # - Line that doesn't look like YAML (no colon, no dash, no indentation)
        end_idx = start_idx + 1
        last_valid_data = None
        last_valid_end = start_idx + 1

        for i in range(start_idx + 1, len(lines)):
            candidate = "\n".join(lines[start_idx : i + 1])
            try:
                data = yaml.safe_load(candidate)
                if isinstance(data, dict) and data:
                    # Valid YAML so far
                    last_valid_data = data
                    last_valid_end = i + 1
            except yaml.YAMLError:
                # This line broke YAML, stop here
                break

            # Stop if we hit a line that looks like prose (not YAML)
            line = lines[i].strip()
            if line and not re.match(r"^[\w_]+\s*:|^-\s|^\s+", lines[i]):
                # Non-YAML line (no key:, no list item, no indentation)
                break

        return last_valid_data

    def extract_with_validation(
        self, content: str, *, validator: type[Any] | None = None
    ) -> dict[str, Any]:
        """Extract YAML and optionally validate against Pydantic model.

        Args:
            content: Raw content from LLM.
            validator: Optional Pydantic model class for validation.

        Returns:
            Parsed and validated YAML as dictionary.

        Raises:
            YAMLExtractionError: If extraction or validation fails.
        """
        data = self.extract(content)

        if validator is not None:
            try:
                # Validate using Pydantic
                validator.model_validate(data)
            except Exception as e:
                raise YAMLExtractionError(
                    f"YAML validation failed: {e}", original_content=content
                ) from e

        return data


def safe_extract_yaml(
    content: str, *, strict: bool = False, validator: type[Any] | None = None
) -> dict[str, Any] | None:
    """Convenience function for YAML extraction with error handling.

    Args:
        content: Raw content from LLM.
        strict: If True, only try direct and fence strategies.
        validator: Optional Pydantic model class for validation.

    Returns:
        Parsed YAML dict, or None if extraction fails.
    """
    extractor = YAMLExtractor(strict=strict)
    try:
        if validator:
            return extractor.extract_with_validation(content, validator=validator)
        return extractor.extract(content)
    except YAMLExtractionError as e:
        logger.error("YAML extraction failed", error=str(e))
        return None
