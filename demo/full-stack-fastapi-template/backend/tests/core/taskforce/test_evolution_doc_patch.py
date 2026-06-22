from __future__ import annotations

import uuid

from sqlmodel import Session, select

from app.core.taskforce.evolution_doc_patch import (
    REFERENCED_BY_ANCHOR_ID,
    apply_evolution_patch,
    revert_evolution_changelog,
)
from app.core.taskforce.evolution_doc_synthesis import (
    TAU_UPDATE,
    synthesize_documents,
)
from app.core.taskforce.evolution_summary import StoredEvolutionSummary
from app.core.taskforce.scoring import ScoredCandidate
from app.core.taskforce.summarizer import SummarizerResult
from app.models import (
    Organization,
    TaskforceSessionArchive,
    User,
    V2Document,
    V2DocumentEvolutionChangelog,
)
from tests.core.taskforce.test_evolution_doc_synthesis import (
    _archive,
    _library_doc,
    _org,
    _user,
)
from unittest.mock import patch


def test_apply_evolution_patch_appends_and_records_changelog(db: Session) -> None:
    org = _org(db)
    user = _user(db, org)
    document = _library_doc(
        db,
        user,
        title="Billing runbook",
        body="Existing billing guidance",
    )
    archive = _archive(
        db,
        user,
        summary_points=["Add retry backoff for Stripe webhook failures"],
    )
    stored = StoredEvolutionSummary(
        summary_points=["Add retry backoff for Stripe webhook failures"],
        details_sections=[],
        decisions=[],
        outcome=None,
        materiality_score=1.0,
    )
    summary = SummarizerResult(
        materiality_score=1.0,
        summary_points=stored.summary_points,
        details_sections=[],
        files_touched=[],
        commands_of_interest=[],
        decisions=[],
        outcome=None,
        open_questions=[],
    )

    changelog = apply_evolution_patch(
        db,
        actor=user,
        document=document,
        archive=archive,
        stored=stored,
        summary=summary,
        match_score=0.9,
    )
    assert changelog is not None
    db.refresh(document)
    sections = document.details_markdown_sections or []
    assert any(
        section.get("anchor_id") == REFERENCED_BY_ANCHOR_ID for section in sections
    )


def test_revert_restores_prior_document_content(db: Session) -> None:
    org = _org(db)
    user = _user(db, org)
    document = _library_doc(db, user, title="Revert me", body="Original body only")
    archive = _archive(db, user, summary_points=["A new evolution finding"])
    stored = StoredEvolutionSummary(
        summary_points=["A new evolution finding"],
        details_sections=[],
        decisions=[],
        outcome=None,
        materiality_score=1.0,
    )
    summary = SummarizerResult(
        materiality_score=1.0,
        summary_points=stored.summary_points,
        details_sections=[],
        files_touched=[],
        commands_of_interest=[],
        decisions=[],
        outcome=None,
        open_questions=[],
    )
    changelog = apply_evolution_patch(
        db,
        actor=user,
        document=document,
        archive=archive,
        stored=stored,
        summary=summary,
        match_score=0.92,
    )
    assert changelog is not None
    before_revert = list(document.main_body or [])

    restored = revert_evolution_changelog(
        db,
        actor=user,
        document_id=document.id,
        changelog_id=changelog.id,
        demo=False,
    )
    assert len(restored.main_body or []) < len(before_revert)
    db.refresh(changelog)
    assert changelog.reverted_at is not None


def test_synthesize_skips_update_below_tau_update(db: Session) -> None:
    org = _org(db)
    user = _user(db, org)
    archive = _archive(db, user, summary_points=["Low-match update candidate"])
    fake_doc = _library_doc(db, user, title="unrelated", body="unrelated")
    weak_match = ScoredCandidate(
        document=fake_doc,
        score=TAU_UPDATE - 0.1,
        band="low",
        match_reasons=["test seam"],
        matched_anchor_id="summary",
    )

    with patch(
        "app.core.taskforce.evolution_doc_synthesis.find_best_document_match",
        return_value=weak_match,
    ):
        created, updated = synthesize_documents(db, archive=archive)

    assert updated == []
    assert len(created) == 1
