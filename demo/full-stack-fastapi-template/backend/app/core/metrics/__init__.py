"""Taskforce metrics engine.

Phase 1 added the versioned pricing-catalog lookup; Phase 2 adds the
write path (token-count helpers, event emitters, savings calculators).
The read path and frontend land in later phases.
See docs/taskforce-metrics-engine-plan.md.
"""

from app.core.metrics.events import (
    record_document_created,
    record_document_finished,
    record_document_reused,
    record_document_updated,
    record_usage,
)
from app.core.metrics.pricing import pricing_for
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
    "cache_savings",
    "count_details_sections_tokens",
    "count_paragraph_tokens",
    "count_tokens",
    "pricing_for",
    "record_document_created",
    "record_document_finished",
    "record_document_reused",
    "record_document_updated",
    "record_usage",
    "reuse_savings",
    "summary_only_savings",
]
