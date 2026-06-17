"""Taskforce session archive ingestion for the Ledger detail surface."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePath
from typing import Any

from sqlalchemy import String, func
from sqlmodel import Session, col, select

from app.core.taskforce.fleet_sessions import (
    get_or_create_default_fleet_session,
)
from app.core.taskforce.session_activity import (
    ingest_observe_events,
    normalized_session_events,
)
from app.core.taskforce.session_provenance import sync_session_provenance
from app.models import (
    MetricsEvent,
    TaskforceObserveRequest,
    TaskforceSessionArchive,
    User,
)

_MAX_TITLE = 255


def upsert_session_archive_from_observe(
    session: Session,
    *,
    actor: User,
    request: TaskforceObserveRequest,
    demo: bool,
    document_id: uuid.UUID | None = None,
) -> TaskforceSessionArchive | None:
    """Persist a best-effort session archive from an observe payload.

    The observe endpoint receives richer session context than the existing
    metrics ledger stores. This read model preserves that context so Ledger can
    render a transcript/detail view while the old metrics grouping remains a
    compatibility fallback.
    """

    if not request.session_id:
        return None

    now = _now()
    archive = session.exec(
        select(TaskforceSessionArchive)
        .where(TaskforceSessionArchive.organization_id == actor.organization_id)
        .where(TaskforceSessionArchive.is_demo == demo)
        .where(TaskforceSessionArchive.session_id == request.session_id)
    ).first()
    if archive is None:
        archive = TaskforceSessionArchive(
            session_id=request.session_id,
            actor_id=actor.id,
            organization_id=actor.organization_id,
            is_demo=demo,
            imported_at=now,
            created_at=now,
        )
    if archive.fleet_session_id is None:
        archive.fleet_session_id = get_or_create_default_fleet_session(
            session, actor
        ).id

    started_at = _started_at(now, request.duration_ms)
    referenced_ids = _referenced_document_ids(
        existing=archive.referenced_document_ids,
        request=request,
        document_id=document_id,
    )

    archive.actor_id = actor.id
    archive.organization_id = actor.organization_id
    archive.client, archive.harness_label = sync_session_provenance(
        client=archive.client,
        harness_label=archive.harness_label,
        incoming=request.client,
    )
    archive.specialist_slug = request.specialist_slug or archive.specialist_slug
    archive.model_id = (
        request.harness.model_id if request.harness is not None else archive.model_id
    )
    archive.cwd = request.cwd or archive.cwd
    archive.repo = _repo_from_cwd(request.cwd) or archive.repo
    archive.branch = request.branch or archive.branch
    archive.title = _title_from_request(request) or archive.title
    archive.started_at = _earliest(archive.started_at, started_at)
    archive.ended_at = (
        now if request.kind in ("final", "session_end") else archive.ended_at
    )
    # When a session ends (clean /exit or the harness closing) we mark it
    # ``ended_at`` so it reports the gray "Inactive" state, but we deliberately
    # leave it in its current group. Sessions are never relocated automatically;
    # archiving to the Archive group is a user-initiated drag.
    # Checkpoint observe must not clobber the waiting state set by turn-ended:
    # when last_turn_ended_at >= last_seen_at the agent is idle between turns.
    if _should_bump_last_seen_from_observe(archive, kind=request.kind):
        archive.last_seen_at = now
    archive.active_document_id = (
        document_id or request.active_document_id or archive.active_document_id
    )
    archive.duration_ms = max(archive.duration_ms or 0, request.duration_ms or 0)
    archive.message_count = max(archive.message_count or 0, len(request.transcript))
    archive.command_count = max(
        archive.command_count or 0,
        len(request.commands_run),
    )
    archive.edit_count = max(archive.edit_count or 0, len(request.files_touched))
    if request.harness is not None:
        archive.input_tokens = request.harness.total_input_tokens
        archive.output_tokens = request.harness.total_output_tokens
        archive.cache_read_tokens = request.harness.total_cache_read_tokens
        archive.cache_write_tokens = request.harness.total_cache_write_tokens
    archive.referenced_document_ids = referenced_ids
    archive.source_metadata = {
        **(archive.source_metadata or {}),
        "kind": request.kind,
        "checkpoint_index": request.checkpoint_index,
        "outcome": request.outcome,
        "summary_points_count": len(request.summary_points),
        "details_sections_count": len(request.details_sections),
        "decisions_count": len(request.decisions),
        "has_structured_payload": bool(
            request.summary_points
            or request.details_sections
            or request.decisions
            or request.outcome
        ),
    }
    archive.updated_at = now
    session.add(archive)
    ingest_observe_events(
        session,
        actor=actor,
        request=request,
        demo=demo,
        fleet_session_id=archive.fleet_session_id,
        now=now,
    )
    return archive


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _should_bump_last_seen_from_observe(
    archive: TaskforceSessionArchive,
    *,
    kind: str,
) -> bool:
    """Whether an observe payload should advance ``last_seen_at``.

    ``final`` / ``session_end`` always bump. ``checkpoint`` skips the bump when
    the Stop hook already marked the session as awaiting the next prompt.
    """

    if kind != "checkpoint":
        return True
    if archive.last_turn_ended_at is None or archive.last_seen_at is None:
        return True
    return _as_utc(archive.last_turn_ended_at) < _as_utc(archive.last_seen_at)


def _started_at(now: datetime, duration_ms: int) -> datetime:
    if duration_ms <= 0:
        return now
    return now - timedelta(milliseconds=duration_ms)


def _earliest(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _repo_from_cwd(cwd: str | None) -> str | None:
    if not cwd:
        return None
    try:
        return PurePath(cwd).name[:255] or None
    except ValueError:
        return None


def _title_from_request(request: TaskforceObserveRequest) -> str | None:
    title = request.summary_points[0] if request.summary_points else request.prompt
    normalized = " ".join((title or "").split())
    return normalized[:_MAX_TITLE] or None


def _referenced_document_ids(
    *,
    existing: list[str],
    request: TaskforceObserveRequest,
    document_id: uuid.UUID | None,
) -> list[str]:
    ids: list[str] = list(existing or [])
    for value in (request.active_document_id, document_id):
        if value is not None:
            ids.append(str(value))
    deduped: list[str] = []
    seen: set[str] = set()
    for value in ids:
        if value and value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped[:50]


def _normalized_events(
    request: TaskforceObserveRequest,
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    """Compatibility helper for normalization unit tests and callers."""

    events = normalized_session_events(request, now=now)
    return [
        {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in event.items()
            if key != "source_event_id"
        }
        for event in events
    ]


# ---- backfill (TF-218) ----------------------------------------------------
# Old sessions predate the archive table: they exist only as ``metrics_event``
# rows grouped by ``payload->>'session_id'``. They already show in the Ledger
# list (metrics-driven) and the detail endpoint falls back to an empty
# transcript, but the list shows a null title/client because those come from
# the archive. This backfill creates best-effort archive rows from the metrics
# payload so old sessions get a readable title + provenance without fabricating
# canonical session events.

_SESSION_ID = MetricsEvent.payload["session_id"].astext
_PROMPT = MetricsEvent.payload["prompt"].astext
_CONSUMED_CLIENT = MetricsEvent.payload["consumed_by_client"].astext
_SPECIALIST_SLUG = MetricsEvent.payload["specialist_slug"].astext


@dataclass(frozen=True)
class ArchiveBackfillReport:
    sessions_seen: int
    archives_created: int
    skipped_existing: int


def backfill_session_archives(
    session: Session,
    *,
    organization_id: uuid.UUID | None = None,
    is_demo: bool | None = None,
    dry_run: bool = True,
) -> ArchiveBackfillReport:
    """Create archive rows for metrics-only sessions that lack one.

    Groups ``metrics_event`` by ``payload->>'session_id'`` (org/demo scoped),
    skips any session that already has a ``taskforce_session_archive`` row, and
    creates a best-effort archive from the metrics payload (title from the
    prompt, client/specialist from the payload, started/ended from the event
    timestamps). Idempotent: re-runs skip already-archived sessions.

    ``dry_run=True`` (default) computes the report and writes nothing — mirrors
    ``observe.py`` shadow mode and the earned-profile compounding job.
    """

    grouped: Any = (
        select(
            _SESSION_ID.label("session_id"),
            MetricsEvent.organization_id.label("organization_id"),
            MetricsEvent.is_demo.label("is_demo"),
            func.min(MetricsEvent.occurred_at).label("first_at"),
            func.max(MetricsEvent.occurred_at).label("last_at"),
            func.max(_PROMPT).label("prompt"),
            func.max(_CONSUMED_CLIENT).label("client"),
            func.max(_SPECIALIST_SLUG).label("specialist_slug"),
        )
        .where(_SESSION_ID.is_not(None))
        .group_by(_SESSION_ID, MetricsEvent.organization_id, MetricsEvent.is_demo)
    )
    if organization_id is not None:
        grouped = grouped.where(MetricsEvent.organization_id == organization_id)
    if is_demo is not None:
        grouped = grouped.where(MetricsEvent.is_demo == is_demo)

    rows = list(session.exec(grouped))

    # Existing archive session_ids, scoped the same way, to skip cheaply.
    existing_stmt: Any = select(TaskforceSessionArchive.session_id)
    if organization_id is not None:
        existing_stmt = existing_stmt.where(
            TaskforceSessionArchive.organization_id == organization_id
        )
    if is_demo is not None:
        existing_stmt = existing_stmt.where(TaskforceSessionArchive.is_demo == is_demo)
    existing: set[str] = set(session.exec(existing_stmt))

    # Resolve the actor per session: the first event's user_id. One query.
    actor_by_session: dict[str, uuid.UUID] = {}
    actor_stmt: Any = (
        select(_SESSION_ID, func.min(col(MetricsEvent.user_id).cast(String)))
        .where(_SESSION_ID.is_not(None))
        .group_by(_SESSION_ID)
    )
    if organization_id is not None:
        actor_stmt = actor_stmt.where(MetricsEvent.organization_id == organization_id)
    if is_demo is not None:
        actor_stmt = actor_stmt.where(MetricsEvent.is_demo == is_demo)
    for sid, actor_text in session.exec(actor_stmt):
        if sid and actor_text:
            actor_by_session[sid] = uuid.UUID(str(actor_text))

    seen = 0
    created = 0
    skipped = 0
    now = _now()
    for row in rows:
        sid = row.session_id
        if not sid:
            continue
        seen += 1
        if sid in existing:
            skipped += 1
            continue
        actor_id = actor_by_session.get(sid)
        if actor_id is None:
            skipped += 1
            continue
        created += 1
        if dry_run:
            continue
        title = " ".join((row.prompt or "").split())[:_MAX_TITLE] or None
        archive = TaskforceSessionArchive(
            session_id=sid,
            actor_id=actor_id,
            organization_id=row.organization_id,
            is_demo=row.is_demo,
            client=row.client,
            specialist_slug=row.specialist_slug,
            harness_label=row.client,
            title=title,
            started_at=row.first_at,
            ended_at=row.last_at,
            imported_at=now,
            created_at=now,
            updated_at=now,
            source_metadata={"backfilled": True, "source": "metrics_event"},
        )
        session.add(archive)
        existing.add(sid)

    if not dry_run:
        session.flush()
    return ArchiveBackfillReport(
        sessions_seen=seen,
        archives_created=created,
        skipped_existing=skipped,
    )
