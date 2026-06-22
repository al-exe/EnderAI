from __future__ import annotations

from unittest.mock import patch

from sqlmodel import Session

from app.core.taskforce.evolution_doc_synthesis import synthesize_documents
from app.core.taskforce.scoring import ScoredCandidate
from tests.core.taskforce.test_evolution_doc_synthesis import (
    _archive,
    _library_doc,
    _org,
    _user,
)


def test_synthesize_blocks_contradicting_update(db: Session) -> None:
    org = _org(db)
    user = _user(db, org)
    matched = _library_doc(
        db,
        user,
        title="Stripe webhook retry policy",
        body="Always use retry backoff for Stripe webhook failures",
    )
    matched.evolution_confidence = 0.9
    db.add(matched)
    db.flush()

    archive = _archive(
        db,
        user,
        summary_points=["Never use retry backoff for Stripe webhook failures"],
    )
    fake_match = ScoredCandidate(
        document=matched,
        score=0.95,
        band="high",
        match_reasons=["test seam"],
        matched_anchor_id="summary",
    )

    with patch(
        "app.core.taskforce.evolution_doc_synthesis.find_best_document_match",
        return_value=fake_match,
    ):
        created, updated = synthesize_documents(db, archive=archive)

    assert created == []
    assert updated == []
    db.refresh(matched)
    assert matched.evolution_stale is True
    assert "curation_contradiction" in (matched.evolution_provenance or {})
    blocked = (archive.source_metadata or {}).get("curation_blocked") or []
    assert any(entry.get("reason") == "contradiction" for entry in blocked)


def test_synthesize_creates_provisional_doc_when_confidence_low(db: Session) -> None:
    org = _org(db)
    user = _user(db, org)
    archive = _archive(
        db,
        user,
        summary_points=["Very weak auto-ingest candidate"],
    )
    metadata = dict(archive.source_metadata or {})
    metadata["evolution_summary"]["materiality_score"] = 0.1
    archive.source_metadata = metadata
    db.add(archive)
    db.flush()

    created, updated = synthesize_documents(db, archive=archive)

    assert updated == []
    assert len(created) == 1
    from app.models import V2Document

    document = db.get(V2Document, created[0])
    assert document is not None
    assert document.evolution_stale is True
    assert document.evolution_provenance.get("provisional") is True
