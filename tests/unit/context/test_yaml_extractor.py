"""Unit tests for robust YAML extraction."""

from __future__ import annotations

import pytest

from orx.context.yaml_extractor import (
    YAMLExtractionError,
    YAMLExtractor,
    safe_extract_yaml,
)


class TestYAMLExtractor:
    """Test cases for YAMLExtractor class."""

    def test_direct_yaml(self) -> None:
        """Test extracting clean YAML."""
        content = """
run_id: "test_123"
items:
  - id: "W001"
    title: "Test"
"""
        extractor = YAMLExtractor()
        result = extractor.extract(content)
        assert result["run_id"] == "test_123"
        assert len(result["items"]) == 1

    def test_markdown_code_fence(self) -> None:
        """Test extracting YAML from markdown code fence."""
        content = """
Here is the YAML:

```yaml
run_id: "test_123"
items: []
```
"""
        extractor = YAMLExtractor()
        result = extractor.extract(content)
        assert result["run_id"] == "test_123"
        assert result["items"] == []

    def test_markdown_fence_without_language(self) -> None:
        """Test extracting YAML from code fence without language marker."""
        content = """
```
run_id: "test_123"
items: []
```
"""
        extractor = YAMLExtractor()
        result = extractor.extract(content)
        assert result["run_id"] == "test_123"

    def test_json_wrapper_response(self) -> None:
        """Test extracting YAML from JSON with 'response' field."""
        content = """
{
  "response": "run_id: \\"test_123\\"\\nitems: []",
  "stats": {}
}
"""
        extractor = YAMLExtractor()
        result = extractor.extract(content)
        assert result["run_id"] == "test_123"

    def test_json_wrapper_nested_dict(self) -> None:
        """Test extracting when JSON contains YAML as dict."""
        content = """
{
  "response": {
    "run_id": "test_123",
    "items": []
  }
}
"""
        extractor = YAMLExtractor()
        result = extractor.extract(content)
        assert result["run_id"] == "test_123"

    def test_yaml_document_markers(self) -> None:
        """Test extracting YAML with document separators."""
        content = """
Some explanatory text here.

---
run_id: "test_123"
items: []
---

More text after.
"""
        extractor = YAMLExtractor()
        result = extractor.extract(content)
        assert result["run_id"] == "test_123"

    def test_yaml_comment_markers(self) -> None:
        """Test extracting YAML with comment markers."""
        content = """
I'll provide the YAML now:

# YAML START
run_id: "test_123"
items: []
# YAML END

That's the corrected version.
"""
        extractor = YAMLExtractor()
        result = extractor.extract(content)
        assert result["run_id"] == "test_123"

    def test_heuristic_extraction(self) -> None:
        """Test heuristic extraction from mixed content."""
        content = """
Let me provide the YAML mapping for you.

run_id: "test_123"
items:
  - id: "W001"
    title: "Test item"

This should work now.
"""
        extractor = YAMLExtractor()
        result = extractor.extract(content)
        assert result["run_id"] == "test_123"
        assert len(result["items"]) == 1

    def test_strict_mode_rejects_heuristic(self) -> None:
        """Test that strict mode only tries direct and fence strategies."""
        content = """
Some text before.

run_id: "test_123"
items: []

Some text after.
"""
        extractor = YAMLExtractor(strict=True)
        with pytest.raises(YAMLExtractionError):
            extractor.extract(content)

    def test_empty_content(self) -> None:
        """Test handling of empty content."""
        extractor = YAMLExtractor()
        with pytest.raises(YAMLExtractionError) as exc_info:
            extractor.extract("")
        assert "Empty content" in str(exc_info.value)

    def test_invalid_yaml_all_strategies(self) -> None:
        """Test that completely invalid content raises error."""
        content = """
This is just plain text with no YAML at all.
No key-value pairs, no structure.
"""
        extractor = YAMLExtractor()
        with pytest.raises(YAMLExtractionError) as exc_info:
            extractor.extract(content)
        assert "Could not extract" in str(exc_info.value)
        # Check content matches (ignoring leading/trailing whitespace)
        assert exc_info.value.original_content.strip() == content.strip()

    def test_non_dict_yaml(self) -> None:
        """Test that YAML list (non-dict) is rejected."""
        content = """
```yaml
- item1
- item2
- item3
```
"""
        extractor = YAMLExtractor()
        with pytest.raises(YAMLExtractionError):
            extractor.extract(content)

    def test_real_world_failure_case(self) -> None:
        """Test extraction from actual failure case."""
        content = """I've read the content of `src/orx/prompts/templates/decompose_fix.md`. This file contains the prompt template used to correct invalid `backlog.yaml` output during the decomposition stage.

How would you like to proceed with this file? I can help you modify the template, debug an issue related to it, or use it as context for another task."""
        extractor = YAMLExtractor()
        with pytest.raises(YAMLExtractionError):
            # This should fail - no YAML here
            extractor.extract(content)

    def test_safe_extract_yaml_none_on_failure(self) -> None:
        """Test that safe_extract_yaml returns None on failure."""
        content = "Not YAML at all"
        result = safe_extract_yaml(content)
        assert result is None

    def test_safe_extract_yaml_success(self) -> None:
        """Test that safe_extract_yaml returns dict on success."""
        content = "run_id: test\nitems: []"
        result = safe_extract_yaml(content)
        assert result is not None
        assert result["run_id"] == "test"

    def test_extract_with_pydantic_validation(self) -> None:
        """Test extraction with Pydantic model validation."""
        from pydantic import BaseModel, Field

        class SimpleBacklog(BaseModel):
            run_id: str = Field(..., min_length=1)
            items: list[dict] = Field(default_factory=list)

        content = """
run_id: "test_123"
items:
  - id: "W001"
"""
        extractor = YAMLExtractor()
        result = extractor.extract_with_validation(content, validator=SimpleBacklog)
        assert result["run_id"] == "test_123"

    def test_extract_with_validation_failure(self) -> None:
        """Test that validation errors are caught."""
        from pydantic import BaseModel, Field

        class StrictBacklog(BaseModel):
            run_id: str = Field(..., min_length=1)
            required_field: str  # This will cause validation to fail

        content = """
run_id: "test_123"
items: []
"""
        extractor = YAMLExtractor()
        with pytest.raises(YAMLExtractionError) as exc_info:
            extractor.extract_with_validation(content, validator=StrictBacklog)
        assert "validation failed" in str(exc_info.value)
