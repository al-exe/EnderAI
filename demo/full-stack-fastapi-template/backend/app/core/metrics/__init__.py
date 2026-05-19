"""Taskforce metrics engine.

Phase 1 exposes only the versioned pricing-catalog lookup. Later phases will
add the event emitters, savings calculators, rollup job, and read queries.
See docs/taskforce-metrics-engine-plan.md.
"""

from app.core.metrics.pricing import pricing_for

__all__ = ["pricing_for"]
