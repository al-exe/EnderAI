from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.api.deps import CurrentUser, SessionDep
from app.core.agents.access import build_agent_specialist_acl_filter
from app.core.v2_documents import build_v2_document_acl_filter
from app.models import (
    METRICS_EVENT_DOCUMENT_CONSULTED,
    AgentsListResponse,
    AgentSpecialist,
    AgentSpecialistCreate,
    AgentSpecialistDetail,
    AgentSpecialistDocumentLink,
    AgentSpecialistInvocationSummary,
    AgentSpecialistLinkedDoc,
    AgentSpecialistStats,
    AgentSpecialistSummary,
    AgentSpecialistUpdate,
    MetricsEvent,
    V2Document,
)

# Leave headroom inside the 64-char slug column for a uniqueness suffix.
_SLUG_BASE_MAX = 56


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:_SLUG_BASE_MAX] or "profile"


def _unique_slug(session: Session, base: str) -> str:
    slug = base
    suffix = 2
    while (
        session.exec(
            select(AgentSpecialist).where(AgentSpecialist.slug == slug)
        ).first()
        is not None
    ):
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


router = APIRouter(prefix="/v2/agents", tags=["v2-agents"])


def _event_scope(slug: str) -> Any:
    return (
        (MetricsEvent.kind == METRICS_EVENT_DOCUMENT_CONSULTED)
        & (MetricsEvent.payload["specialist_slug"].astext == slug)  # type: ignore[index]
    )


def _agent_stats(
    session: Session,
    *,
    specialist: AgentSpecialist,
    linked_docs_count: int,
    current_user_id: Any,
    demo: bool,
) -> AgentSpecialistStats:
    session_id_expr = MetricsEvent.payload["session_id"].astext  # type: ignore[index]
    statement = (
        select(
            func.count(func.distinct(session_id_expr)),
            func.coalesce(func.sum(MetricsEvent.input_tokens), 0),
            func.coalesce(func.sum(MetricsEvent.usd_amount), 0),
        )
        .where(_event_scope(specialist.slug))
        .where(MetricsEvent.user_id == current_user_id)
        .where(MetricsEvent.is_demo.is_(demo))  # type: ignore[union-attr]
    )
    invocations_count, tokens_saved, usd_saved = session.exec(statement).one()
    return AgentSpecialistStats(
        invocations_count=int(invocations_count or 0),
        linked_docs_count=linked_docs_count,
        tokens_saved=int(tokens_saved or 0),
        usd_saved=Decimal(str(usd_saved or 0)).quantize(Decimal("0.000001")),
    )


def _last_invoked_at(
    session: Session,
    *,
    specialist: AgentSpecialist,
    current_user_id: Any,
    demo: bool,
) -> datetime | None:
    statement = (
        select(func.max(MetricsEvent.occurred_at))
        .where(_event_scope(specialist.slug))
        .where(MetricsEvent.user_id == current_user_id)
        .where(MetricsEvent.is_demo.is_(demo))  # type: ignore[union-attr]
    )
    return session.exec(statement).one()


def _linked_docs(
    session: Session,
    *,
    specialist: AgentSpecialist,
    current_user: CurrentUser,
    demo: bool,
) -> list[AgentSpecialistLinkedDoc]:
    statement = (
        select(AgentSpecialistDocumentLink, V2Document)
        .join(V2Document, V2Document.id == AgentSpecialistDocumentLink.document_id)
        .where(AgentSpecialistDocumentLink.specialist_id == specialist.id)
        .where(build_v2_document_acl_filter(current_user, demo=demo))
        .order_by(
            col(AgentSpecialistDocumentLink.is_pinned).desc(),
            col(AgentSpecialistDocumentLink.weight).desc(),
            col(AgentSpecialistDocumentLink.created_at).asc(),
        )
    )
    linked: list[AgentSpecialistLinkedDoc] = []
    for link, document in session.exec(statement).all():
        href = f"/v2/library/{document.id}"
        if link.anchor_id:
            href += f"#{link.anchor_id}"
        linked.append(
            AgentSpecialistLinkedDoc(
                document_id=document.id,
                title=document.title,
                description=document.description,
                anchor_id=link.anchor_id,
                href=href,
                reason=link.reason,
            )
        )
    return linked


