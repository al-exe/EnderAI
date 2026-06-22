from __future__ import annotations

from sqlmodel import Session, select

from app.core.metrics.events import (
    record_doc_auto_created,
    record_specialist_evolved,
    record_specialist_proposed,
)
from app.models import METRICS_EVENT_DOC_AUTO_CREATED, METRICS_EVENT_SPECIALIST_EVOLVED, MetricsEvent
from tests.core.agents.test_compounding import _document, _org, _org_user


def test_record_doc_auto_created_emits_ledger_event(db: Session) -> None:
    org = _org(db)
    user = _org_user(db, org)
    document = _document(db, user)

    record_doc_auto_created(
        db,
        user=user,
        document=document,
        is_demo=False,
        source_session_id="sess-auto-create",
        confidence=0.8,
    )
    db.commit()

    event = db.exec(
        select(MetricsEvent).where(MetricsEvent.kind == METRICS_EVENT_DOC_AUTO_CREATED)
    ).first()
    assert event is not None
    assert event.payload["source_session_id"] == "sess-auto-create"
    assert event.document_id == document.id


def test_record_specialist_evolved_payload(db: Session) -> None:
    org = _org(db)
    user = _org_user(db, org)

    record_specialist_evolved(
        db,
        user=user,
        is_demo=False,
        specialist_slug="billing-specialist",
        source_session_id="sess-evolve",
        confidence=0.9,
        links_created=1,
        instructions_added=2,
    )
    db.commit()

    event = db.exec(
        select(MetricsEvent).where(
            MetricsEvent.kind == METRICS_EVENT_SPECIALIST_EVOLVED
        )
    ).first()
    assert event is not None
    assert event.payload["specialist_slug"] == "billing-specialist"
    assert event.payload["instructions_added"] == 2


def test_record_specialist_proposed_payload(db: Session) -> None:
    org = _org(db)
    user = _org_user(db, org)

    record_specialist_proposed(
        db,
        user=user,
        is_demo=False,
        specialist_slug="earned-stripe",
        cluster_key="stripe-webhook-billing",
        source_session_ids=["a", "b", "c"],
        confidence=0.7,
    )
    db.commit()

    event = db.exec(select(MetricsEvent).where(MetricsEvent.kind == "specialist.proposed")).first()
    assert event is not None
    assert event.payload["cluster_key"] == "stripe-webhook-billing"
