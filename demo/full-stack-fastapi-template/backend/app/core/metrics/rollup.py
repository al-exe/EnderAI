"""Daily rollup job.

Materializes one row per (day, user, is_demo, metric_name) into
``metrics_daily_rollup`` so the read endpoint serves 7d/30d/all-time
totals from indexed lookups rather than full scans of ``metrics_event``.

Idempotent: re-running for the same day replaces the rows. The job is
expected to be invoked once per day for the previous day, but it's safe
to call multiple times or to backfill old days.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlmodel import Session, col, delete, select

from app.core.metrics.queries import MetricWindow, sum_metric_total
from app.core.metrics.registry import REGISTRY, rollup_metric_names
from app.models import MetricsDailyRollup, MetricsEvent


def _bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def _users_active_on(
    session: Session, day: date
) -> list[tuple[uuid.UUID, uuid.UUID | None, bool]]:
    """Every (user_id, organization_id, is_demo) tuple with at least one
    event on ``day``. Demo and live are rolled up as separate rows so
    plan §11 Q5 isolation holds."""

    start, end = _bounds(day)
    statement = (
        select(
            MetricsEvent.user_id,
            MetricsEvent.organization_id,
            MetricsEvent.is_demo,
        )
        .where(col(MetricsEvent.occurred_at) >= start)
        .where(col(MetricsEvent.occurred_at) < end)
        .distinct()
    )
    return [(uid, oid, bool(demo)) for uid, oid, demo in session.exec(statement)]


def compute_daily_rollup(
    session: Session,
    *,
    day: date,
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    is_demo: bool,
) -> int:
    """Compute (and upsert) every rollup-eligible metric for one
    (day, user, is_demo) triple. Returns the number of metric rows
    written.

    Caller is responsible for committing.
    """

    start, end = _bounds(day)
    window = MetricWindow(name="all", start=start, end=end)

    # Clear existing rows for this day so the upsert is idempotent.
    session.execute(
        delete(MetricsDailyRollup).where(
            col(MetricsDailyRollup.day) == day,
            col(MetricsDailyRollup.user_id) == user_id,
            col(MetricsDailyRollup.is_demo) == is_demo,
        )
    )

    written = 0
    for name in rollup_metric_names():
        defn = REGISTRY[name]
        total = sum_metric_total(
            session,
            user_id=user_id,
            is_demo=is_demo,
            window=window,
            definition=defn,
        )
        count = _kind_count(
            session,
            user_id=user_id,
            is_demo=is_demo,
            start=start,
            end=end,
            kinds=defn.kinds,
        )
        if total == 0 and count == 0:
            continue
        session.add(
            MetricsDailyRollup(
                day=day,
                user_id=user_id,
                is_demo=is_demo,
                metric_name=name,
                organization_id=organization_id,
                value_num=Decimal(str(total)),
                value_count=count,
            )
        )
        written += 1
    return written


def _kind_count(
    session: Session,
    *,
    user_id: uuid.UUID,
    is_demo: bool,
    start: datetime,
    end: datetime,
    kinds: tuple[str, ...],
) -> int:
    if not kinds:
        return 0
    statement = (
        select(func.count())
        .where(col(MetricsEvent.kind).in_(kinds))
        .where(MetricsEvent.user_id == user_id)
        .where(MetricsEvent.is_demo == is_demo)
        .where(col(MetricsEvent.occurred_at) >= start)
        .where(col(MetricsEvent.occurred_at) < end)
    )
    result = session.exec(statement).first()
    return int(result or 0)


def rollup_day(session: Session, *, day: date) -> int:
    """Rollup every active (user, demo) pair for ``day``. Returns the
    total number of rollup rows written. Caller commits."""

    written = 0
    for user_id, organization_id, is_demo in _users_active_on(session, day):
        written += compute_daily_rollup(
            session,
            day=day,
            user_id=user_id,
            organization_id=organization_id,
            is_demo=is_demo,
        )
    return written
