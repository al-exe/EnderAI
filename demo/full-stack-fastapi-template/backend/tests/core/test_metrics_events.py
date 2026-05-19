from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, delete, select

from app.core.metrics import (
    record_document_created,
    record_document_finished,
    record_document_reused,
    record_document_updated,
    record_usage,
)
from app.core.security import get_password_hash
from app.models import (
    METRICS_EVENT_DOCUMENT_CREATED,
    METRICS_EVENT_DOCUMENT_FINISHED,
    METRICS_EVENT_DOCUMENT_REUSED,
    METRICS_EVENT_DOCUMENT_UPDATED,
    METRICS_EVENT_TOKENS_CONSUMED,
    METRICS_EVENT_TOKENS_SAVED_CACHE,
    METRICS_EVENT_TOKENS_SAVED_REUSE,
    METRICS_EVENT_TOKENS_SAVED_SUMMARY_ONLY,
    MetricsEvent,
    TaskforceUsagePayload,
    User,
    V2Document,
)
from tests.utils.utils import random_email, random_lower_string


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


@pytest.fixture
def user(db: Session) -> Generator[User, None, None]:
    user = User(
        email=random_email(),
        hashed_password=get_password_hash(random_lower_string()),
        v2=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    yield user
    # cascade deletes metrics_event via the FK
    db.execute(delete(V2Document).where(V2Document.owner_id == user.id))  # type: ignore[arg-type]
    db.delete(user)
    db.commit()


def _make_doc(
    db: Session,
    user: User,
    *,
    summary: int = 0,
    details: int = 0,
) -> V2Document:
    document = V2Document(
        owner_id=user.id,
        title="metrics test doc",
        summary_tokens=summary,
        details_tokens=details,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def _events_for(db: Session, document: V2Document) -> list[MetricsEvent]:
    return list(
        db.exec(
            select(MetricsEvent)
            .where(MetricsEvent.document_id == document.id)
            .order_by(MetricsEvent.created_at, MetricsEvent.id)  # type: ignore[arg-type]
        )
    )


def test_record_document_created_without_usage(db: Session, user: User) -> None:
    document = _make_doc(db, user)
    record_document_created(db, user=user, document=document, usage=None, is_demo=False)
    db.commit()

    events = _events_for(db, document)
    assert [e.kind for e in events] == [METRICS_EVENT_DOCUMENT_CREATED]
    assert events[0].user_id == user.id
    assert events[0].pricing_id is None
    assert events[0].usd_amount is None


def test_record_document_updated_with_usage_emits_consumed_event(
    db: Session, user: User
) -> None:
    document = _make_doc(db, user)
    usage = TaskforceUsagePayload(
        model_id="claude-opus-4-7",
        input_tokens=1_000,
        output_tokens=500,
        occurred_at=_utc(2026, 6, 1),
    )
    record_document_updated(
        db, user=user, document=document, usage=usage, is_demo=False
    )
    db.commit()

    events = _events_for(db, document)
    kinds = [e.kind for e in events]
    assert METRICS_EVENT_DOCUMENT_UPDATED in kinds
    assert METRICS_EVENT_TOKENS_CONSUMED in kinds

    consumed = next(e for e in events if e.kind == METRICS_EVENT_TOKENS_CONSUMED)
    assert consumed.input_tokens == 1_000
    assert consumed.output_tokens == 500
    # 1k × $5/MTok + 500 × $25/MTok = $0.005 + $0.0125 = $0.0175
    assert consumed.usd_amount is not None
    assert float(consumed.usd_amount) == pytest.approx(0.0175, rel=1e-6)
    assert consumed.pricing_id is not None


def test_record_usage_emits_cache_savings_event_when_cache_reads_present(
    db: Session, user: User
) -> None:
    document = _make_doc(db, user)
    usage = TaskforceUsagePayload(
        model_id="claude-opus-4-7",
        input_tokens=100,
        cache_read_input_tokens=1_000_000,
        occurred_at=_utc(2026, 6, 1),
    )
    record_usage(db, user=user, document=document, usage=usage, is_demo=False)
    db.commit()

    events = _events_for(db, document)
    kinds = [e.kind for e in events]
    assert METRICS_EVENT_TOKENS_SAVED_CACHE in kinds
    cache = next(e for e in events if e.kind == METRICS_EVENT_TOKENS_SAVED_CACHE)
    assert cache.cache_read_tokens == 1_000_000
    # Opus delta 4.50/MTok × 1M tokens = $4.50.
    assert float(cache.usd_amount or 0) == pytest.approx(4.5, rel=1e-6)


def test_record_usage_emits_summary_only_savings_when_flag_set(
    db: Session, user: User
) -> None:
    document = _make_doc(db, user, details=2_000_000)
    usage = TaskforceUsagePayload(
        model_id="claude-opus-4-7",
        input_tokens=100,
        view_consulted="summary",
        occurred_at=_utc(2026, 6, 1),
    )
    record_usage(db, user=user, document=document, usage=usage, is_demo=False)
    db.commit()

    events = _events_for(db, document)
    summary = [e for e in events if e.kind == METRICS_EVENT_TOKENS_SAVED_SUMMARY_ONLY]
    assert len(summary) == 1
    assert summary[0].input_tokens == 2_000_000
    # 2M × $5/MTok = $10.
    assert float(summary[0].usd_amount or 0) == pytest.approx(10.0, rel=1e-6)


def test_record_document_reused_emits_reuse_savings(db: Session, user: User) -> None:
    document = _make_doc(db, user, summary=5_000, details=10_000)
    record_document_reused(
        db,
        user=user,
        document=document,
        score=82,
        band="high",
        reasons=["Title tokens overlap"],
        usage=None,
        is_demo=False,
    )
    db.commit()

    events = _events_for(db, document)
    kinds = [e.kind for e in events]
    assert kinds == [
        METRICS_EVENT_DOCUMENT_REUSED,
        METRICS_EVENT_TOKENS_SAVED_REUSE,
    ]
    reused = events[0]
    assert reused.payload["score"] == 82
    assert reused.payload["band"] == "high"
    assert reused.payload["bootstrap_tokens"] == 15_000
    saved = events[1]
    # 15k tokens × $5/MTok = $0.075.
    assert saved.input_tokens == 15_000
    assert float(saved.usd_amount or 0) == pytest.approx(0.075, rel=1e-6)


def test_record_document_finished_carries_status_in_payload(
    db: Session, user: User
) -> None:
    document = _make_doc(db, user)
    record_document_finished(
        db,
        user=user,
        document=document,
        status="paused",
        usage=None,
        is_demo=False,
    )
    db.commit()

    events = _events_for(db, document)
    assert [e.kind for e in events] == [METRICS_EVENT_DOCUMENT_FINISHED]
    assert events[0].payload == {"status": "paused"}


def test_events_inherit_is_demo_flag(db: Session, user: User) -> None:
    document = _make_doc(db, user)
    document.is_demo = True
    db.add(document)
    db.commit()
    db.refresh(document)

    record_document_updated(
        db,
        user=user,
        document=document,
        usage=TaskforceUsagePayload(model_id="claude-haiku-4-5", input_tokens=50),
        is_demo=True,
    )
    db.commit()

    events = _events_for(db, document)
    assert all(event.is_demo for event in events)
