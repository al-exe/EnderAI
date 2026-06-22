from __future__ import annotations

import uuid
from unittest.mock import patch

from sqlmodel import Session, select

from app.core.taskforce.evolution_doc_synthesis import (
    EVOLUTION_SUMMARY_KEY,
    TAU_CREATE,
    StoredEvolutionSummary,
    find_best_document_match,
    synthesize_documents,
)
from app.core.taskforce.scoring import ScoredCandidate
from app.models import Organization, TaskforceSessionArchive, User, V2Document
from tests.utils.user import create_random_user
from tests.utils.utils import random_lower_string


def _org(db: Session) -> Organization:
    org = Organization(name=f"DocSynth {random_lower_string()}")
    db.add(org)
    db.flush()
    return org


def _user(db: Session, org: Organization) -> User:
    user = create_random_user(db)
    user.organization_id = org.id
    user.organization_role = "admin"
    db.add(user)
    db.flush()
    return user


def _archive(
    db: Session,
    user: User,
    *,
    summary_points: list[str],
    visibility: str = "organization",
    active_document_id: uuid.UUID | None = None,
) -> TaskforceSessionArchive:
    archive = TaskforceSessionArchive(
        session_id=f"synth-{random_lower_string()}",
        actor_id=user.id,
        organization_id=user.organization_id,
        is_demo=False,
        title=summary_points[0] if summary_points else "Session",
        active_document_id=active_document_id,
        source_metadata={
            EVOLUTION_SUMMARY_KEY: {
                "summary_points": summary_points,
                "details_sections": [],
                "decisions": [],
                "outcome": None,
                "materiality_score": 1.0,
            },
            "visibility": visibility,
        },
    )
    db.add(archive)
    db.flush()
    return archive


def _library_doc(
    db: Session,
    user: User,
    *,
    title: str,
    body: str,
) -> V2Document:
    document = V2Document(
        owner_id=user.id,
        organization_id=user.organization_id,
        visibility="organization",
        title=title,
        description=body,
        ai_generated_summary=body,
        main_body=[
            {
                "segments": [{"text": body}],
            }
        ],
        is_demo=False,
    )
    db.add(document)
    db.flush()
    return document


def test_synthesize_creates_doc_when_no_match(db: Session) -> None:
    org = _org(db)
    user = _user(db, org)
    archive = _archive(
        db,
        user,
        summary_points=["Novel Stripe webhook idempotency pattern for refunds"],
    )

    created, updated = synthesize_documents(db, archive=archive)

    assert updated == []
    assert len(created) == 1
    document = db.get(V2Document, created[0])
    assert document is not None
    assert document.auto_created is True
    assert document.evolution_confidence is not None
    assert document.evolution_provenance["source_session_id"] == archive.session_id
    assert document.visibility == "organization"
    assert document.organization_id == org.id


def test_synthesize_skips_when_best_match_above_tau_create(db: Session) -> None:
    org = _org(db)
    user = _user(db, org)
    novel_summary = ["Stripe webhook idempotency for duplicate refund events"]
    archive = _archive(db, user, summary_points=novel_summary)
    _library_doc(
        db,
        user,
        title="Stripe webhook idempotency for duplicate refund events",
        body="Stripe webhook idempotency for duplicate refund events",
    )

    created, _ = synthesize_documents(db, archive=archive)
    assert created == []


def test_synthesize_honors_private_visibility(db: Session) -> None:
    org = _org(db)
    user = _user(db, org)
    archive = _archive(
        db,
        user,
        summary_points=["Private-only investigation notes"],
        visibility="private",
    )

    created, _ = synthesize_documents(db, archive=archive)
    document = db.get(V2Document, created[0])
    assert document is not None
    assert document.visibility == "private"
    assert document.organization_id is None


def test_synthesize_skips_without_summary_payload(db: Session) -> None:
    org = _org(db)
    user = _user(db, org)
    archive = TaskforceSessionArchive(
        session_id=f"empty-{random_lower_string()}",
        actor_id=user.id,
        organization_id=user.organization_id,
        is_demo=False,
        source_metadata={},
    )
    db.add(archive)
    db.flush()

    created, updated = synthesize_documents(db, archive=archive)
    assert created == []
    assert updated == []


def test_find_best_document_match_seam_returns_top_scored_candidate(
    db: Session,
) -> None:
    org = _org(db)
    user = _user(db, org)
    summary = StoredEvolutionSummary(
        summary_points=["Billing reliability runbook"],
        details_sections=[],
        decisions=[],
        outcome=None,
        materiality_score=1.0,
    )
    archive = _archive(db, user, summary_points=summary.summary_points)
    matched = _library_doc(
        db,
        user,
        title="Billing reliability runbook",
        body="Billing reliability runbook",
    )

    best = find_best_document_match(
        db, actor=user, archive=archive, summary=summary
    )

    assert best is not None
    assert best.document.id == matched.id
    assert best.score >= TAU_CREATE


def test_synthesize_uses_matcher_seam_to_block_create(db: Session) -> None:
    org = _org(db)
    user = _user(db, org)
    archive = _archive(
        db,
        user,
        summary_points=["Would create without the matcher seam"],
    )
    fake_doc = _library_doc(db, user, title="stub", body="stub")
    fake_match = ScoredCandidate(
        document=fake_doc,
        score=TAU_CREATE,
        band="high",
        match_reasons=["test seam"],
        matched_anchor_id="summary",
    )

    with patch(
        "app.core.taskforce.evolution_doc_synthesis.find_best_document_match",
        return_value=fake_match,
    ):
        created, _ = synthesize_documents(db, archive=archive)

    assert created == []


def test_synthesize_skips_when_active_session_doc_already_covers_summary(
    db: Session,
) -> None:
    org = _org(db)
    user = _user(db, org)
    points = ["Session capture doc already holds this knowledge"]
    session_doc = _library_doc(
        db,
        user,
        title=points[0],
        body=points[0],
    )
    archive = _archive(
        db,
        user,
        summary_points=points,
        active_document_id=session_doc.id,
    )

    created, _ = synthesize_documents(db, archive=archive)
    assert created == []

    count = len(
        db.exec(select(V2Document).where(V2Document.owner_id == user.id)).all()
    )
    assert count == 1
