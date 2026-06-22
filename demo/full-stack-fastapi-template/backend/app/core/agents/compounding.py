"""Earned-profile compounding (TF-205 / C6).

The Taskforce loop is *raw input -> clean agent profiles -> redropped in*. This
module is the middle arrow's **earned** path: an offline, out-of-loop job that turns
``AgentSpecialist`` rows from ``created_from="seeded"`` into ``"earned"`` by accreting
``AgentSpecialistDocumentLink`` rows from the real ``V2Document``s that match a
specialist's routing signals.

Why it exists (thesis D5): seeded profiles look like a shared-prompt library (the
commodity); *earned* profiles are the moat — "we capture what your agents figure out,
not what you write down." This compounding is that capture, consolidated.

Hard rule: this runs **off the agent's critical path** (a worker / scheduled task),
never from ``route_specialist`` or any request handler — sensor, not processor.

Full design (algorithm, reused helpers, guardrails): ``docs/planning/earned-profiles-design.md``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from sqlmodel import Session, col, select

from app.core.taskforce.scoring import DiscoveryRequest, score_document, tokenize
from app.core.v2_documents import list_v2_documents_for_actor
from app.models import (
    AgentSpecialist,
    AgentSpecialistDocumentLink,
    User,
    V2Document,
    get_datetime_utc,
)

# Tunables (see design doc §Guardrails). Start values; regress from real data later.
MIN_LINK_SCORE = 0.45
MAX_LINKS_PER_SPECIALIST = 25


def _text_from_paragraphs(paragraphs: Sequence[Any]) -> str:
    out: list[str] = []
    for paragraph in paragraphs:
        segments = (
            paragraph.get("segments")
            if isinstance(paragraph, dict)
            else paragraph.segments
        ) or []
        for segment in segments:
            text = segment.get("text") if isinstance(segment, dict) else segment.text
            if text:
                out.append(text)
    return "\n".join(out)


def _text_from_details(sections: Sequence[Any]) -> str:
    out: list[str] = []
    for section in sections:
        markdown = (
            section.get("markdown") if isinstance(section, dict) else section.markdown
        )
        if markdown:
            out.append(markdown)
    return "\n".join(out)


def _document_text(document: V2Document) -> str:
    return "\n".join(
        filter(
            None,
            [
                document.title or "",
                document.description or "",
                document.human_summary or "",
                document.ai_generated_summary or "",
                _text_from_paragraphs(document.main_body or []),
                _text_from_details(document.details_markdown_sections or []),
            ],
        )
    )


def _routing_signals(specialist: AgentSpecialist) -> list[str]:
    seen: set[str] = set()
    signals: list[str] = []
    for value in [
        *specialist.routing_triggers,
        *specialist.domain_tags,
    ]:
        normalized = value.strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            signals.append(normalized)
    return signals


def _match_reason(specialist: AgentSpecialist, document: V2Document) -> str:
    signals = _routing_signals(specialist)
    doc_tokens = set(tokenize(_document_text(document)))
    matched: list[str] = []
    for signal in signals:
        signal_tokens = set(tokenize(signal))
        if signal_tokens and signal_tokens & doc_tokens:
            matched.append(signal)

    if not matched:
        matched = signals[:3]

    detail = ", ".join(matched[:5]) if matched else specialist.slug
    return f"earned: matched {detail}"[:240]


def _specialists_statement(organization_id: uuid.UUID | None) -> Any:
    statement = (
        select(AgentSpecialist)
        .where(AgentSpecialist.status == "active")
        .where(col(AgentSpecialist.is_demo).is_(False))
        .where(col(AgentSpecialist.organization_id).is_not(None))
        .order_by(col(AgentSpecialist.created_at).asc(), col(AgentSpecialist.id).asc())
    )
    if organization_id is not None:
        statement = statement.where(AgentSpecialist.organization_id == organization_id)
    return statement


def _actor_for_specialist(
    session: Session,
    specialist: AgentSpecialist,
    cache: dict[uuid.UUID, User | None],
) -> User | None:
    if specialist.owner_id is not None:
        owner = session.get(User, specialist.owner_id)
        if owner is not None and owner.organization_id == specialist.organization_id:
            return owner

    if specialist.organization_id is None:
        return None
    if specialist.organization_id not in cache:
        cache[specialist.organization_id] = session.exec(
            select(User)
            .where(User.organization_id == specialist.organization_id)
            .where(col(User.is_active).is_(True))
            .order_by(col(User.created_at).asc(), col(User.id).asc())
        ).first()
    return cache[specialist.organization_id]


def _candidate_documents(
    session: Session,
    *,
    actor: User,
    organization_id: uuid.UUID,
) -> list[V2Document]:
    return [
        document
        for document in list_v2_documents_for_actor(session, actor, demo=False)
        if document.organization_id == organization_id and not document.is_demo
    ]


def _existing_link_by_document_id(
    session: Session,
    specialist_id: uuid.UUID,
) -> dict[uuid.UUID, AgentSpecialistDocumentLink]:
    links = session.exec(
        select(AgentSpecialistDocumentLink).where(
            AgentSpecialistDocumentLink.specialist_id == specialist_id
        )
    ).all()
    return {link.document_id: link for link in links}


def _link_would_change(
    link: AgentSpecialistDocumentLink,
    *,
    anchor_id: str,
    reason: str,
    weight: float,
) -> bool:
    return (
        link.anchor_id != anchor_id
        or link.reason != reason
        or abs(link.weight - weight) > 0.000001
    )


def _prune_overflow(
    session: Session,
    *,
    specialist_id: uuid.UUID,
    max_links: int,
    dry_run: bool,
) -> int:
    if max_links <= 0:
        max_links = 0

    links = list(
        session.exec(
            select(AgentSpecialistDocumentLink).where(
                AgentSpecialistDocumentLink.specialist_id == specialist_id
            )
        ).all()
    )
    overflow = len(links) - max_links
    if overflow <= 0:
        return 0

    prune_candidates = sorted(
        [link for link in links if not link.is_pinned],
        key=lambda link: (link.weight, link.created_at or get_datetime_utc(), link.id),
    )
    to_prune = prune_candidates[:overflow]
    if not dry_run:
        for link in to_prune:
            session.delete(link)
    return len(to_prune)


def _has_earned_link(links: Iterable[AgentSpecialistDocumentLink]) -> bool:
    return any((link.reason or "").startswith("earned:") for link in links)


def link_document_to_specialist(
    session: Session,
    specialist: AgentSpecialist,
    document: V2Document,
    *,
    anchor_id: str | None,
    reason: str,
    weight: float,
) -> tuple[bool, bool]:
    """Upsert one doc link on a specialist. Returns (created, updated)."""

    existing = session.exec(
        select(AgentSpecialistDocumentLink).where(
            AgentSpecialistDocumentLink.specialist_id == specialist.id,
            AgentSpecialistDocumentLink.document_id == document.id,
        )
    ).first()
    if existing is None:
        session.add(
            AgentSpecialistDocumentLink(
                specialist_id=specialist.id,
                document_id=document.id,
                anchor_id=anchor_id,
                reason=reason,
                weight=weight,
                is_pinned=False,
            )
        )
        return True, False
    if existing.is_pinned:
        return False, False
    if _link_would_change(
        existing,
        anchor_id=anchor_id or existing.anchor_id,
        reason=reason,
        weight=weight,
    ):
        existing.anchor_id = anchor_id
        existing.reason = reason
        existing.weight = weight
        return False, True
    return False, False


def compound_specialists(
    session: Session,
    *,
    organization_id: uuid.UUID | None = None,
    min_link_score: float = MIN_LINK_SCORE,
    max_links_per_specialist: int = MAX_LINKS_PER_SPECIALIST,
    dry_run: bool = True,
) -> dict[str, int]:
    """Accrete earned doc-links onto an org's specialists; flip ``created_from``.

    Returns a summary, e.g. ``{"specialists_seen": N, "links_created": M,
    "links_updated": K, "promoted_to_earned": P}``. With ``dry_run=True`` (default)
    it computes the plan and writes nothing — mirroring ``observe.py`` shadow mode.

    The job is deliberately offline/out-of-loop. It is not imported from routing
    or any request handler.
    """

    report = {
        "specialists_seen": 0,
        "links_created": 0,
        "links_updated": 0,
        "links_pruned": 0,
        "promoted_to_earned": 0,
    }
    actor_cache: dict[uuid.UUID, User | None] = {}

    specialists = list(session.exec(_specialists_statement(organization_id)).all())
    for specialist in specialists:
        if specialist.organization_id is None:
            continue
        signals = _routing_signals(specialist)
        if not signals:
            continue

        actor = _actor_for_specialist(session, specialist, actor_cache)
        if actor is None:
            continue

        report["specialists_seen"] += 1
        request = DiscoveryRequest(prompt=" ".join(signals))
        existing_links = _existing_link_by_document_id(session, specialist.id)
        matched_existing_earned = _has_earned_link(existing_links.values())

        for document in _candidate_documents(
            session,
            actor=actor,
            organization_id=specialist.organization_id,
        ):
            scored = score_document(document, request)
            if scored.score < min_link_score:
                continue

            reason = _match_reason(specialist, document)
            existing = existing_links.get(document.id)
            if existing is None:
                report["links_created"] += 1
                matched_existing_earned = True
                if not dry_run:
                    link = AgentSpecialistDocumentLink(
                        specialist_id=specialist.id,
                        document_id=document.id,
                        anchor_id=scored.matched_anchor_id,
                        reason=reason,
                        weight=scored.score,
                        is_pinned=False,
                    )
                    session.add(link)
                    existing_links[document.id] = link
                continue

            if existing.is_pinned:
                continue

            matched_existing_earned = True
            if _link_would_change(
                existing,
                anchor_id=scored.matched_anchor_id,
                reason=reason,
                weight=scored.score,
            ):
                report["links_updated"] += 1
                if not dry_run:
                    existing.anchor_id = scored.matched_anchor_id
                    existing.reason = reason
                    existing.weight = scored.score

        if specialist.created_from == "seeded" and matched_existing_earned:
            report["promoted_to_earned"] += 1
            if not dry_run:
                specialist.created_from = "earned"
                specialist.updated_at = get_datetime_utc()

        if not dry_run:
            session.flush()
            report["links_pruned"] += _prune_overflow(
                session,
                specialist_id=specialist.id,
                max_links=max_links_per_specialist,
                dry_run=False,
            )

    if not dry_run:
        session.flush()
    return report
