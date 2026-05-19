from collections.abc import Generator
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlmodel import Session, delete, select

from app.core.metrics.rollup import compute_daily_rollup, rollup_day
from app.core.security import get_password_hash
from app.models import (
    METRICS_EVENT_DOCUMENT_CREATED,
    METRICS_EVENT_TOKENS_CONSUMED,
    METRICS_EVENT_TOKENS_SAVED_CACHE,
    MetricsDailyRollup,
    MetricsEvent,
    User,
)
from tests.utils.utils import random_email, random_lower_string


def _utc(y: int, m: int, d: int, h: int = 12) -> datetime:
    return datetime(y, m, d, h, tzinfo=timezone.utc)


@pytest.fixture
def user(db: Session) -> Generator[User, None, None]:
    user = User(
        email=random_email(),
        is_active=True,
        hashed_password=get_password_hash(random_lower_string()),
        v2=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    yield user
    db.execute(delete(MetricsDailyRollup).where(MetricsDailyRollup.user_id == user.id))
    db.execute(delete(MetricsEvent).where(MetricsEvent.user_id == user.id))
    db.delete(user)
    db.commit()


def _ev(db: Session, user: User, **kw) -> None:  # type: ignore[no-untyped-def]
    event = MetricsEvent(
        user_id=user.id,
        organization_id=None,
        document_id=None,
        kind=kw["kind"],
        occurred_at=kw["occurred_at"],
        model_id=kw.get("model_id"),
        input_tokens=kw.get("input_tokens"),
        output_tokens=kw.get("output_tokens"),
        cache_read_tokens=kw.get("cache_read_tokens"),
        usd_amount=kw.get("usd_amount"),
        is_demo=kw.get("is_demo", False),
    )
    db.add(event)
    db.commit()


def _rollups_for(db: Session, user: User, day: date) -> list[MetricsDailyRollup]:
    return list(
        db.exec(
            select(MetricsDailyRollup)
            .where(MetricsDailyRollup.user_id == user.id)
            .where(MetricsDailyRollup.day == day)
        )
    )


def test_compute_daily_rollup_writes_one_row_per_active_metric(
    db: Session, user: User
) -> None:
    day = date(2026, 5, 19)
    _ev(
        db,
        user,
        kind=METRICS_EVENT_TOKENS_SAVED_CACHE,
        occurred_at=_utc(2026, 5, 19, 8),
        input_tokens=1000,
        usd_amount=Decimal("0.005"),
    )
    _ev(
        db,
        user,
        kind=METRICS_EVENT_TOKENS_CONSUMED,
        occurred_at=_utc(2026, 5, 19, 9),
        input_tokens=2000,
        usd_amount=Decimal("0.010"),
    )
    _ev(
        db, user, kind=METRICS_EVENT_DOCUMENT_CREATED, occurred_at=_utc(2026, 5, 19, 10)
    )

    written = compute_daily_rollup(
        db, day=day, user_id=user.id, organization_id=None, is_demo=False
    )
    db.commit()
    assert written >= 2  # tokens_saved + tokens_consumed at minimum

    rows = {r.metric_name: r for r in _rollups_for(db, user, day)}
    assert "tokens_saved" in rows
    assert rows["tokens_saved"].value_num == Decimal(1000)
    assert "tokens_consumed" in rows
    assert rows["tokens_consumed"].value_num == Decimal(2000)
    assert "documents_touched" not in rows  # composed, not rolled up


def test_compute_daily_rollup_is_idempotent(db: Session, user: User) -> None:
    day = date(2026, 5, 19)
    _ev(
        db,
        user,
        kind=METRICS_EVENT_TOKENS_SAVED_CACHE,
        occurred_at=_utc(2026, 5, 19, 8),
        input_tokens=1000,
    )

    compute_daily_rollup(
        db, day=day, user_id=user.id, organization_id=None, is_demo=False
    )
    db.commit()
    first = _rollups_for(db, user, day)

    compute_daily_rollup(
        db, day=day, user_id=user.id, organization_id=None, is_demo=False
    )
    db.commit()
    second = _rollups_for(db, user, day)

    assert len(first) == len(second)
    by_name = {r.metric_name: r for r in second}
    assert by_name["tokens_saved"].value_num == Decimal(1000)


def test_rollup_day_iterates_every_active_user_and_demo_pair(
    db: Session, user: User
) -> None:
    day = date(2026, 5, 19)
    _ev(
        db,
        user,
        kind=METRICS_EVENT_TOKENS_SAVED_CACHE,
        occurred_at=_utc(2026, 5, 19, 8),
        input_tokens=100,
    )
    _ev(
        db,
        user,
        kind=METRICS_EVENT_TOKENS_SAVED_CACHE,
        occurred_at=_utc(2026, 5, 19, 9),
        input_tokens=999,
        is_demo=True,
    )

    written = rollup_day(db, day=day)
    db.commit()
    assert written >= 2

    rows = {(r.metric_name, r.is_demo): r for r in _rollups_for(db, user, day)}
    assert rows[("tokens_saved", False)].value_num == Decimal(100)
    assert rows[("tokens_saved", True)].value_num == Decimal(999)


def test_compute_daily_rollup_skips_metrics_with_zero_value_and_zero_count(
    db: Session, user: User
) -> None:
    day = date(2026, 5, 19)
    # No events at all → no rows written.
    compute_daily_rollup(
        db, day=day, user_id=user.id, organization_id=None, is_demo=False
    )
    db.commit()
    assert _rollups_for(db, user, day) == []
