from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.taskforce.curation import (
    EVOLUTION_STALE_TTL_SECONDS,
    TAU_CONFIDENCE,
    detect_contradiction,
    evaluate_curation_gate,
    is_evolution_stale,
    score_evolution_confidence,
    stamp_freshness,
)
from app.core.taskforce.evolution_summary import StoredEvolutionSummary
from app.models import V2Document
from sqlmodel import Session

from tests.core.taskforce.test_evolution_doc_synthesis import _library_doc, _org, _user


def _stored(
    *,
    summary_points: list[str],
    materiality_score: float = 1.0,
    decisions: list[str] | None = None,
) -> StoredEvolutionSummary:
    return StoredEvolutionSummary(
        summary_points=summary_points,
        details_sections=[],
        decisions=decisions or [],
        outcome=None,
        materiality_score=materiality_score,
    )


def test_score_evolution_confidence_boosts_with_corroboration() -> None:
    base = score_evolution_confidence(materiality_score=0.5, match_score=0.4)
    boosted = score_evolution_confidence(
        materiality_score=0.5,
        match_score=0.4,
        has_decisions=True,
        has_outcome=True,
    )
    assert boosted > base
    assert boosted <= 1.0


def test_evaluate_gate_blocks_low_confidence_update() -> None:
    stored = _stored(
        summary_points=["Minor note"],
        materiality_score=0.1,
    )
    document = V2Document(
        title="Runbook",
        description="body",
        ai_generated_summary="body",
        main_body=[{"segments": [{"text": "body"}]}],
        evolution_confidence=0.8,
    )
    result = evaluate_curation_gate(
        action="update",
        stored=stored,
        match_score=0.2,
        document=document,
    )
    assert result.allowed is False
    assert result.block_reason == "low_confidence"
    assert result.confidence < TAU_CONFIDENCE


def test_evaluate_gate_allows_provisional_create_below_threshold() -> None:
    stored = _stored(
        summary_points=["Weak signal only"],
        materiality_score=0.1,
    )
    result = evaluate_curation_gate(action="create", stored=stored, match_score=0.0)
    assert result.allowed is True
    assert result.provisional is True
    assert result.confidence < TAU_CONFIDENCE


def test_detect_contradiction_on_high_confidence_doc(db: Session) -> None:
    org = _org(db)
    user = _user(db, org)
    document = _library_doc(
        db,
        user,
        title="Retry policy",
        body="Always use retry backoff for Stripe webhook failures",
    )
    document.evolution_confidence = 0.9
    db.add(document)
    db.flush()

    contradiction = detect_contradiction(
        document,
        summary_points=["Never use retry backoff for Stripe webhook failures"],
    )
    assert contradiction is not None
    assert contradiction.existing_phrase == "always"
    assert contradiction.incoming_phrase == "never"


def test_evaluate_gate_blocks_contradicting_update(db: Session) -> None:
    org = _org(db)
    user = _user(db, org)
    document = _library_doc(
        db,
        user,
        title="Retry policy",
        body="Always use retry backoff for Stripe webhook failures",
    )
    document.evolution_confidence = 0.9
    db.add(document)
    db.flush()
    stored = _stored(
        summary_points=["Never use retry backoff for Stripe webhook failures"],
        materiality_score=1.0,
    )

    result = evaluate_curation_gate(
        action="update",
        stored=stored,
        match_score=0.9,
        document=document,
    )
    assert result.allowed is False
    assert result.block_reason == "contradiction"
    assert result.contradiction is not None


def test_is_evolution_stale_after_ttl() -> None:
    document = V2Document(
        title="Fresh doc",
        description="",
        ai_generated_summary="",
        main_body=[],
        auto_created=True,
        evolution_stale=False,
        last_verified_at=datetime.now(timezone.utc)
        - timedelta(seconds=EVOLUTION_STALE_TTL_SECONDS + 60),
    )
    assert is_evolution_stale(document) is True


def test_stamp_freshness_clears_stale_flag() -> None:
    document = V2Document(
        title="Recover",
        description="",
        ai_generated_summary="",
        main_body=[],
        evolution_stale=True,
    )
    stamp_freshness(document, confidence=0.8, provisional=False)
    assert document.evolution_stale is False
    assert document.evolution_confidence == 0.8
    assert document.last_verified_at is not None