def _recent_invocations(
    session: Session,
    *,
    specialist: AgentSpecialist,
    current_user_id: Any,
    demo: bool,
) -> list[AgentSpecialistInvocationSummary]:
    # One /tf call consults N docs → N document.consulted events with the
    # same session_id. Collapse them client-side into one invocation row
    # per session (sum tokens, count docs, pick latest occurred_at as the
    # row's timestamp). Events that have no session_id (pre-TF-181 legacy
    # rows, hand-seeded metrics) stay as one row each, keyed by event.id.
    statement = (
        select(MetricsEvent)
        .where(_event_scope(specialist.slug))
        .where(MetricsEvent.user_id == current_user_id)
        .where(MetricsEvent.is_demo.is_(demo))  # type: ignore[union-attr]
        .order_by(col(MetricsEvent.occurred_at).desc())
        # Fetch wider than the display limit so collapsing doesn't leave
        # us short on rows when many events share a session_id.
        .limit(60)
    )

    grouped: dict[str, AgentSpecialistInvocationSummary] = {}
    order: list[str] = []
    for event in session.exec(statement).all():
        payload = event.payload or {}
        session_id = payload.get("session_id")
        # Group key: session_id when present, else the event id (no dedup).
        key = str(session_id) if session_id else f"event:{event.id}"

        if key in grouped:
            existing = grouped[key]
            grouped[key] = existing.model_copy(
                update={
                    "tokens_saved": existing.tokens_saved
                    + int(event.input_tokens or 0),
                    "documents_consulted_count": existing.documents_consulted_count + 1,
                    # Keep the earliest occurred_at as the row's "when" so
                    # the time delta shown to the user reflects when the
                    # session started, not when the last doc was logged.
                    "created_at": min(existing.created_at, event.occurred_at)
                    if existing.created_at and event.occurred_at
                    else existing.created_at or event.occurred_at,
                }
            )
            continue

        grouped[key] = AgentSpecialistInvocationSummary(
            id=event.id,
            prompt=str(payload.get("prompt") or ""),
            summary=payload.get("summary"),
            session_id=session_id,
            repo=payload.get("repo"),
            branch=payload.get("branch"),
            documents_consulted_count=1,
            tokens_saved=int(event.input_tokens or 0),
            created_at=event.occurred_at,
        )
        order.append(key)

    # Re-sort by created_at desc (collapsing may have moved earliest
    # timestamps earlier than the fetch order) and cap at 10.
    collapsed = [grouped[k] for k in order]
    collapsed.sort(
        key=lambda inv: inv.created_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return collapsed[:10]


def _linked_docs_count(
    session: Session,
    *,
    specialist: AgentSpecialist,
    current_user: CurrentUser,
    demo: bool,
) -> int:
    statement = (
        select(func.count())
        .select_from(AgentSpecialistDocumentLink)
        .join(V2Document, V2Document.id == AgentSpecialistDocumentLink.document_id)
        .where(AgentSpecialistDocumentLink.specialist_id == specialist.id)
        .where(build_v2_document_acl_filter(current_user, demo=demo))
    )
    return int(session.exec(statement).one() or 0)


def _summary_for(
    session: Session,
    *,
    specialist: AgentSpecialist,
    current_user: CurrentUser,
    demo: bool,
) -> AgentSpecialistSummary:
    linked_docs_count = _linked_docs_count(
        session,
        specialist=specialist,
        current_user=current_user,
        demo=demo,
    )
    stats = _agent_stats(
        session,
        specialist=specialist,
        linked_docs_count=linked_docs_count,
        current_user_id=current_user.id,
        demo=demo,
    )
    return AgentSpecialistSummary(
        id=specialist.id,
        slug=specialist.slug,
        name=specialist.name,
        role=specialist.role,
        status=specialist.status,
        short_description=specialist.short_description,
        domain_tags=list(specialist.domain_tags or []),
        created_from=specialist.created_from,
        linked_docs_count=linked_docs_count,
        invocations_count=stats.invocations_count,
        tokens_saved=stats.tokens_saved,
        last_invoked_at=_last_invoked_at(
            session,
            specialist=specialist,
            current_user_id=current_user.id,
            demo=demo,
        ),
        created_at=specialist.created_at,
    )


def _detail_for(
    session: Session,
    *,
    specialist: AgentSpecialist,
    current_user: CurrentUser,
    demo: bool,
) -> AgentSpecialistDetail:
    linked_knowledge = _linked_docs(
        session,
        specialist=specialist,
        current_user=current_user,
        demo=demo,
    )
    stats = _agent_stats(
        session,
        specialist=specialist,
        linked_docs_count=len(linked_knowledge),
        current_user_id=current_user.id,
        demo=demo,
    )
    return AgentSpecialistDetail(
        id=specialist.id,
        slug=specialist.slug,
        name=specialist.name,
        role=specialist.role,
        status=specialist.status,
        short_description=specialist.short_description,
        description=specialist.description,
        created_from=specialist.created_from,
        domain_tags=list(specialist.domain_tags or []),
        routing_triggers=list(specialist.routing_triggers or []),
        negative_triggers=list(specialist.negative_triggers or []),
        instructions=list(specialist.instructions or []),
        linked_knowledge=linked_knowledge,
        recent_invocations=_recent_invocations(
            session,
            specialist=specialist,
            current_user_id=current_user.id,
            demo=demo,
        ),
        stats=stats,
    )


def _writable_specialist(
    session: Session,
    *,
    current_user: CurrentUser,
    slug: str,
    demo: bool,
) -> AgentSpecialist:
    """Resolve a specialist the actor is allowed to modify, or raise."""

    specialist = session.exec(
        select(AgentSpecialist).where(AgentSpecialist.slug == slug)
    ).first()
    if specialist is None:
        raise HTTPException(status_code=404, detail="Agent specialist not found")

    accessible = session.exec(
        select(AgentSpecialist)
        .where(AgentSpecialist.id == specialist.id)
        .where(build_agent_specialist_acl_filter(current_user, demo=demo))
    ).first()
    if accessible is None:
        raise HTTPException(status_code=403, detail="Agent specialist access denied")

    # Outside the demo sandbox, only the owner may edit or delete a profile.
    if not demo and specialist.owner_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Only the owner can modify this profile"
        )
    return specialist


