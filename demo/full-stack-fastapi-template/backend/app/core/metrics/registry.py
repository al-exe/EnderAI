"""Metric definitions registry.

Code-defined (not table-driven) per plan §4.4. Adding a new metric is one
PR: append a ``MetricDefinition`` here and the rollup job + read endpoints
pick it up automatically because they iterate this registry. The frontend
self-describes via ``GET /v2/metrics/definitions``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.models import (
    METRICS_EVENT_DOCUMENT_CONSULTED,
    METRICS_EVENT_DOCUMENT_CREATED,
    METRICS_EVENT_DOCUMENT_FINISHED,
    METRICS_EVENT_DOCUMENT_REUSED,
    METRICS_EVENT_DOCUMENT_UPDATED,
    METRICS_EVENT_TOKENS_CONSUMED,
    METRICS_EVENT_TOKENS_SAVED_CACHE,
    METRICS_EVENT_TOKENS_SAVED_REUSE,
    METRICS_EVENT_TOKENS_SAVED_SUMMARY_ONLY,
)

MetricUnit = Literal["tokens", "usd", "count", "ratio"]
MetricFormat = Literal["compact-int", "usd", "ratio", "count"]

TOKENS_SAVED_KINDS = (
    METRICS_EVENT_TOKENS_SAVED_CACHE,
    METRICS_EVENT_TOKENS_SAVED_REUSE,
    METRICS_EVENT_TOKENS_SAVED_SUMMARY_ONLY,
)

REUSE_RATE_NUM_KINDS = (METRICS_EVENT_DOCUMENT_REUSED,)
REUSE_RATE_DEN_KINDS = (
    METRICS_EVENT_DOCUMENT_REUSED,
    METRICS_EVENT_DOCUMENT_CREATED,
)


@dataclass(frozen=True)
class MetricPresentation:
    format: MetricFormat = "compact-int"
    trend: bool = True
    icon: str | None = None


@dataclass(frozen=True)
class MetricDefinition:
    """Describes one metric end-to-end.

    Fields are read by:
      * the rollup job (``kinds``, ``field_name``)
      * the read endpoint (``unit``, ``presentation``, ``description``)
      * the frontend (everything that's part of the public envelope)
    """

    name: str
    display_name: str
    unit: MetricUnit
    description: str
    # Event kinds that contribute to this metric. Empty for composed
    # metrics that are derived at read time (e.g. ``reuse_rate``).
    kinds: tuple[str, ...] = ()
    # Which numeric column to sum when aggregating. None for ratio /
    # count-distinct metrics that need bespoke SQL.
    field_name: (
        Literal["input_tokens", "output_tokens", "cache_read_tokens", "usd_amount"]
        | None
    ) = None
    presentation: MetricPresentation = field(default_factory=MetricPresentation)
    # ``True`` for ratio metrics that compose two underlying aggregations
    # rather than mapping to a single rollup row.
    composed: bool = False


REGISTRY: dict[str, MetricDefinition] = {
    "tokens_saved": MetricDefinition(
        name="tokens_saved",
        display_name="Tokens Saved",
        unit="tokens",
        description=(
            "Estimated tokens not sent to the model thanks to Taskforce. Combines "
            "cache reads, Summary-instead-of-Details consultations, and reuse-on-begin."
        ),
        kinds=TOKENS_SAVED_KINDS,
        field_name="input_tokens",
        presentation=MetricPresentation(format="compact-int", icon="spark"),
    ),
    "usd_saved": MetricDefinition(
        name="usd_saved",
        display_name="USD Saved",
        unit="usd",
        description=(
            "Dollar value of tokens saved, priced at the model rates effective when "
            "each event occurred. Historical figures stay reproducible across price changes."
        ),
        kinds=TOKENS_SAVED_KINDS,
        field_name="usd_amount",
        presentation=MetricPresentation(format="usd", icon="dollar"),
    ),
    "tokens_consumed": MetricDefinition(
        name="tokens_consumed",
        display_name="Tokens Used",
        unit="tokens",
        description="Total input + output tokens consumed across Taskforce-mediated turns.",
        kinds=(METRICS_EVENT_TOKENS_CONSUMED,),
        field_name="input_tokens",
    ),
    "usd_consumed": MetricDefinition(
        name="usd_consumed",
        display_name="USD Spent",
        unit="usd",
        description="Dollar cost of Taskforce-mediated turns, priced per the pricing snapshot at event time.",
        kinds=(METRICS_EVENT_TOKENS_CONSUMED,),
        field_name="usd_amount",
        presentation=MetricPresentation(format="usd"),
    ),
    "documents_touched": MetricDefinition(
        name="documents_touched",
        display_name="Documents Touched",
        unit="count",
        description="Distinct V2 documents the agent created, reused, updated, or finished in the window.",
        kinds=(
            METRICS_EVENT_DOCUMENT_CREATED,
            METRICS_EVENT_DOCUMENT_UPDATED,
            METRICS_EVENT_DOCUMENT_REUSED,
            METRICS_EVENT_DOCUMENT_FINISHED,
        ),
        composed=True,
        presentation=MetricPresentation(format="count"),
    ),
    "reuse_rate": MetricDefinition(
        name="reuse_rate",
        display_name="Reuse Rate",
        unit="ratio",
        description=(
            "Share of begin-document calls that reused an existing V2 document instead of "
            "creating a fresh one. Higher = the scoring engine is finding good matches."
        ),
        composed=True,
        presentation=MetricPresentation(format="ratio"),
    ),
    "documents_consulted": MetricDefinition(
        name="documents_consulted",
        display_name="Documents Consulted",
        unit="count",
        description=(
            "Distinct V2 documents the Taskforce hooks surfaced to the agent in the window. "
            "Each match returned by POST /v2/taskforce/discover counts once; the discover "
            "endpoint is fired automatically by the UserPromptSubmit hook (TF-176)."
        ),
        kinds=(METRICS_EVENT_DOCUMENT_CONSULTED,),
        composed=True,
        presentation=MetricPresentation(format="count"),
    ),
}


def metric(name: str) -> MetricDefinition:
    """Return the registry entry for ``name`` or raise KeyError."""

    return REGISTRY[name]


def all_metric_names() -> list[str]:
    return list(REGISTRY.keys())


def rollup_metric_names() -> list[str]:
    """Names of metrics that the rollup job materializes directly.

    Composed metrics aren't rolled up because they're computed at read
    time from the underlying counts.
    """

    return [name for name, defn in REGISTRY.items() if not defn.composed]
