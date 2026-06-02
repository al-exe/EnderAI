from collections.abc import Generator
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlmodel import Session, delete

from app.core.metrics import (
    cross_boundary_reuse_totals,
    documents_touched_count,
    resolve_window,
    reuse_rate,
    savings_breakdown,
    sum_metric_total,
    top_models,
)
from app.core.metrics.registry import REGISTRY
from app.core.security import get_password_hash
from app.models import (
    METRICS_EVENT_DOCUMENT_CONSULTED,
    METRICS_EVENT_DOCUMENT_CREATED,
    METRICS_EVENT_DOCUMENT_REUSED,
    METRICS_EVENT_TOKENS_CONSUMED,
    METRICS_EVENT_TOKENS_SAVED_CACHE,
    METRICS_EVENT_TOKENS_SAVED_REUSE,
    METRICS_EVENT_TOKENS_SAVED_SUMMARY_ONLY,
    MetricsEvent,
    User,
    V2Document,
)
from tests.utils.utils import random_email, random_lower_string


def _utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


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
    db.execute(delete(MetricsEvent).where(MetricsEvent.user_id == user.id))
    db.execute(delete(V2Document).where(V2Document.owner_id == user.id))  # type: ignore[arg-type]
    db.delete(user)
    db.commit()


def _doc(db: Session, user: User) -> V2Document:
    document = V2Document(owner_id=user.id, title="queries doc")
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def _event(
    db: Session,
    user: User,
    *,
    kind: str,
    occurred_at: datetime,
    input_tokens: int | None = None,
    usd_amount: Decimal | None = None,
    cache_read_tokens: int | None = None,
    document: V2Document | None = None,
    is_demo: bool = False,
    model_id: str | None = None,
    output_tokens: int | None = None,
    payload: dict[str, str] | None = None,
) -> None:
    event = MetricsEvent(
        occurred_at=occurred_at,
        user_id=user.id,
        organization_id=None,
        document_id=document.id if document else None,
        kind=kind,
        model_id=model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        usd_amount=usd_amount,
        payload=payload or {},
        is_demo=is_demo,
    )
    db.add(event)
    db.commit()


def test_sum_metric_total_sums_tokens_saved_across_three_sources(
    db: Session, user: User
) -> None:
    now = _utc(2026, 5, 19, 9)
    _event(
        db,
        user,
        kind=METRICS_EVENT_TOKENS_SAVED_CACHE,
        occurred_at=now,
        input_tokens=1000,
    )
    _event(
        db,
        user,
        kind=METRICS_EVENT_TOKENS_SAVED_SUMMARY_ONLY,
        occurred_at=now,
        input_tokens=500,
    )
    _event(
        db,
        user,
        kind=METRICS_EVENT_TOKENS_SAVED_REUSE,
        occurred_at=now,
        input_tokens=2000,
    )
    # Unrelated event should not contribute.
    _event(
        db,
        user,
        kind=METRICS_EVENT_TOKENS_CONSUMED,
        occurred_at=now,
        input_tokens=99999,
    )

    window = resolve_window("7d", now=_utc(2026, 5, 19, 23))
    total = sum_metric_total(
        db,
        user_id=user.id,
        is_demo=False,
        window=window,
        definition=REGISTRY["tokens_saved"],
    )
    assert total == Decimal(3500)


def test_sum_metric_total_respects_window_bounds(db: Session, user: User) -> None:
    _event(
        db,
        user,
        kind=METRICS_EVENT_TOKENS_SAVED_CACHE,
        occurred_at=_utc(2026, 1, 1),
        input_tokens=1000,
    )
    _event(
        db,
        user,
        kind=METRICS_EVENT_TOKENS_SAVED_CACHE,
        occurred_at=_utc(2026, 5, 18),
        input_tokens=200,
    )
    window = resolve_window("7d", now=_utc(2026, 5, 19, 12))
    total = sum_metric_total(
        db,
        user_id=user.id,
        is_demo=False,
        window=window,
        definition=REGISTRY["tokens_saved"],
    )
    # Only the 2026-05-18 row falls inside the 7-day window.
    assert total == Decimal(200)


def test_sum_metric_total_isolates_demo_from_live(db: Session, user: User) -> None:
    now = _utc(2026, 5, 19)
    _event(
        db,
        user,
        kind=METRICS_EVENT_TOKENS_SAVED_CACHE,
        occurred_at=now,
        input_tokens=1000,
    )
    _event(
        db,
        user,
        kind=METRICS_EVENT_TOKENS_SAVED_CACHE,
        occurred_at=now,
        input_tokens=9999,
        is_demo=True,
    )
    window = resolve_window("7d", now=_utc(2026, 5, 19, 23))

    live = sum_metric_total(
        db,
        user_id=user.id,
        is_demo=False,
        window=window,
        definition=REGISTRY["tokens_saved"],
    )
    demo = sum_metric_total(
        db,
        user_id=user.id,
        is_demo=True,
        window=window,
        definition=REGISTRY["tokens_saved"],
    )
    assert live == Decimal(1000)
    assert demo == Decimal(9999)


