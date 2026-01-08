"""Quality metrics computation for stage outputs."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from orx.metrics.schema import DiffStats, QualityMetrics

if TYPE_CHECKING:
    pass


def analyze_spec_quality(spec_content: str) -> QualityMetrics:
    """Analyze spec content for quality metrics.

    Args:
        spec_content: Content of the spec.md file.

    Returns:
        QualityMetrics with spec-related fields populated.
    """
    # Check for required sections
    has_ac = bool(re.search(r"(?i)(acceptance\s+criteria|## ac\b|## criteria)", spec_content))
    has_files = bool(re.search(r"(?i)(files?\s+hint|files?\s+to\s+modify|target\s+files)", spec_content))

    # Check for schema validity (has headers)
    has_headers = spec_content.count("#") >= 2
    schema_valid = has_headers and len(spec_content) > 100

    # Compute quality score (0-1)
    score = 0.0
    if has_ac:
        score += 0.4
    if has_files:
        score += 0.3
    if schema_valid:
        score += 0.3

    return QualityMetrics(
        spec_quality=round(score, 2),
        has_acceptance_criteria=has_ac,
        has_file_shortlist=has_files,
        schema_valid=schema_valid,
    )


def analyze_plan_quality(plan_content: str) -> QualityMetrics:
    """Analyze plan content for quality metrics.

    Args:
        plan_content: Content of the plan.md file.

    Returns:
        QualityMetrics with plan-related fields populated.
    """
    # Check for required sections
    has_overview = bool(re.search(r"(?i)(overview|summary|goal)", plan_content))
    has_steps = bool(re.search(r"(?i)(steps|approach|phases|tasks)", plan_content))
    has_risks = bool(re.search(r"(?i)(risks|concerns|limitations)", plan_content))

    # Schema validity
    has_headers = plan_content.count("#") >= 2
    schema_valid = has_headers and len(plan_content) > 50

    # Quality score
    score = 0.0
    if has_overview:
        score += 0.3
    if has_steps:
        score += 0.4
    if has_risks:
        score += 0.1
    if schema_valid:
        score += 0.2

    return QualityMetrics(
        spec_quality=round(score, 2),  # Reusing field for plan quality
        schema_valid=schema_valid,
    )


def analyze_diff_hygiene(
    diff_stats: DiffStats,
    *,
    max_files: int = 50,
    max_loc_added: int = 500,
    max_loc_removed: int = 200,
) -> QualityMetrics:
    """Analyze diff statistics for implementation hygiene.

    Args:
        diff_stats: Diff statistics.
        max_files: Maximum files changed threshold.
        max_loc_added: Maximum lines added threshold.
        max_loc_removed: Maximum lines removed threshold.

    Returns:
        QualityMetrics with diff-related fields populated.
    """
    within_limits = (
        diff_stats.files_changed <= max_files
        and diff_stats.lines_added <= max_loc_added
        and diff_stats.lines_removed <= max_loc_removed
    )

    return QualityMetrics(
        diff_within_limits=within_limits,
    )


def analyze_pack_relevance(
    pack_files: list[str],
    changed_files: list[str],
    pack_chars: int,
) -> QualityMetrics:
    """Analyze context pack relevance.

    Args:
        pack_files: List of files included in context pack.
        changed_files: List of files that were actually modified.
        pack_chars: Total character count of the pack.

    Returns:
        QualityMetrics with pack-related fields populated.
    """
    if not pack_files:
        return QualityMetrics(
            pack_files_count=0,
            pack_chars=pack_chars,
            pack_signal_ratio=0.0,
        )

    # Compute signal ratio: how many pack files were actually modified
    pack_set = set(pack_files)
    changed_set = set(changed_files)
    overlap = len(pack_set & changed_set)
    signal_ratio = overlap / len(pack_files) if pack_files else 0.0

    return QualityMetrics(
        pack_files_count=len(pack_files),
        pack_chars=pack_chars,
        pack_signal_ratio=round(signal_ratio, 2),
    )


def analyze_backlog_quality(backlog_content: str) -> QualityMetrics:
    """Analyze backlog YAML for quality.

    Args:
        backlog_content: Content of backlog.yaml.

    Returns:
        QualityMetrics with backlog-related fields.
    """
    import yaml

    try:
        data = yaml.safe_load(backlog_content)
        if not isinstance(data, dict):
            return QualityMetrics(schema_valid=False)

        items = data.get("items", [])
        if not items:
            return QualityMetrics(schema_valid=False)

        # Check required fields in items
        valid_items = 0
        for item in items:
            if isinstance(item, dict):
                has_id = "id" in item
                has_title = "title" in item
                has_objective = "objective" in item
                if has_id and has_title and has_objective:
                    valid_items += 1

        schema_valid = valid_items == len(items) and len(items) > 0

        return QualityMetrics(schema_valid=schema_valid)

    except yaml.YAMLError:
        return QualityMetrics(schema_valid=False)


def combine_quality_metrics(*metrics: QualityMetrics | None) -> QualityMetrics:
    """Combine multiple quality metrics into one.

    Takes non-None values from each input, later inputs override earlier.

    Args:
        *metrics: QualityMetrics objects to combine.

    Returns:
        Combined QualityMetrics.
    """
    result = QualityMetrics()

    for m in metrics:
        if m is None:
            continue
        for field in m.model_fields:
            value = getattr(m, field)
            if value is not None:
                setattr(result, field, value)

    return result
