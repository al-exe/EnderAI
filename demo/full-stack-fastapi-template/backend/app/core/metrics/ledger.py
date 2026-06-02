"""Org-wide session ledger (TF-208 / pipeline-surfaces P1).

The raw tier of the Taskforce pipeline (``taskforce-pipeline-deep-dive.md``):
every session an org runs through a Taskforce-enabled tool, grouped from the
append-only ``metrics_event`` log. Newer sessions can also have a persisted
``taskforce_session_archive`` row that carries transcript/detail metadata; the
metrics grouping remains the pagination and compatibility backbone.

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

from sqlalchemy import String, and_, cast, func, or_
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Session, col, select

from app.models import (
    AgentSpecialist,
    MetricsEvent,
    TaskforceSessionArchive,
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
    title: str | None = None
    actor_handle: str | None = None
    harness_label: str | None = None
    harness_version: str | None = None
    model_id: str | None = None
    repo: str | None = None
    branch: str | None = None
    cwd: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: int = 0
    imported_at: datetime | None = None
    message_count: int = 0
    command_count: int = 0
    edit_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    source: str | None = None
    transcript_available: bool = False


@dataclass(frozen=True)
class LedgerTranscriptEvent:
    kind: str
    occurred_at: datetime | None = None
    role: str | None = None
    who: str | None = None
    text: str | None = None
    cmd: str | None = None
    exit_code: int | None = None
    output: str | None = None
    file: str | None = None
    added: int | None = None
    removed: int | None = None
    note: str | None = None
    repo: str | None = None


@dataclass(frozen=True)
class LedgerSessionDetail:
    row: LedgerSessionRow
    transcript_events: list[LedgerTranscriptEvent]
    raw_transcript_available: bool
    source_metadata: dict[str, Any]


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
    document_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    client: str | None = None,
    specialist_slug: str | None = None,
    session_id: str | None = None,
    cross_boundary_only: bool = False,
    since: datetime | None = None,
    until: datetime | None = None,
    query: str | None = None,
    sort: str = "newest",
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
            # Postgres has no min(uuid); aggregate as text then cast back.
            # One actor per session, so which row we pick is immaterial.
            cast(
                func.min(cast(MetricsEvent.user_id, String)), PGUUID(as_uuid=True)
            ).label("actor_id"),
            func.coalesce(
                func.max(TaskforceSessionArchive.client),
                func.max(_consumed_client_expr()),
            ).label("client"),
            func.coalesce(
                func.max(TaskforceSessionArchive.specialist_slug),
                func.max(_specialist_slug_expr()),
            ).label("specialist_slug"),
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
            func.max(TaskforceSessionArchive.title).label("title"),
            func.max(TaskforceSessionArchive.harness_label).label("harness_label"),
            func.max(TaskforceSessionArchive.harness_version).label("harness_version"),
            func.max(TaskforceSessionArchive.model_id).label("model_id"),
            func.max(TaskforceSessionArchive.repo).label("repo"),
            func.max(TaskforceSessionArchive.branch).label("branch"),
            func.max(TaskforceSessionArchive.cwd).label("cwd"),
            func.min(TaskforceSessionArchive.started_at).label("started_at"),
            func.max(TaskforceSessionArchive.ended_at).label("ended_at"),
            func.coalesce(func.max(TaskforceSessionArchive.duration_ms), 0).label(
                "duration_ms"
            ),
            func.max(TaskforceSessionArchive.imported_at).label("imported_at"),
            func.coalesce(func.max(TaskforceSessionArchive.message_count), 0).label(
                "message_count"
            ),
            func.coalesce(func.max(TaskforceSessionArchive.command_count), 0).label(
                "command_count"
            ),
            func.coalesce(func.max(TaskforceSessionArchive.edit_count), 0).label(
                "edit_count"
            ),
            func.coalesce(func.max(TaskforceSessionArchive.input_tokens), 0).label(
                "input_tokens"
            ),
            func.coalesce(func.max(TaskforceSessionArchive.output_tokens), 0).label(
                "output_tokens"
            ),
            func.coalesce(func.max(TaskforceSessionArchive.cache_read_tokens), 0).label(
                "cache_read_tokens"
            ),
            func.coalesce(
                func.max(TaskforceSessionArchive.cache_write_tokens), 0
            ).label("cache_write_tokens"),
            func.coalesce(
                func.bool_or(
                    func.jsonb_array_length(TaskforceSessionArchive.transcript_events)
                    > 0
                ),
                False,
            ).label("transcript_available"),
        )
        .join(
            TaskforceSessionArchive,
            and_(
                TaskforceSessionArchive.session_id == sid,
                TaskforceSessionArchive.organization_id == MetricsEvent.organization_id,
                TaskforceSessionArchive.is_demo == MetricsEvent.is_demo,
            ),
            isouter=True,
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
    if document_id is not None:
        grouped = grouped.where(MetricsEvent.document_id == document_id)
    if actor_id is not None:
        grouped = grouped.where(MetricsEvent.user_id == actor_id)
    if client is not None:
        grouped = grouped.where(
            or_(
                _consumed_client_expr() == client,
                TaskforceSessionArchive.client == client,
            )
        )
    if specialist_slug is not None:
        grouped = grouped.where(
            or_(
                _specialist_slug_expr() == specialist_slug,
                TaskforceSessionArchive.specialist_slug == specialist_slug,
            )
        )
    if session_id is not None:
        grouped = grouped.where(sid == session_id)
    if since is not None:
        grouped = grouped.where(col(MetricsEvent.occurred_at) >= since)
    if until is not None:
        grouped = grouped.where(col(MetricsEvent.occurred_at) < until)
    if query:
        like = f"%{query}%"
        grouped = grouped.where(
            or_(
                _prompt_expr().ilike(like),
                col(V2Document.title).ilike(like),
                col(TaskforceSessionArchive.title).ilike(like),
                col(TaskforceSessionArchive.repo).ilike(like),
                col(TaskforceSessionArchive.branch).ilike(like),
                col(TaskforceSessionArchive.cwd).ilike(like),
                cast(TaskforceSessionArchive.transcript_events, String).ilike(like),
            )
        )

    grouped = grouped.group_by(sid)
    if cross_boundary_only:
        grouped = grouped.having(func.bool_or(xb).is_(True))

    count_subq = grouped.subquery()
    total = int(session.exec(select(func.count()).select_from(count_subq)).one() or 0)

    order_expr = func.max(MetricsEvent.occurred_at)
    page_stmt = (
        grouped.order_by(order_expr.asc() if sort == "oldest" else order_expr.desc())
        .limit(limit)
        .offset(offset)
    )
    raw_rows = session.exec(page_stmt).all()

    # ---- query 2: hydrate doc titles + specialist names for the page -------
    archive_by_session: dict[str, TaskforceSessionArchive] = {}
    session_ids = [r.session_id for r in raw_rows if r.session_id]
    if session_ids:
        for archive in session.exec(
            select(TaskforceSessionArchive)
            .where(TaskforceSessionArchive.organization_id == organization_id)
            .where(TaskforceSessionArchive.is_demo == is_demo)
            .where(col(TaskforceSessionArchive.session_id).in_(session_ids))
        ):
            archive_by_session[archive.session_id] = archive

    all_doc_ids: set[uuid.UUID] = set()
    all_slugs: set[str] = set()
    for r in raw_rows:
        for did in r.doc_ids or []:
            if did is not None:
                all_doc_ids.add(did)
        archive = archive_by_session.get(r.session_id)
        if archive is not None:
            all_doc_ids.update(_archive_document_ids(archive))
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
        archive = archive_by_session.get(r.session_id)
        ordered_doc_ids = _ordered_document_ids(
            metric_doc_ids=r.doc_ids or [],
            archive=archive,
        )
        doc_refs = [
            LedgerDocRef(document_id=did, title=doc_titles.get(did, "Untitled"))
            for did in ordered_doc_ids
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
                title=r.title,
                actor_handle=actor_names.get(r.actor_id, "Unknown"),
                harness_label=r.harness_label or r.client,
                harness_version=r.harness_version,
                model_id=r.model_id,
                repo=r.repo,
                branch=r.branch,
                cwd=r.cwd,
                started_at=r.started_at,
                ended_at=r.ended_at,
                duration_ms=int(r.duration_ms or 0),
                imported_at=r.imported_at,
                message_count=int(r.message_count or 0),
                command_count=int(r.command_count or 0),
                edit_count=int(r.edit_count or 0),
                input_tokens=int(r.input_tokens or 0),
                output_tokens=int(r.output_tokens or 0),
                cache_read_tokens=int(r.cache_read_tokens or 0),
                cache_write_tokens=int(r.cache_write_tokens or 0),
                source=r.client,
                transcript_available=bool(r.transcript_available),
            )
        )

    return LedgerPage(rows=rows, total=total, limit=limit, offset=offset)


def ledger_session_detail(
    session: Session,
    *,
    organization_id: uuid.UUID,
    session_id: str,
    is_demo: bool = False,
) -> LedgerSessionDetail | None:
    page = ledger_sessions(
        session,
        organization_id=organization_id,
        is_demo=is_demo,
        session_id=session_id,
        limit=1,
    )
    if not page.rows:
        return None

    archive = session.exec(
        select(TaskforceSessionArchive)
        .where(TaskforceSessionArchive.organization_id == organization_id)
        .where(TaskforceSessionArchive.is_demo == is_demo)
        .where(TaskforceSessionArchive.session_id == session_id)
    ).first()

    return LedgerSessionDetail(
        row=page.rows[0],
        transcript_events=_transcript_events_from_archive(archive),
        raw_transcript_available=bool(archive and archive.raw_transcript),
        source_metadata=dict(archive.source_metadata or {}) if archive else {},
    )


def _transcript_events_from_archive(
    archive: TaskforceSessionArchive | None,
) -> list[LedgerTranscriptEvent]:
    if archive is None:
        return []

    events: list[LedgerTranscriptEvent] = []
    for raw in archive.transcript_events or []:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "")
        if kind not in {"prompt", "reply", "command", "edit", "note"}:
            continue
        events.append(
            LedgerTranscriptEvent(
                kind=kind,
                occurred_at=_parse_event_time(raw.get("occurred_at")),
                role=_str_or_none(raw.get("role")),
                who=_str_or_none(raw.get("who")),
                text=_str_or_none(raw.get("text")),
                cmd=_str_or_none(raw.get("cmd")),
                exit_code=(
                    int(raw["exit_code"]) if raw.get("exit_code") is not None else None
                ),
                output=_str_or_none(raw.get("output")),
                file=_str_or_none(raw.get("file")),
                added=_int_or_none(raw.get("added")),
                removed=_int_or_none(raw.get("removed")),
                note=_str_or_none(raw.get("note")),
                repo=_str_or_none(raw.get("repo")),
            )
        )
    return events


def _ordered_document_ids(
    *,
    metric_doc_ids: list[uuid.UUID | None],
    archive: TaskforceSessionArchive | None,
) -> list[uuid.UUID]:
    ordered: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for did in metric_doc_ids:
        if did is not None and did not in seen:
            ordered.append(did)
            seen.add(did)
    if archive is not None:
        for did in _archive_document_ids(archive):
            if did not in seen:
                ordered.append(did)
                seen.add(did)
    return ordered


def _archive_document_ids(archive: TaskforceSessionArchive) -> set[uuid.UUID]:
    doc_ids: set[uuid.UUID] = set()
    for value in archive.referenced_document_ids or []:
        try:
            doc_ids.add(uuid.UUID(str(value)))
        except ValueError:
            continue
    return doc_ids


def _parse_event_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