def test_documents_touched_counts_distinct_ids(db: Session, user: User) -> None:
    doc_a = _doc(db, user)
    doc_b = _doc(db, user)
    now = _utc(2026, 5, 19)
    _event(
        db, user, kind=METRICS_EVENT_DOCUMENT_CREATED, occurred_at=now, document=doc_a
    )
    _event(
        db, user, kind=METRICS_EVENT_DOCUMENT_REUSED, occurred_at=now, document=doc_a
    )
    _event(
        db, user, kind=METRICS_EVENT_DOCUMENT_CREATED, occurred_at=now, document=doc_b
    )
    window = resolve_window("7d", now=_utc(2026, 5, 19, 23))
    assert (
        documents_touched_count(db, user_id=user.id, is_demo=False, window=window) == 2
    )


def test_reuse_rate_is_reused_over_total_begin_calls(db: Session, user: User) -> None:
    now = _utc(2026, 5, 19)
    _event(db, user, kind=METRICS_EVENT_DOCUMENT_REUSED, occurred_at=now)
    _event(db, user, kind=METRICS_EVENT_DOCUMENT_REUSED, occurred_at=now)
    _event(db, user, kind=METRICS_EVENT_DOCUMENT_CREATED, occurred_at=now)
    window = resolve_window("7d", now=_utc(2026, 5, 19, 23))
    rate = reuse_rate(db, user_id=user.id, is_demo=False, window=window)
    # 2 reuses / 3 begin calls.
    assert rate == Decimal("0.6667")


def test_reuse_rate_returns_zero_when_no_events(db: Session, user: User) -> None:
    window = resolve_window("7d", now=_utc(2026, 5, 19, 23))
    assert reuse_rate(db, user_id=user.id, is_demo=False, window=window) == Decimal(0)


def test_savings_breakdown_splits_by_kind(db: Session, user: User) -> None:
    now = _utc(2026, 5, 19)
    _event(
        db,
        user,
        kind=METRICS_EVENT_TOKENS_SAVED_CACHE,
        occurred_at=now,
        input_tokens=100,
    )
    _event(
        db,
        user,
        kind=METRICS_EVENT_TOKENS_SAVED_SUMMARY_ONLY,
        occurred_at=now,
        input_tokens=200,
    )
    _event(
        db,
        user,
        kind=METRICS_EVENT_TOKENS_SAVED_REUSE,
        occurred_at=now,
        input_tokens=300,
    )
    window = resolve_window("7d", now=_utc(2026, 5, 19, 23))
    breakdown = savings_breakdown(db, user_id=user.id, is_demo=False, window=window)
    assert breakdown.cache == Decimal(100)
    assert breakdown.summary_only == Decimal(200)
    assert breakdown.reuse == Decimal(300)
    assert breakdown.total == Decimal(600)


def test_cross_boundary_reuse_totals_split_tool_boundary(
    db: Session, user: User
) -> None:
    same_doc = _doc(db, user)
    same_doc.produced_by_client = "codex"
    cross_doc = _doc(db, user)
    cross_doc.produced_by_client = "codex"
    db.add(same_doc)
    db.add(cross_doc)
    db.commit()

    now = _utc(2026, 5, 19)
    _event(
        db,
        user,
        kind=METRICS_EVENT_DOCUMENT_CONSULTED,
        occurred_at=now,
        input_tokens=100,
        usd_amount=Decimal("0.010000"),
        document=same_doc,
        payload={"consumed_by_client": "codex"},
    )
    _event(
        db,
        user,
        kind=METRICS_EVENT_DOCUMENT_CONSULTED,
        occurred_at=now,
        input_tokens=300,
        usd_amount=Decimal("0.030000"),
        document=cross_doc,
        payload={"consumed_by_client": "claude-code"},
    )

    window = resolve_window("7d", now=_utc(2026, 5, 19, 23))
    totals = cross_boundary_reuse_totals(
        db,
        user_id=user.id,
        is_demo=False,
        window=window,
    )

    assert totals.total_consults == 2
    assert totals.cross_boundary_consults == 1
    assert totals.rate == Decimal("0.5000")
    assert totals.cross_boundary_tokens == 300
    assert totals.cross_boundary_usd == Decimal("0.030000")
    assert totals.same_boundary_tokens == 100
    assert totals.same_boundary_usd == Decimal("0.010000")


def test_top_models_orders_by_total_tokens_desc(db: Session, user: User) -> None:
    now = _utc(2026, 5, 19)
    _event(
        db,
        user,
        kind=METRICS_EVENT_TOKENS_CONSUMED,
        occurred_at=now,
        model_id="claude-haiku-4-5",
        input_tokens=100,
        output_tokens=50,
    )
    _event(
        db,
        user,
        kind=METRICS_EVENT_TOKENS_CONSUMED,
        occurred_at=now,
        model_id="claude-opus-4-7",
        input_tokens=1000,
        output_tokens=500,
    )
    _event(
        db,
        user,
        kind=METRICS_EVENT_TOKENS_CONSUMED,
        occurred_at=now,
        model_id="claude-sonnet-4-6",
        input_tokens=400,
        output_tokens=200,
    )
    window = resolve_window("7d", now=_utc(2026, 5, 19, 23))
    rows = top_models(db, user_id=user.id, is_demo=False, window=window)
    assert [r.model_id for r in rows] == [
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    ]
    assert rows[0].tokens == 1500
