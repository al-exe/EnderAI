from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.api.deps import CurrentUser, SessionDep
from app.core.agents.access import build_agent_specialist_acl_filter
from app.core.agents.compounding import MAX_LINKS_PER_SPECIALIST
from app.core.agents.subagent_export import (
    ExportDocument,
    ExportSpecialist,
    render_claude_subagent,
    subagent_content_hash,
    subagent_filename,
)
from app.core.config import settings
from app.core.v2_documents import (
    build_v2_document_acl_filter,
    get_v2_document_for_actor,
)
from app.models import (
    METRICS_EVENT_DOCUMENT_CONSULTED,
    AgentHarnessSyncFile,
    AgentHarnessSyncResponse,
    AgentsListResponse,
    AgentSpecialist,
    AgentSpecialistCreate,
    AgentSpecialistDetail,
    AgentSpecialistDocumentLink,
    AgentSpecialistDocumentLinkCreate,
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
HarnessTarget = Literal["claude", "codex", "cursor"]
HarnessTargetOrAll = Literal["claude", "codex", "cursor", "all"]
_HARNESS_PRIORITY: tuple[HarnessTarget, ...] = ("claude", "codex", "cursor")
_HARNESS_TARGET_DIRS = {
    "claude": ".claude/agents",
    "codex": ".codex/agents",
    "cursor": ".cursor/agents",
}


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
        model_hint=specialist.model_hint,
        permission_scope=specialist.permission_scope,
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


def _details_markdown(document: V2Document) -> str:
    sections = document.details_markdown_sections or []
    markdown: list[str] = []
    for section in sections:
        if isinstance(section, dict):
            value = str(section.get("markdown") or "").strip()
        else:
            value = str(getattr(section, "markdown", "") or "").strip()
        if value:
            markdown.append(value)
    return "\n\n".join(markdown)


def _absolute_document_backlink(document_id: uuid.UUID) -> str:
    """Absolute, harness-portable backlink to a library document.

    Exported subagent files are read by harnesses with no base-URL context, so
    the ``↳`` backlink must be a full URL rather than a bare ``/v2/library/{id}``
    path (which only resolves inside the web app). Derive the origin from
    ``FRONTEND_HOST`` — the same setting the CORS/frontend links use.
    """

    base = (settings.FRONTEND_HOST or "").rstrip("/")
    path = f"/v2/library/{document_id}"
    return f"{base}{path}" if base else path


def _export_specialist_for(
    session: Session,
    *,
    specialist: AgentSpecialist,
    current_user: CurrentUser,
    demo: bool,
) -> ExportSpecialist:
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
    documents: list[ExportDocument] = []
    for link, document in session.exec(statement).all():
        documents.append(
            ExportDocument(
                title=document.title,
                purpose=document.human_summary or document.description,
                details=_details_markdown(document),
                backlink=_absolute_document_backlink(document.id),
                weight=link.weight,
                is_pinned=link.is_pinned,
            )
        )

    return ExportSpecialist(
        slug=specialist.slug,
        short_description=specialist.short_description,
        routing_triggers=list(specialist.routing_triggers or []),
        negative_triggers=list(specialist.negative_triggers or []),
        instructions=list(specialist.instructions or []),
        model_hint=specialist.model_hint,
        permission_scope=specialist.permission_scope,
        documents=documents,
    )


def _render_sync_files(
    specs: list[ExportSpecialist],
    *,
    target: HarnessTargetOrAll,
) -> AgentHarnessSyncResponse:
    targets = list(_HARNESS_PRIORITY if target == "all" else (target,))
    files: list[AgentHarnessSyncFile] = []
    for harness in targets:
        target_dir = _HARNESS_TARGET_DIRS[harness]
        for spec in specs:
            content = render_claude_subagent(spec)
            files.append(
                AgentHarnessSyncFile(
                    target=harness,
                    path=f"{target_dir}/{subagent_filename(spec.slug)}",
                    content=content,
                    sha256=subagent_content_hash(content),
                )
            )
    return AgentHarnessSyncResponse(
        priority=list(_HARNESS_PRIORITY),
        files=files,
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


def _manual_link_reason(
    current_user: CurrentUser,
    payload: AgentSpecialistDocumentLinkCreate,
) -> str:
    reason = (payload.reason or "").strip()
    if reason:
        return reason[:240]
    actor = (current_user.full_name or current_user.email or "user").strip()
    return f"added by {actor}"[:240]


def _link_count(session: Session, specialist_id: Any) -> int:
    return int(
        session.exec(
            select(func.count()).select_from(AgentSpecialistDocumentLink).where(
                AgentSpecialistDocumentLink.specialist_id == specialist_id
            )
        ).one()
        or 0
    )


def _pinned_link_count(session: Session, specialist_id: Any) -> int:
    return int(
        session.exec(
            select(func.count()).select_from(AgentSpecialistDocumentLink).where(
                AgentSpecialistDocumentLink.specialist_id == specialist_id,
                col(AgentSpecialistDocumentLink.is_pinned).is_(True),
            )
        ).one()
        or 0
    )


def _prune_one_unpinned_link(session: Session, specialist_id: Any) -> bool:
    link = session.exec(
        select(AgentSpecialistDocumentLink)
        .where(AgentSpecialistDocumentLink.specialist_id == specialist_id)
        .where(col(AgentSpecialistDocumentLink.is_pinned).is_(False))
        .order_by(
            col(AgentSpecialistDocumentLink.weight).asc(),
            col(AgentSpecialistDocumentLink.created_at).asc(),
            col(AgentSpecialistDocumentLink.id).asc(),
        )
    ).first()
    if link is None:
        return False
    session.delete(link)
    return True


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
        model_hint=specialist.model_hint,
        permission_scope=specialist.permission_scope,
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


@router.get("/sync-harness", response_model=AgentHarnessSyncResponse)
def sync_harness_agents(
    session: SessionDep,
    current_user: CurrentUser,
    target: HarnessTargetOrAll = Query(default="all"),
    demo: bool = Query(default=False),
) -> Any:
    specialists = session.exec(
        select(AgentSpecialist)
        .where(build_agent_specialist_acl_filter(current_user, demo=demo))
        .where(AgentSpecialist.status == "active")
        .order_by(col(AgentSpecialist.slug).asc())
    ).all()
    specs = [
        _export_specialist_for(
            session,
            specialist=specialist,
            current_user=current_user,
            demo=demo,
        )
        for specialist in specialists
    ]
    return _render_sync_files(specs, target=target)


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


@router.post("/{slug}/sync-harness", response_model=AgentHarnessSyncResponse)
def sync_harness_agent(
    session: SessionDep,
    current_user: CurrentUser,
    slug: str,
    target: HarnessTargetOrAll = Query(default="all"),
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

    spec = _export_specialist_for(
        session,
        specialist=specialist,
        current_user=current_user,
        demo=demo,
    )
    return _render_sync_files([spec], target=target)


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
    if payload.model_hint is not None:
        specialist.model_hint = payload.model_hint.strip()[:64] or "inherit"
    if payload.permission_scope is not None:
        specialist.permission_scope = payload.permission_scope
    if payload.instructions is not None:
        specialist.instructions = [
            line.strip() for line in payload.instructions if line.strip()
        ]
    if payload.routing_triggers is not None:
        specialist.routing_triggers = [
            trigger.strip() for trigger in payload.routing_triggers if trigger.strip()
        ]
    if payload.negative_triggers is not None:
        specialist.negative_triggers = [
            trigger.strip() for trigger in payload.negative_triggers if trigger.strip()
        ]

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


@router.post("/{slug}/documents", response_model=AgentSpecialistDetail)
def link_agent_document(
    session: SessionDep,
    current_user: CurrentUser,
    slug: str,
    payload: AgentSpecialistDocumentLinkCreate,
    demo: bool = Query(default=False),
) -> Any:
    specialist = _writable_specialist(
        session, current_user=current_user, slug=slug, demo=demo
    )
    document = get_v2_document_for_actor(
        session,
        current_user,
        payload.document_id,
        demo=demo,
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    existing = session.exec(
        select(AgentSpecialistDocumentLink).where(
            AgentSpecialistDocumentLink.specialist_id == specialist.id,
            AgentSpecialistDocumentLink.document_id == document.id,
        )
    ).first()

    if existing is None or not existing.is_pinned:
        if _pinned_link_count(session, specialist.id) >= MAX_LINKS_PER_SPECIALIST:
            raise HTTPException(
                status_code=409,
                detail="Agent profile already has the maximum pinned documents",
            )

    if existing is None:
        if _link_count(session, specialist.id) >= MAX_LINKS_PER_SPECIALIST:
            pruned = _prune_one_unpinned_link(session, specialist.id)
            if not pruned:
                raise HTTPException(
                    status_code=409,
                    detail="Agent profile already has the maximum linked documents",
                )
        session.add(
            AgentSpecialistDocumentLink(
                specialist_id=specialist.id,
                document_id=document.id,
                anchor_id=None,
                reason=_manual_link_reason(current_user, payload),
                weight=1.0,
                is_pinned=True,
            )
        )
    else:
        existing.anchor_id = None
        existing.reason = _manual_link_reason(current_user, payload)
        existing.weight = max(existing.weight, 1.0)
        existing.is_pinned = True
        session.add(existing)

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


@router.delete("/{slug}/documents/{document_id}", status_code=204, response_model=None)
def unlink_agent_document(
    session: SessionDep,
    current_user: CurrentUser,
    slug: str,
    document_id: uuid.UUID,
    demo: bool = Query(default=False),
) -> None:
    specialist = _writable_specialist(
        session, current_user=current_user, slug=slug, demo=demo
    )
    link = session.exec(
        select(AgentSpecialistDocumentLink).where(
            AgentSpecialistDocumentLink.specialist_id == specialist.id,
            AgentSpecialistDocumentLink.document_id == document_id,
        )
    ).first()
    if link is None:
        raise HTTPException(status_code=404, detail="Document link not found")

    session.delete(link)
    specialist.updated_at = datetime.now(timezone.utc)
    session.add(specialist)
    session.commit()


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
