"""Unit tests for metrics quality analysis."""

from __future__ import annotations

import pytest

from orx.metrics.quality import (
    analyze_backlog_quality,
    analyze_diff_hygiene,
    analyze_pack_relevance,
    analyze_plan_quality,
    analyze_spec_quality,
    combine_quality_metrics,
)
from orx.metrics.schema import DiffStats, QualityMetrics


class TestAnalyzeSpecQuality:
    """Tests for analyze_spec_quality function."""

    def test_good_spec(self) -> None:
        """High quality spec gets high score."""
        spec = """
## Acceptance Criteria

- [ ] Feature X works correctly
- [ ] Tests pass
- [ ] No regressions

## Files to Modify

- src/module.py
- tests/test_module.py

## Schema

```yaml
type: object
properties:
  name: string
```
"""
        qm = analyze_spec_quality(spec)
        assert qm.spec_quality is not None
        assert qm.spec_quality >= 0.7
        assert qm.has_acceptance_criteria is True
        assert qm.has_file_shortlist is True

    def test_minimal_spec(self) -> None:
        """Minimal spec gets lower score."""
        spec = "Do the thing."
        qm = analyze_spec_quality(spec)
        assert qm.spec_quality is not None
        assert qm.spec_quality < 0.5

    def test_spec_with_ac_only(self) -> None:
        """Spec with AC but missing other sections."""
        spec = """
## Acceptance Criteria

- Feature works
- Tests pass
"""
        qm = analyze_spec_quality(spec)
        assert qm.spec_quality is not None
        assert qm.has_acceptance_criteria is True
        # May not have file shortlist
        assert 0.3 <= qm.spec_quality <= 0.7

    def test_empty_spec(self) -> None:
        """Empty spec gets zero score."""
        qm = analyze_spec_quality("")
        assert qm.spec_quality is not None
        assert qm.spec_quality == 0.0


class TestAnalyzePlanQuality:
    """Tests for analyze_plan_quality function."""

    def test_good_plan(self) -> None:
        """Good plan gets high score."""
        plan = """
## Overview

This plan outlines the implementation of feature X.

## Steps

1. Create the module
2. Add tests
3. Update documentation

## Risks

- May impact performance
- Needs careful testing
"""
        qm = analyze_plan_quality(plan)
        assert qm.spec_quality is not None  # Uses spec_quality field
        assert qm.spec_quality >= 0.8

    def test_minimal_plan(self) -> None:
        """Minimal plan gets lower score."""
        plan = "Just do it."
        qm = analyze_plan_quality(plan)
        assert qm.spec_quality is not None
        assert qm.spec_quality < 0.5

    def test_plan_with_steps(self) -> None:
        """Plan with steps section."""
        plan = """
## Steps

1. First step
2. Second step

This is some extra content to make it longer.
"""
        qm = analyze_plan_quality(plan)
        assert qm.spec_quality is not None
        assert qm.spec_quality >= 0.4


class TestAnalyzeDiffHygiene:
    """Tests for analyze_diff_hygiene function."""

    def test_small_clean_diff(self) -> None:
        """Small diff passes hygiene checks."""
        diff_stats = DiffStats(
            files_changed=2,
            lines_added=50,
            lines_removed=10,
        )
        qm = analyze_diff_hygiene(diff_stats, max_files=10, max_loc_added=500, max_loc_removed=200)
        assert qm.diff_within_limits is True

    def test_large_diff(self) -> None:
        """Large diff fails hygiene checks."""
        diff_stats = DiffStats(
            files_changed=60,  # Exceeds max_files=50
            lines_added=100,
            lines_removed=50,
        )
        qm = analyze_diff_hygiene(diff_stats, max_files=50, max_loc_added=500, max_loc_removed=200)
        assert qm.diff_within_limits is False

    def test_diff_exceeds_loc(self) -> None:
        """Diff exceeding LOC limit."""
        diff_stats = DiffStats(
            files_changed=5,
            lines_added=600,  # Exceeds max_loc_added=500
            lines_removed=50,
        )
        qm = analyze_diff_hygiene(diff_stats, max_files=50, max_loc_added=500, max_loc_removed=200)
        assert qm.diff_within_limits is False

    def test_empty_diff(self) -> None:
        """Empty diff passes hygiene checks."""
        diff_stats = DiffStats(
            files_changed=0,
            lines_added=0,
            lines_removed=0,
        )
        qm = analyze_diff_hygiene(diff_stats, max_files=10, max_loc_added=500, max_loc_removed=200)
        assert qm.diff_within_limits is True


