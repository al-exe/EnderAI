"""Active-sessions roster (TF-225).

Gives each session a glanceable view of what its sibling sessions — other
currently-open Claude Code instances for the same actor — are doing right
now. Two consumers share the query in this module:

- ``POST /v2/taskforce/discover`` (hook-driven, every prompt): also records
  a heartbeat for the calling session via :func:`touch_session_heartbeat`.
- ``GET /v2/taskforce/active-sessions`` (frontend presence rail): read-only.

See ``docs/planning/taskforce-active-sessions-roster.md`` for the design.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import desc
from sqlmodel import Session, col, select

from app.core.taskforce.archive import _now, _repo_from_cwd
from app.models import (
    TaskforceActiveSession,
    TaskforceDiscoverRequest,
    TaskforceSessionArchive,
    User,
    V2Document,
)

# Backstop window: a session that hasn't heartbeat in this long is treated as
# abandoned/crashed even if it never got a clean ``ended_at``. Properly-ended
# sessions are excluded outright regardless of this window.
MAX_AGE = timedelta(hours=8)

# Bounds the roster size regardless of how many sessions a user accumulates.
ROSTER_LIMIT = 5


def touch_session_heartbeat(
    session: Session,
    *,
    actor: User,
    request: TaskforceDiscoverRequest,
    demo: bool,
) -> None:
    """Record "this session is still alive" on every ``/discover`` call.

    Creates a minimal archive row if one doesn't exist yet (e.g. the first
    prompt of a session, before any checkpoint has fired) so the session
    shows up in siblings' rosters immediately, with ``active_document_id``
    left null until the first observe.
    """

    if not request.session_id:
        return

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
            client=request.client,
            cwd=request.cwd,
            repo=_repo_from_cwd(request.cwd),
            branch=request.git_branch,
            started_at=now,
            imported_at=now,
            created_at=now,
        )
    else:
        archive.cwd = archive.cwd or request.cwd
        archive.repo = archive.repo or _repo_from_cwd(request.cwd)
        archive.branch = archive.branch or request.git_branch
        archive.client = archive.client or request.client

    archive.last_seen_at = now
    archive.updated_at = now
    session.add(archive)


def get_active_sessions(
    session: Session,
    *,
    actor: User,
    demo: bool,
    exclude_session_id: str | None = None,
    limit: int = ROSTER_LIMIT,
    max_age: timedelta = MAX_AGE,
) -> list[TaskforceActiveSession]:
    """Return the actor's other currently-active sessions, most recent first.

    Scope: ``actor_id = actor``, same org/demo space, ``ended_at IS NULL``
    (cleanly-ended sessions are excluded outright — the ``max_age`` window
    is a backstop for "forgot to /exit", not the primary filter), and
    ``last_seen_at`` within ``max_age``. Capped at ``limit`` rows.
    """

    now = _now()
    cutoff = now - max_age

    statement = (
        select(TaskforceSessionArchive)
        .where(TaskforceSessionArchive.actor_id == actor.id)
        .where(TaskforceSessionArchive.organization_id == actor.organization_id)
        .where(TaskforceSessionArchive.is_demo == demo)
        .where(TaskforceSessionArchive.ended_at.is_(None))
        .where(TaskforceSessionArchive.last_seen_at.is_not(None))
        .where(TaskforceSessionArchive.last_seen_at >= cutoff)
    )
    if exclude_session_id:
        statement = statement.where(
            TaskforceSessionArchive.session_id != exclude_session_id
        )
    statement = statement.order_by(
        desc(TaskforceSessionArchive.last_seen_at)
    ).limit(limit)

    rows = list(session.exec(statement))
    if not rows:
        return []

    doc_ids = {row.active_document_id for row in rows if row.active_document_id}
    documents: dict[uuid.UUID, V2Document] = {}
    if doc_ids:
        documents = {
            doc.id: doc
            for doc in session.exec(
                select(V2Document).where(col(V2Document.id).in_(doc_ids))
            )
        }

    entries: list[TaskforceActiveSession] = []
    for row in rows:
        document = (
            documents.get(row.active_document_id)
            if row.active_document_id
            else None
        )
        last_seen_at = row.last_seen_at
        assert last_seen_at is not None  # filtered above
        minutes_ago = max(0, int((now - last_seen_at).total_seconds() // 60))
        entries.append(
            TaskforceActiveSession(
                session_id=row.session_id,
                cwd=row.cwd,
                branch=row.branch,
                repo=row.repo,
                active_document_id=row.active_document_id,
                title=document.title if document else None,
                summary_markdown=(document.ai_generated_summary or "")
                if document
                else "",
                last_seen_at=last_seen_at,
                minutes_ago=minutes_ago,
            )
        )
    return entries
