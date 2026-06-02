"""Taskforce metrics engine.

Phase 1 added the versioned pricing-catalog lookup; Phase 2 adds the
write path (token-count helpers, event emitters, savings calculators).
The read path and frontend land in later phases.
See docs/taskforce-metrics-engine-plan.md.
"""

from app.core.metrics.events import (
    record_document_consulted,
    record_document_created,
    record_document_finished,
    record_document_reused,
    record_document_updated,
    record_usage,
)
from app.core.metrics.pricing import pricing_for
from app.core.metrics.queries import (
    MetricWindow,
    SavingsBreakdown,
    cross_boundary_reuse_totals,
    daily_series,
    documents_consulted_count,
    documents_touched_count,
    resolve_window,
    reuse_rate,
    savings_breakdown,
    sum_metric_total,
    top_models,
)
from app.core.metrics.registry import (
    REGISTRY,
    MetricDefinition,
    MetricPresentation,
    all_metric_names,
    metric,
    rollup_metric_names,
)
from app.core.metrics.rollup import compute_daily_rollup, rollup_day
from app.core.metrics.savings import (
    cache_savings,
    reuse_savings,
    summary_only_savings,
)
from app.core.metrics.tokens import (
    count_details_sections_tokens,
    count_paragraph_tokens,
    count_tokens,
)

__all__ = [
    "MetricDefinition",
    "MetricPresentation",
    "MetricWindow",
    "REGISTRY",
    "SavingsBreakdown",
    "all_metric_names",
    "cache_savings",
    "compute_daily_rollup",
    "count_details_sections_tokens",
    "count_paragraph_tokens",
    "count_tokens",
    "cross_boundary_reuse_totals",
    "daily_series",
    "documents_consulted_count",
    "documents_touched_count",
    "metric",
    "pricing_for",
    "record_document_consulted",
    "record_document_created",
    "record_document_finished",
    "record_document_reused",
    "record_document_updated",
    "record_usage",
    "resolve_window",
    "reuse_rate",
    "reuse_savings",
    "rollup_day",
    "rollup_metric_names",
    "savings_breakdown",
    "summary_only_savings",
    "sum_metric_total",
    "top_models",
]
