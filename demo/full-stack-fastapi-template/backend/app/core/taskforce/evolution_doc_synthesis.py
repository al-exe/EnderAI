"""Offline doc synthesis for the self-evolving knowledge layer (T1/T2).

T1: when a material session summary matches no existing Library doc above
``TAU_CREATE``, auto-create a V2 document with provenance stamps.

T2: when match ≥ ``TAU_UPDATE``, append-merge new nuance into the matched doc
with a revertable changelog entry.
"""

from __future__ import annotations

import uuid

from sqlmodel import Session

from app.core.taskforce.evolution_doc_patch import apply_evolution_patch
from app.core.taskforce.evolution_summary import (
    StoredEvolutionSummary,
    stored_summary_from_metadata,
    summary_has_content,
)
from app.core.taskforce.scoring import DiscoveryRequest, ScoredCandidate, score_document
from app.core.v2_documents import get_v2_document_for_actor, list_v2_documents_for_actor
from app.core.taskforce.summarizer import SummarizerResult
from app.models import TaskforceObserveRequest, TaskforceSessionArchive, User, V2Document

# Conservative starting thresholds — tune from real consultation data.
TAU_CREATE = 0.45
TAU_UPDATE = 0.45


def _to_summarizer_result(summary: StoredEvolutionSummary) -> SummarizerResult:
    return SummarizerResult(
        materiality_score=summary.materiality_score,
        summary_points=list(summary.summary_points),
        details_sections=list(summary.details_sections),
        files_touched=[],
        commands_of_interest=[],
        decisions=list(summary.decisions),
        outcome=summary.outcome,
        open_questions=[],
    )


def discovery_request_for_archive(
    archive: TaskforceSessionArchive,
    summary: StoredEvolutionSummary,
) -> DiscoveryRequest:
    prompt = (
        " ".join(summary.summary_points)
        or summary.outcome
        or (archive.title or "")
    ).strip()
    return DiscoveryRequest(
        prompt=prompt,
        title=archive.title,
        git_branch=archive.branch,
        cwd=archive.cwd,
    )


def find_best_document_match(
    session: Session,
    *,
    actor: User,
    archive: TaskforceSessionArchive,
    summary: StoredEvolutionSummary,
) -> ScoredCandidate | None:
    """Score the actor's accessible corpus; return the top match or None."""

    request = discovery_request_for_archive(archive, summary)
    documents = list_v2_documents_for_actor(
        session, actor, demo=archive.is_demo
    )
    best: ScoredCandidate | None = None
    for document in documents:
        scored = score_document(document, request)
        if best is None or scored.score > best.score:
            best = scored
    return best


def _resolve_visibility(
    archive: TaskforceSessionArchive,
    actor: User,
) -> str:
    metadata = archive.source_metadata or {}
    requested = metadata.get("visibility")
    if requested == "private" or actor.organization_id is None:
        return "private"
    return "organization"


def _observe_request_for_archive(
    archive: TaskforceSessionArchive,
    *,
    summary: StoredEvolutionSummary,
    visibility: str,
) -> TaskforceObserveRequest:
    prompt = (archive.title or "").strip()
    if not prompt and summary.summary_points:
        prompt = summary.summary_points[0]
    return TaskforceObserveRequest(
        kind="final",
        prompt=prompt,
        session_id=archive.session_id,
        client=archive.client,
        specialist_slug=archive.specialist_slug,
        visibility=visibility,  # type: ignore[arg-type]
        cwd=archive.cwd,
        branch=archive.branch,
        summary_points=list(summary.summary_points),
        details_sections=[
            section for section in summary.details_sections if isinstance(section, dict)
        ],
        decisions=list(summary.decisions),
        outcome=summary.outcome,
    )


def _active_session_doc_covers_summary(
    session: Session,
    *,
    actor: User,
    archive: TaskforceSessionArchive,
    summary: StoredEvolutionSummary,
) -> bool:
    """True when observe's session doc already captures this summary."""

    if archive.active_document_id is None:
        return False
    document = get_v2_document_for_actor(
        session,
        actor,
        archive.active_document_id,
        demo=archive.is_demo,
    )
    if document is None:
        return False
    request = discovery_request_for_archive(archive, summary)
    return score_document(document, request).score >= TAU_CREATE


def synthesize_documents(
    session: Session,
    *,
    archive: TaskforceSessionArchive,
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Run T1 auto-create and T2 auto-update for one archived session."""

    actor = session.get(User, archive.actor_id)
    if actor is None:
        return [], []

    stored = stored_summary_from_metadata(archive.source_metadata)
    if stored is None or not summary_has_content(stored):
        return [], []

    best = find_best_document_match(
        session, actor=actor, archive=archive, summary=stored
    )

    if best is not None and best.score >= TAU_UPDATE:
        if archive.active_document_id == best.document.id:
            return [], []
        summarizer = _to_summarizer_result(stored)
        changelog = apply_evolution_patch(
            session,
            actor=actor,
            document=best.document,
            archive=archive,
            stored=stored,
            summary=summarizer,
            match_score=best.score,
        )
        if changelog is not None:
            return [], [best.document.id]
        return [], []

    if _active_session_doc_covers_summary(
        session, actor=actor, archive=archive, summary=stored
    ):
        return [], []

    if best is not None and best.score >= TAU_CREATE:
        return [], []

    visibility = _resolve_visibility(archive, actor)
    summarizer = _to_summarizer_result(stored)
    observe_request = _observe_request_for_archive(
        archive, summary=stored, visibility=visibility
    )
    match_score = best.score if best is not None else 0.0
    confidence = min(1.0, max(stored.materiality_score, match_score))

    # Lazy import: observe pulls in evolution.mark_session_for_evolution.
    from app.core.taskforce.observe import create_v2_document_from_session_summary

    document = create_v2_document_from_session_summary(
        session,
        actor=actor,
        summary=summarizer,
        is_demo=archive.is_demo,
        request=observe_request,
        fleet_session_id=archive.fleet_session_id,
        auto_created=True,
        evolution_confidence=confidence,
        evolution_provenance={
            "source_session_id": archive.session_id,
            "actor_id": str(actor.id),
            "harness_client": archive.client,
            "harness_label": archive.harness_label,
            "specialist_slug": archive.specialist_slug,
            "model_id": archive.model_id,
            "best_match_score": match_score,
            "tau_create": TAU_CREATE,
        },
    )
    session.flush()
    return [document.id], []