@router.get("", response_model=AgentsListResponse)
def list_agents(
    session: SessionDep,
    current_user: CurrentUser,
    demo: bool = Query(default=False),
) -> Any:
    specialists = session.exec(
        select(AgentSpecialist)
        .where(build_agent_specialist_acl_filter(current_user, demo=demo))
    ).all()
    items = [
        _summary_for(
            session,
            specialist=specialist,
            current_user=current_user,
            demo=demo,
        )
        for specialist in specialists
    ]
    items.sort(
        key=lambda item: (
            -(item.created_at.timestamp() if item.created_at else 0),
            item.name.lower(),
        )
    )
    return AgentsListResponse(items=items)


@router.post("", response_model=AgentSpecialistDetail, status_code=201)
def create_agent(
    session: SessionDep,
    current_user: CurrentUser,
    payload: AgentSpecialistCreate,
    demo: bool = Query(default=False),
) -> Any:
    name = payload.name.strip()
    role = payload.role.strip()
    if not name or not role:
        raise HTTPException(status_code=422, detail="Name and role are required")

    specialist = AgentSpecialist(
        owner_id=current_user.id,
        organization_id=None,
        slug=_unique_slug(session, _slugify(name)),
        name=name[:80],
        role=role[:160],
        short_description=(payload.short_description or "").strip()[:240],
        description="",
        status="active",
        visibility="private",
        domain_tags=[tag.strip() for tag in (payload.domain_tags or []) if tag.strip()],
        created_from="manual",
        is_demo=demo,
    )
    session.add(specialist)
    session.commit()
    session.refresh(specialist)

    # A freshly created profile has no linked docs or invocations yet.
    return AgentSpecialistDetail(
        id=specialist.id,
        slug=specialist.slug,
        name=specialist.name,
        role=specialist.role,
        status=specialist.status,
        short_description=specialist.short_description,
        description=specialist.description,
        created_from=specialist.created_from,
        domain_tags=list(specialist.domain_tags or []),
        routing_triggers=list(specialist.routing_triggers or []),
        negative_triggers=list(specialist.negative_triggers or []),
        instructions=list(specialist.instructions or []),
        linked_knowledge=[],
        recent_invocations=[],
        stats=AgentSpecialistStats(
            invocations_count=0,
            linked_docs_count=0,
            tokens_saved=0,
            usd_saved=Decimal(0),
        ),
    )


@router.get("/{slug}", response_model=AgentSpecialistDetail)
def get_agent(
    session: SessionDep,
    current_user: CurrentUser,
    slug: str,
    demo: bool = Query(default=False),
) -> Any:
    specialist = session.exec(
        select(AgentSpecialist).where(AgentSpecialist.slug == slug)
    ).first()
    if specialist is None:
        raise HTTPException(status_code=404, detail="Agent specialist not found")

    accessible = session.exec(
        select(AgentSpecialist)
        .where(AgentSpecialist.id == specialist.id)
        .where(build_agent_specialist_acl_filter(current_user, demo=demo))
    ).first()
    if accessible is None:
        raise HTTPException(status_code=403, detail="Agent specialist access denied")

    return _detail_for(
        session,
        specialist=specialist,
        current_user=current_user,
        demo=demo,
    )


@router.patch("/{slug}", response_model=AgentSpecialistDetail)
def update_agent(
    session: SessionDep,
    current_user: CurrentUser,
    slug: str,
    payload: AgentSpecialistUpdate,
    demo: bool = Query(default=False),
) -> Any:
    specialist = _writable_specialist(
        session, current_user=current_user, slug=slug, demo=demo
    )

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Name cannot be empty")
        specialist.name = name[:80]
    if payload.role is not None:
        role = payload.role.strip()
        if not role:
            raise HTTPException(status_code=422, detail="Role cannot be empty")
        specialist.role = role[:160]
    if payload.short_description is not None:
        specialist.short_description = payload.short_description.strip()[:240]
    if payload.domain_tags is not None:
        specialist.domain_tags = [
            tag.strip() for tag in payload.domain_tags if tag.strip()
        ]
    if payload.status is not None:
        specialist.status = payload.status

    specialist.updated_at = datetime.now(timezone.utc)
    session.add(specialist)
    session.commit()
    session.refresh(specialist)

    return _detail_for(
        session,
        specialist=specialist,
        current_user=current_user,
        demo=demo,
    )


@router.delete("/{slug}", status_code=204, response_model=None)
def delete_agent(
    session: SessionDep,
    current_user: CurrentUser,
    slug: str,
    demo: bool = Query(default=False),
) -> None:
    specialist = _writable_specialist(
        session, current_user=current_user, slug=slug, demo=demo
    )
    # agent_specialist_document_link rows cascade on the FK (ondelete=CASCADE).
    session.delete(specialist)
    session.commit()
