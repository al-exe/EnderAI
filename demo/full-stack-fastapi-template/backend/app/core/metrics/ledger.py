"""Org-wide session ledger (TF-208 / pipeline-surfaces P1).

The raw tier of the Taskforce pipeline (``taskforce-pipeline-deep-dive.md``):
every session an org runs through a Taskforce-enabled tool, grouped from the
append-only ``metrics_event`` log. There is **no Session table** — a "session"
is emergent from ``metrics_event.payload->>'session_id'``; this module is a
*read model* over that grouping, not new persisted state.

Framing is recall / activity / provenance, never "proof": the cross-boundary
signal is one boolean attribute + filter on a row, not a headline. See
``docs/planning/taskforce-pipeline-surfaces-design.md`` → P1.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_
from sqlmodel import Session, col, select

from app.models import (
    AgentSpecialist,
    MetricsEvent,
    User,
    V2Document,
)

# Events that carry a ``session_id`` and represent "work in a session" — the
# rows that compose the ledger. Everything with a session_id in payload is in
# scope; we don't restrict by kind so observe/consult/reuse all contribute.
_LEDGER_MAX_LIMIT = 200
_LEDGER_MAX_DOCS_PER_ROW = 20


def _session_id_expr() -> Any:
    return MetricsEvent.payload["session_id"].astext


def _consumed_client_expr() -> Any:
    return MetricsEvent.payload["consumed_by_client"].astext


def _specialist_slug_expr() -> Any:
    return MetricsEvent.payload["specialist_slug"].astext


def _prompt_expr() -> Any:
    return MetricsEvent.payload["prompt"].astext


def _cross_boundary_event_expr() -> Any:
    """True for an event that crossed a person OR tool boundary.

    Person boundary: the consumer (``MetricsEvent.user_id``) is not the owner of
    the document the event touched. Tool boundary: the consuming tool
    (``payload->>'consumed_by_client'``) differs from the document's origin tool
    (``V2Document.produced_by_client``). Both require a joined document; for
    document-less events the expression is false.
    """

    person_boundary = and_(
        col(MetricsEvent.document_id).is_not(None),
        col(MetricsEvent.user_id) != col(V2Document.owner_id),
    )
    consumed = _consumed_client_expr()
    tool_boundary = and_(
        consumed.is_not(None),
        col(V2Document.produced_by_client).is_not(None),
        consumed != col(V2Document.produced_by_client),
    )
    return or_(person_boundary, tool_boundary)


@dataclass(frozen=True)
class LedgerDocRef:
    document_id: uuid.UUID
    title: str


@dataclass(frozen=True)
class LedgerSessionRow:
    """One session: who, in which tool, what they did, what it saved."""

    session_id: str
    actor_id: uuid.UUID
    actor_name: str
    client: str | None
    specialist_slug: str | None
    specialist_name: str | None
    documents: list[LedgerDocRef]
    kinds: list[str]
    net_saved_tokens: int
    usd_amount: Decimal
    event_count: int
    cross_boundary: bool
    occurred_at_first: datetime
    occurred_at_last: datetime


@dataclass(frozen=True)
class LedgerPage:
    rows: list[LedgerSessionRow]
    total: int
    limit: int
    offset: int


def ledger_sessions(
    session: Session,
    *,
    organization_id: uuid.UUID,
    is_demo: bool = False,
    actor_id: uuid.UUID | None = None,
    client: str | None = None,
    specialist_slug: str | None = None,
    cross_boundary_only: bool = False,
    since: datetime | None = None,
    until: datetime | None = None,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> LedgerPage:
    """Paginated, org-scoped feed of sessions, newest first.

    Two queries: (1) select + aggregate the page of ``session_id`` groups with
    all filters applied at the DB level (so ``cross_boundary_only`` and the
    total count are correct), then (2) hydrate doc titles + specialist names for
    just the page. The left join to ``V2Document`` powers both the free-text
    title search and the cross-boundary determination.
    """

    limit = max(1, min(limit, _LEDGER_MAX_LIMIT))
    offset = max(0, offset)
    sid = _session_id_expr()
    xb = _cross_boundary_event_expr()

    # ---- query 1: page of session groups + aggregates ----------------------
    # Left-join the document so the cross-boundary expression + title search can
    # reference it; group by the emergent session_id.
    grouped: Any = (
        select(
            sid.label("session_id"),
            func.min(MetricsEvent.user_id).label("actor_id"),
            func.max(_consumed_client_expr()).label("client"),
            func.max(_specialist_slug_expr()).label("specialist_slug"),
            func.coalesce(func.sum(MetricsEvent.input_tokens), 0).label(
                "net_saved_tokens"
            ),
            func.coalesce(func.sum(MetricsEvent.usd_amount), 0).label("usd"),
            func.count().label("event_count"),
            func.bool_or(xb).label("cross_boundary"),
            func.array_agg(func.distinct(MetricsEvent.kind)).label("kinds"),
            func.array_agg(func.distinct(MetricsEvent.document_id)).label("doc_ids"),
            func.min(MetricsEvent.occurred_at).label("first_at"),
            func.max(MetricsEvent.occurred_at).label("last_at"),
        )
        .join(
            V2Document,
            col(V2Document.id) == col(MetricsEvent.document_id),
            isouter=True,
        )
        .where(_session_id_expr().is_not(None))
        .where(MetricsEvent.organization_id == organization_id)
        .where(MetricsEvent.is_demo == is_demo)
    )
    if actor_id is not None:
        grouped = grouped.where(MetricsEvent.user_id == actor_id)
    if client is not None:
        grouped = grouped.where(_consumed_client_expr() == client)
    if specialist_slug is not None:
        grouped = grouped.where(_specialist_slug_expr() == specialist_slug)
    if since is not None:
        grouped = grouped.where(col(MetricsEvent.occurred_at) >= since)
    if until is not None:
        grouped = grouped.where(col(MetricsEvent.occurred_at) < until)
    if query:
        like = f"%{query}%"
        grouped = grouped.where(
            or_(_prompt_expr().ilike(like), col(V2Document.title).ilike(like))
        )

    grouped = grouped.group_by(sid)
    if cross_boundary_only:
        grouped = grouped.having(func.bool_or(xb).is_(True))

    count_subq = grouped.subquery()
    total = int(session.exec(select(func.count()).select_from(count_subq)).one() or 0)

    page_stmt = (
        grouped.order_by(func.max(MetricsEvent.occurred_at).desc())
        .limit(limit)
        .offset(offset)
    )
    raw_rows = session.exec(page_stmt).all()

    # ---- query 2: hydrate doc titles + specialist names for the page -------
    all_doc_ids: set[uuid.UUID] = set()
    all_slugs: set[str] = set()
    for r in raw_rows:
        for did in r.doc_ids or []:
            if did is not None:
                all_doc_ids.add(did)
        if r.specialist_slug:
            all_slugs.add(r.specialist_slug)

    doc_titles: dict[uuid.UUID, str] = {}
    if all_doc_ids:
        for did, title in session.exec(
            select(V2Document.id, V2Document.title).where(
                col(V2Document.id).in_(all_doc_ids)
            )
        ):
            doc_titles[did] = title

    specialist_names: dict[str, str] = {}
    if all_slugs:
        for slug, name in session.exec(
            select(AgentSpecialist.slug, AgentSpecialist.name).where(
                col(AgentSpecialist.slug).in_(all_slugs)
            )
        ):
            specialist_names[slug] = name

    actor_ids = {r.actor_id for r in raw_rows if r.actor_id is not None}
    actor_names: dict[uuid.UUID, str] = {}
    if actor_ids:
        for uid, full_name, email in session.exec(
            select(User.id, User.full_name, User.email).where(
                col(User.id).in_(actor_ids)
            )
        ):
            actor_names[uid] = full_name or email

    rows: list[LedgerSessionRow] = []
    for r in raw_rows:
        doc_refs = [
            LedgerDocRef(document_id=did, title=doc_titles.get(did, "Untitled"))
            for did in (r.doc_ids or [])
            if did is not None
        ][:_LEDGER_MAX_DOCS_PER_ROW]
        rows.append(
            LedgerSessionRow(
                session_id=r.session_id,
                actor_id=r.actor_id,
                actor_name=actor_names.get(r.actor_id, "Unknown"),
                client=r.client,
                specialist_slug=r.specialist_slug,
                specialist_name=(
                    specialist_names.get(r.specialist_slug)
                    if r.specialist_slug
                    else None
                ),
                documents=doc_refs,
                kinds=sorted(k for k in (r.kinds or []) if k is not None),
                net_saved_tokens=int(r.net_saved_tokens or 0),
                usd_amount=Decimal(str(r.usd or 0)).quantize(Decimal("0.000001")),
                event_count=int(r.event_count or 0),
                cross_boundary=bool(r.cross_boundary),
                occurred_at_first=r.first_at,
                occurred_at_last=r.last_at,
            )
        )

    return LedgerPage(rows=rows, total=total, limit=limit, offset=offset)