class TestAnalyzePackRelevance:
    """Tests for analyze_pack_relevance function."""

    def test_all_relevant(self) -> None:
        """All pack files were modified."""
        pack_files = ["src/a.py", "src/b.py"]
        modified_files = ["src/a.py", "src/b.py", "src/c.py"]

        qm = analyze_pack_relevance(pack_files, modified_files, pack_chars=1000)
        assert qm.pack_signal_ratio is not None
        assert qm.pack_signal_ratio == 1.0

    def test_none_relevant(self) -> None:
        """No pack files were modified."""
        pack_files = ["src/a.py", "src/b.py"]
        modified_files = ["src/c.py", "src/d.py"]

        qm = analyze_pack_relevance(pack_files, modified_files, pack_chars=1000)
        assert qm.pack_signal_ratio is not None
        assert qm.pack_signal_ratio == 0.0

    def test_partial_relevance(self) -> None:
        """Some pack files were modified."""
        pack_files = ["src/a.py", "src/b.py", "src/c.py", "src/d.py"]
        modified_files = ["src/a.py", "src/c.py"]

        qm = analyze_pack_relevance(pack_files, modified_files, pack_chars=1000)
        assert qm.pack_signal_ratio is not None
        assert qm.pack_signal_ratio == 0.5

    def test_empty_pack(self) -> None:
        """Empty pack defaults to 0."""
        qm = analyze_pack_relevance([], ["src/a.py"], pack_chars=0)
        assert qm.pack_signal_ratio is not None
        assert qm.pack_signal_ratio == 0.0
        assert qm.pack_files_count == 0


class TestAnalyzeBacklogQuality:
    """Tests for analyze_backlog_quality function."""

    def test_valid_yaml(self) -> None:
        """Valid YAML backlog."""
        backlog = """
items:
  - id: item-1
    title: First task
    objective: Do the first thing
  - id: item-2
    title: Second task
    objective: Do the second thing
"""
        qm = analyze_backlog_quality(backlog)
        assert qm.schema_valid is True

    def test_invalid_yaml(self) -> None:
        """Invalid YAML gets low score."""
        backlog = "not: valid: yaml: {{"
        qm = analyze_backlog_quality(backlog)
        assert qm.schema_valid is False

    def test_missing_items(self) -> None:
        """YAML without items section."""
        backlog = """
metadata:
  version: 1
"""
        qm = analyze_backlog_quality(backlog)
        assert qm.schema_valid is False


class TestCombineQualityMetrics:
    """Tests for combine_quality_metrics function."""

    def test_combine_two(self) -> None:
        """Combine two metrics."""
        qm1 = QualityMetrics(spec_quality=0.8)
        qm2 = QualityMetrics(has_acceptance_criteria=True)

        combined = combine_quality_metrics(qm1, qm2)
        assert combined.spec_quality == 0.8
        assert combined.has_acceptance_criteria is True

    def test_combine_overlapping(self) -> None:
        """Later values override earlier."""
        qm1 = QualityMetrics(spec_quality=0.5, has_acceptance_criteria=False)
        qm2 = QualityMetrics(spec_quality=0.9)

        combined = combine_quality_metrics(qm1, qm2)
        assert combined.spec_quality == 0.9
        assert combined.has_acceptance_criteria is False

    def test_combine_empty(self) -> None:
        """Combine empty list returns empty metrics."""
        combined = combine_quality_metrics()
        assert combined.spec_quality is None
        assert combined.has_acceptance_criteria is None

    def test_combine_many(self) -> None:
        """Combine many metrics."""
        qm1 = QualityMetrics(spec_quality=0.7)
        qm2 = QualityMetrics(has_acceptance_criteria=True)
        qm3 = QualityMetrics(diff_within_limits=True)
        qm4 = QualityMetrics(pack_signal_ratio=0.6)

        combined = combine_quality_metrics(qm1, qm2, qm3, qm4)
        assert combined.spec_quality == 0.7
        assert combined.has_acceptance_criteria is True
        assert combined.diff_within_limits is True
        assert combined.pack_signal_ratio == 0.6
