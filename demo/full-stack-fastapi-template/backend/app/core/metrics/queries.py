"""Read-side aggregations.

These helpers turn raw ``metrics_event`` rows (or the cached
``metrics_daily_rollup``) into the shapes the read endpoint and frontend
care about. Each query is owner-scoped and honours the demo flag —
plan §11 Q5 demands strict isolation between live and demo data.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.core.metrics.registry import (
    REGISTRY,
    REUSE_RATE_DEN_KINDS,
    REUSE_RATE_NUM_KINDS,
    TOKENS_SAVED_KINDS,
    MetricDefinition,
)
from app.models import (
    METRICS_EVENT_DOCUMENT_CONSULTED,
    METRICS_EVENT_TOKENS_CONSUMED,
    METRICS_EVENT_TOKENS_SAVED_CACHE,
    METRICS_EVENT_TOKENS_SAVED_REUSE,
    METRICS_EVENT_TOKENS_SAVED_SUMMARY_ONLY,
    AgentSpecialist,
    MetricsEvent,
)

WindowName = Literal["7d", "30d", "all"]


@dataclass(frozen=True)
class MetricWindow:
    name: WindowName
    start: datetime | None  # None = all-time
    end: datetime

    def previous(self) -> MetricWindow | None:
        """The same-sized window immediately before this one, for delta math."""
        if self.start is None:
            return None
        span = self.end - self.start
        return MetricWindow(name=self.name, start=self.start - span, end=self.start)


def resolve_window(name: WindowName, now: datetime | None = None) -> MetricWindow:
    end = now or datetime.now(timezone.utc)
    if name == "7d":
        return MetricWindow(name=name, start=end - timedelta(days=7), end=end)
    if name == "30d":
        return MetricWindow(name=name, start=end - timedelta(days=30), end=end)
    return MetricWindow(name="all", start=None, end=end)


def _apply_scope(
    statement: Any,
    *,
    user_id: uuid.UUID,
    is_demo: bool,
    window: MetricWindow,
) -> Any:
    statement = statement.where(MetricsEvent.user_id == user_id)
    statement = statement.where(MetricsEvent.is_demo == is_demo)
    if window.start is not None:
        statement = statement.where(col(MetricsEvent.occurred_at) >= window.start)
    statement = statement.where(col(MetricsEvent.occurred_at) < window.end)
    return statement


def sum_metric_total(
    session: Session,
    *,
    user_id: uuid.UUID,
    is_demo: bool,
    window: MetricWindow,
    definition: MetricDefinition,
) -> Decimal:
    """Sum the configured field across events of the registered kinds.

    Returns 0 (Decimal) when no rows match. Always returns Decimal so
    callers don't have to think about None / int / float interleaving.
    """

    if definition.composed:
        # Composed metrics have dedicated computers below; this helper
        # is only for the direct-field case.
        return Decimal(0)
    if not definition.kinds or definition.field_name is None:
        return Decimal(0)

    column = getattr(MetricsEvent, definition.field_name)
    statement = select(func.coalesce(func.sum(column), 0)).where(
        col(MetricsEvent.kind).in_(definition.kinds)
    )
    statement = _apply_scope(statement, user_id=user_id, is_demo=is_demo, window=window)
    result = session.exec(statement).first()
    if result is None:
        return Decimal(0)
    return Decimal(str(result))


def _distinct_documents_for_kinds(
    session: Session,
    *,
    user_id: uuid.UUID,
    is_demo: bool,
    window: MetricWindow,
    kinds: tuple[str, ...],
) -> int:
    """Count distinct ``document_id`` values across the given event kinds.

    Backs both ``documents_touched`` (across the four document.* lifecycle
    kinds) and ``documents_consulted`` (just ``document.consulted``).
    """

    if not kinds:
        return 0
    statement = select(func.count(func.distinct(MetricsEvent.document_id))).where(
        col(MetricsEvent.kind).in_(kinds)
    )
    statement = _apply_scope(statement, user_id=user_id, is_demo=is_demo, window=window)
    statement = statement.where(col(MetricsEvent.document_id).is_not(None))
    result = session.exec(statement).first()
    return int(result or 0)


def documents_touched_count(
    session: Session,
    *,
    user_id: uuid.UUID,
    is_demo: bool,
    window: MetricWindow,
) -> int:
    """Distinct document_ids across the four document.* kinds in the window."""

    return _distinct_documents_for_kinds(
        session,
        user_id=user_id,
        is_demo=is_demo,
        window=window,
        kinds=REGISTRY["documents_touched"].kinds,
    )


def documents_consulted_count(
    session: Session,
    *,
    user_id: uuid.UUID,
    is_demo: bool,
    window: MetricWindow,
) -> int:
    """Distinct document_ids touched by ``document.consulted`` events.

    Backs the ``documents_consulted`` metric (TF-175).
    """

    return _distinct_documents_for_kinds(
        session,
        user_id=user_id,
        is_demo=is_demo,
        window=window,
        kinds=REGISTRY["documents_consulted"].kinds,
    )


def reuse_rate(
    session: Session,
    *,
    user_id: uuid.UUID,
    is_demo: bool,
    window: MetricWindow,
) -> Decimal:
    """``document.reused`` / (``document.reused`` + ``document.created``)
    within the window. Returns 0 when there were no begin-document calls."""

    statement = select(MetricsEvent.kind, func.count()).where(
        col(MetricsEvent.kind).in_(REUSE_RATE_DEN_KINDS)
    )
    statement = _apply_scope(statement, user_id=user_id, is_demo=is_demo, window=window)
    statement = statement.group_by(MetricsEvent.kind)
    counts: dict[str, int] = {row[0]: row[1] for row in session.exec(statement)}
    reused = sum(counts.get(k, 0) for k in REUSE_RATE_NUM_KINDS)
    total = sum(counts.values())
    if total == 0:
        return Decimal(0)
    return (Decimal(reused) / Decimal(total)).quantize(Decimal("0.0001"))


@dataclass(frozen=True)
class SavingsBreakdown:
    cache: Decimal
    summary_only: Decimal
    reuse: Decimal

    @property
    def total(self) -> Decimal:
        return self.cache + self.summary_only + self.reuse


def savings_breakdown(
    session: Session,
    *,
    user_id: uuid.UUID,
    is_demo: bool,
    window: MetricWindow,
    field: Literal["input_tokens", "usd_amount"] = "input_tokens",
) -> SavingsBreakdown:
    """Per-source breakdown of savings within the window."""

    column = getattr(MetricsEvent, field)
    statement = select(MetricsEvent.kind, func.coalesce(func.sum(column), 0)).where(
        col(MetricsEvent.kind).in_(TOKENS_SAVED_KINDS)
    )
    statement = _apply_scope(statement, user_id=user_id, is_demo=is_demo, window=window)
    statement = statement.group_by(MetricsEvent.kind)
    sums: dict[str, Decimal] = {}
    for kind, total in session.exec(statement):
        sums[kind] = Decimal(str(total or 0))
    return SavingsBreakdown(
        cache=sums.get(METRICS_EVENT_TOKENS_SAVED_CACHE, Decimal(0)),
        summary_only=sums.get(METRICS_EVENT_TOKENS_SAVED_SUMMARY_ONLY, Decimal(0)),
        reuse=sums.get(METRICS_EVENT_TOKENS_SAVED_REUSE, Decimal(0)),
    )


@dataclass(frozen=True)
class TaskforceSessionSavings:
    session_id: str
    doc_count: int
    net_saved_tokens: int
    usd_saved: Decimal
    pricing_model_id: str | None
    occurred_at_first: datetime | None
    occurred_at_last: datetime | None
    specialist_slug: str | None
    specialist_name: str | None


def taskforce_session_savings(
    session: Session,
    *,
    user_id: uuid.UUID,
    session_id: str,
    pricing_model_id: str | None = None,
) -> TaskforceSessionSavings:
    """Aggregate savings from ``document.consulted`` events for one session."""

    statement = (
        select(
            func.count(func.distinct(MetricsEvent.document_id)),
            func.coalesce(func.sum(MetricsEvent.input_tokens), 0),
            func.coalesce(func.sum(MetricsEvent.usd_amount), 0),
            func.min(MetricsEvent.occurred_at),
            func.max(MetricsEvent.occurred_at),
        )
        .where(MetricsEvent.kind == METRICS_EVENT_DOCUMENT_CONSULTED)
        .where(MetricsEvent.user_id == user_id)
        .where(MetricsEvent.payload["session_id"].astext == session_id)  # type: ignore[index]
    )
    doc_count, net_saved_tokens, usd_saved, occurred_at_first, occurred_at_last = (
        session.exec(statement).one()
    )

    # One specialist per session (routing happens once at session/start), so
    # we read the slug off the first consult event and resolve the display
    # name from agent_specialist. The slug stays the source of truth for
    # deep-linking — name is null when the specialist was deleted between
    # the session and the metrics view.
    specialist_slug: str | None = session.exec(
        select(MetricsEvent.payload["specialist_slug"].astext)  # type: ignore[index]
        .where(MetricsEvent.kind == METRICS_EVENT_DOCUMENT_CONSULTED)
        .where(MetricsEvent.user_id == user_id)
        .where(MetricsEvent.payload["session_id"].astext == session_id)  # type: ignore[index]
        .where(MetricsEvent.payload["specialist_slug"].astext.isnot(None))  # type: ignore[index]
        .limit(1)
    ).first()
    specialist_name: str | None = None
    if specialist_slug:
        specialist_name = session.exec(
            select(AgentSpecialist.name).where(AgentSpecialist.slug == specialist_slug)
        ).first()

    usd = Decimal(str(usd_saved or 0))
    if pricing_model_id and occurred_at_last is not None:
        from app.core.metrics.pricing import pricing_for

        pricing = pricing_for(session, pricing_model_id, occurred_at_last)
        if pricing is not None and pricing.input_per_mtok is not None:
            usd = (
                Decimal(int(net_saved_tokens or 0)) / Decimal(1_000_000)
            ) * pricing.input_per_mtok
        else:
            usd = Decimal(0)

    return TaskforceSessionSavings(
        session_id=session_id,
        doc_count=int(doc_count or 0),
        net_saved_tokens=int(net_saved_tokens or 0),
        usd_saved=usd.quantize(Decimal("0.000001")),
        pricing_model_id=pricing_model_id,
        occurred_at_first=occurred_at_first,
        occurred_at_last=occurred_at_last,
        specialist_slug=specialist_slug,
        specialist_name=specialist_name,
    )


@dataclass(frozen=True)
class ModelTotals:
    model_id: str
    tokens: int
    usd: Decimal


def top_models(
    session: Session,
    *,
    user_id: uuid.UUID,
    is_demo: bool,
    window: MetricWindow,
    limit: int = 5,
) -> list[ModelTotals]:
    """Top models by tokens consumed in the window.

    Only ``tokens.consumed`` events contribute — they're the canonical
    "this model did N tokens worth of work" rows. Savings events are
    derivative.
    """

    tokens_col = func.coalesce(
        func.sum(
            (func.coalesce(MetricsEvent.input_tokens, 0))
            + (func.coalesce(MetricsEvent.output_tokens, 0))
        ),
        0,
    )
    usd_col = func.coalesce(func.sum(MetricsEvent.usd_amount), 0)
    statement = select(MetricsEvent.model_id, tokens_col, usd_col).where(
        MetricsEvent.kind == METRICS_EVENT_TOKENS_CONSUMED
    )
    statement = _apply_scope(statement, user_id=user_id, is_demo=is_demo, window=window)
    statement = statement.where(col(MetricsEvent.model_id).is_not(None))
    statement = statement.group_by(MetricsEvent.model_id)
    statement = statement.order_by(tokens_col.desc())
    statement = statement.limit(limit)
    rows: list[ModelTotals] = []
    for model_id, tokens, usd in session.exec(statement):
        if model_id is None:
            continue
        rows.append(
            ModelTotals(
                model_id=str(model_id),
                tokens=int(tokens or 0),
                usd=Decimal(str(usd or 0)),
            )
        )
    return rows


@dataclass(frozen=True)
class DayValue:
    day: date
    value: Decimal


def daily_series(
    session: Session,
    *,
    user_id: uuid.UUID,
    is_demo: bool,
    window: MetricWindow,
    definition: MetricDefinition,
) -> list[DayValue]:
    """Per-day series for a non-composed metric, ordered by day asc.

    Days with no events are returned with value 0 so charts render a
    continuous line. ``all`` windows clamp the lower bound to the
    earliest event day for the user.
    """

    if definition.composed or definition.field_name is None or not definition.kinds:
        return []

    column = getattr(MetricsEvent, definition.field_name)
    day_expr = func.date_trunc("day", MetricsEvent.occurred_at).label("day")
    statement = select(day_expr, func.coalesce(func.sum(column), 0)).where(
        col(MetricsEvent.kind).in_(definition.kinds)
    )
    statement = _apply_scope(statement, user_id=user_id, is_demo=is_demo, window=window)
    statement = statement.group_by(day_expr).order_by(day_expr)
    by_day: dict[date, Decimal] = {}
    for day_value, total in session.exec(statement):
        if day_value is None:
            continue
        day_key = day_value.date() if isinstance(day_value, datetime) else day_value
        by_day[day_key] = Decimal(str(total or 0))

    if window.start is None:
        if not by_day:
            return []
        start_day = min(by_day.keys())
    else:
        start_day = window.start.date()
    end_day = window.end.date()

    out: list[DayValue] = []
    cursor = start_day
    while cursor <= end_day:
        out.append(DayValue(day=cursor, value=by_day.get(cursor, Decimal(0))))
        cursor += timedelta(days=1)
    return out
