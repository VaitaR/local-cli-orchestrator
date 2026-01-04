"""Metrics collection and analysis for orx runs."""

from orx.metrics.aggregator import (
    AggregatedMetrics,
    GateStats,
    MetricsAggregator,
    StageStats,
    rebuild_metrics,
)
from orx.metrics.collector import MetricsCollector, StageTimer
from orx.metrics.quality import (
    analyze_backlog_quality,
    analyze_diff_hygiene,
    analyze_pack_relevance,
    analyze_plan_quality,
    analyze_spec_quality,
    combine_quality_metrics,
)
from orx.metrics.schema import (
    DiffStats,
    GateMetrics,
    QualityMetrics,
    RunMetrics,
    StageMetrics,
)
from orx.metrics.writer import MetricsWriter

__all__ = [
    # Aggregator
    "AggregatedMetrics",
    "GateStats",
    "MetricsAggregator",
    "StageStats",
    "rebuild_metrics",
    # Collector
    "MetricsCollector",
    "StageTimer",
    # Quality
    "analyze_backlog_quality",
    "analyze_diff_hygiene",
    "analyze_pack_relevance",
    "analyze_plan_quality",
    "analyze_spec_quality",
    "combine_quality_metrics",
    # Schema
    "DiffStats",
    "GateMetrics",
    "QualityMetrics",
    "RunMetrics",
    "StageMetrics",
    # Writer
    "MetricsWriter",
]
