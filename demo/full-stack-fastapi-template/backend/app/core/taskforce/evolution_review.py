"""Human review queue for proposed specialists and flagged doc edits (T6)."""

from __future__ import annotations

import uuid

from sqlmodel import Session, col, select

from app.core.agents.access import build_agent_specialist_acl_filter
from app.core.v2_documents import build_v2_document_acl_filter
from app.models import AgentSpecialist, User, V2Document, get_datetime_utc


def list_review_items(
    session: Session,
    *,
    actor: User,
    demo: bool,
) -> dict[str, list[dict]]:
    """Return proposed specialists and contradiction-flagged documents."""

    specialist_acl = build_agent_specialist_acl_filter(actor, demo=demo)
    proposed = list(
        session.exec(
            select(AgentSpecialist)
            .where(AgentSpecialist.status == "proposed")
            .where(specialist_acl)
            .order_by(col(AgentSpecialist.created_at).desc())
        ).all()
    )

    doc_acl = build_v2_document_acl_filter(actor, demo=demo)
    flagged_docs = list(
        session.exec(
            select(V2Document)
            .where(col(V2Document.evolution_stale).is_(True))
            .where(doc_acl)
            .order_by(col(V2Document.updated_at).desc())
            .limit(50)
        ).all()
    )
    contradiction_docs = [
        document
        for document in flagged_docs
        if (document.evolution_provenance or {}).get("curation_contradiction")
    ]

    return {
        "proposed_specialists": [
            {
                "id": str(specialist.id),
                "slug": specialist.slug,
                "name": specialist.name,
                "role": specialist.role,
                "short_description": specialist.short_description,
                "evolution_provenance": specialist.evolution_provenance or {},
                "created_at": specialist.created_at,
            }
            for specialist in proposed
        ],
        "flagged_documents": [
            {
                "id": str(document.id),
                "title": document.title,
                "evolution_stale": document.evolution_stale,
                "evolution_confidence": document.evolution_confidence,
                "curation_contradiction": (
                    document.evolution_provenance or {}
                ).get("curation_contradiction"),
                "updated_at": document.updated_at,
            }
            for document in contradiction_docs
        ],
    }


def confirm_proposed_specialist(
    session: Session,
    *,
    actor: User,
    specialist_id: uuid.UUID,
    demo: bool,
) -> AgentSpecialist:
    specialist = session.get(AgentSpecialist, specialist_id)
    if specialist is None:
        raise ValueError("specialist_not_found")

    accessible = session.exec(
        select(AgentSpecialist)
        .where(AgentSpecialist.id == specialist_id)
        .where(build_agent_specialist_acl_filter(actor, demo=demo))
    ).first()
    if accessible is None:
        raise ValueError("specialist_access_denied")
    if specialist.status != "proposed":
        raise ValueError("specialist_not_proposed")

    specialist.status = "active"
    provenance = dict(specialist.evolution_provenance or {})
    provenance["review"] = {
        "action": "confirmed",
        "actor_id": str(actor.id),
        "confirmed_at": get_datetime_utc().isoformat(),
    }
    specialist.evolution_provenance = provenance
    specialist.updated_at = get_datetime_utc()
    session.add(specialist)
    session.flush()
    return specialist


def reject_proposed_specialist(
    session: Session,
    *,
    actor: User,
    specialist_id: uuid.UUID,
    demo: bool,
) -> AgentSpecialist:
    specialist = session.get(AgentSpecialist, specialist_id)
    if specialist is None:
        raise ValueError("specialist_not_found")

    accessible = session.exec(
        select(AgentSpecialist)
        .where(AgentSpecialist.id == specialist_id)
        .where(build_agent_specialist_acl_filter(actor, demo=demo))
    ).first()
    if accessible is None:
        raise ValueError("specialist_access_denied")
    if specialist.status != "proposed":
        raise ValueError("specialist_not_proposed")

    specialist.status = "archived"
    provenance = dict(specialist.evolution_provenance or {})
    provenance["review"] = {
        "action": "rejected",
        "actor_id": str(actor.id),
        "rejected_at": get_datetime_utc().isoformat(),
    }
    specialist.evolution_provenance = provenance
    specialist.updated_at = get_datetime_utc()
    session.add(specialist)
    session.flush()
    return specialist


def dismiss_document_contradiction_flag(
    session: Session,
    *,
    actor: User,
    document_id: uuid.UUID,
    demo: bool,
) -> V2Document:
    document = session.exec(
        select(V2Document)
        .where(V2Document.id == document_id)
        .where(build_v2_document_acl_filter(actor, demo=demo))
    ).first()
    if document is None:
        raise ValueError("document_not_found")

    provenance = dict(document.evolution_provenance or {})
    contradiction = provenance.pop("curation_contradiction", None)
    if contradiction is not None:
        provenance["review"] = {
            "action": "dismissed_contradiction",
            "actor_id": str(actor.id),
            "dismissed_at": get_datetime_utc().isoformat(),
            "prior_contradiction": contradiction,
        }
    document.evolution_provenance = provenance
    document.evolution_stale = False
    document.updated_at = get_datetime_utc()
    session.add(document)
    session.flush()
    return document
