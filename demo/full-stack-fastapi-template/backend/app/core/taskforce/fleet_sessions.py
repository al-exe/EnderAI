"""Fleet session membership helpers (TF-229)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlmodel import Session, col, select

from app.models import TaskforceFleetSession, TaskforceSessionArchive, User, get_datetime_utc

DEFAULT_SESSION_NAME = "Session 1"
HISTORY_SESSION_NAME = "History"
_SESSION_NUMBER = re.compile(r"^Session ([1-9][0-9]*)$")

# Inactive agents older than this window are swept into History on fleet reads.
# 8h keeps an agent in its live fleet session for a full working session before
# it ages into History (matches FLEET_RUNNING_WINDOW / MAX_AGE).
INACTIVE_WINDOW_MINUTES = 8 * 60


def fleet_sessions_for_actor(
    session: Session,
    actor: User,
    *,
    exclude_id: uuid.UUID | None = None,
    include_history: bool = True,
) -> list[TaskforceFleetSession]:
    statement = (
        select(TaskforceFleetSession)
        .where(TaskforceFleetSession.actor_id == actor.id)
        .order_by(col(TaskforceFleetSession.created_at), col(TaskforceFleetSession.id))
    )
    if exclude_id is not None:
        statement = statement.where(TaskforceFleetSession.id != exclude_id)
    if not include_history:
        statement = statement.where(TaskforceFleetSession.is_history.is_(False))
    return list(session.exec(statement).all())


def history_fleet_session_for_actor(
    session: Session,
    actor: User,
) -> TaskforceFleetSession | None:
    return session.exec(
        select(TaskforceFleetSession)
        .where(TaskforceFleetSession.actor_id == actor.id)
        .where(TaskforceFleetSession.is_history.is_(True))
        .limit(1)
    ).first()


def get_or_create_history_fleet_session(
    session: Session,
    actor: User,
) -> TaskforceFleetSession:
    existing = history_fleet_session_for_actor(session, actor)
    if existing is not None:
        return existing

    now = get_datetime_utc()
    history = TaskforceFleetSession(
        actor_id=actor.id,
        organization_id=actor.organization_id,
        name=HISTORY_SESSION_NAME,
        is_history=True,
        created_at=now,
        updated_at=now,
    )
    session.add(history)
    session.flush()
    return history


def get_or_create_default_fleet_session(
    session: Session,
    actor: User,
    *,
    exclude_id: uuid.UUID | None = None,
) -> TaskforceFleetSession:
    """Return the actor's named default, otherwise their oldest non-history session."""

    fleet_sessions = fleet_sessions_for_actor(
        session,
        actor,
        exclude_id=exclude_id,
        include_history=False,
    )
    default = next(
        (
            fleet_session
            for fleet_session in fleet_sessions
            if fleet_session.name == DEFAULT_SESSION_NAME
        ),
        fleet_sessions[0] if fleet_sessions else None,
    )
    if default is not None:
        return default

    now = get_datetime_utc()
    default = TaskforceFleetSession(
        actor_id=actor.id,
        organization_id=actor.organization_id,
        name=DEFAULT_SESSION_NAME,
        created_at=now,
        updated_at=now,
    )
    session.add(default)
    session.flush()
    return default


def next_fleet_session_name(session: Session, actor: User) -> str:
    """Return the next unused conventional name: Session 1, Session 2, ..."""

    numbers = [
        int(match.group(1))
        for fleet_session in fleet_sessions_for_actor(
            session, actor, include_history=False
        )
        if (match := _SESSION_NUMBER.fullmatch(fleet_session.name))
    ]
    return f"Session {max(numbers, default=0) + 1}"


def _minutes_ago(now: datetime, value: datetime) -> int:
    normalized = value
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    return max(
        0, int((now - normalized.astimezone(timezone.utc)).total_seconds() // 60)
    )


def archive_is_inactive(
    archive: TaskforceSessionArchive,
    *,
    now: datetime,
) -> bool:
    if archive.ended_at is not None:
        return True
    last_seen_at = archive.last_seen_at
    if last_seen_at is None:
        return True
    return _minutes_ago(now, last_seen_at) >= INACTIVE_WINDOW_MINUTES


def move_archive_to_history(
    session: Session,
    archive: TaskforceSessionArchive,
    actor: User,
    *,
    now: datetime | None = None,
) -> None:
    history = get_or_create_history_fleet_session(session, actor)
    if archive.fleet_session_id == history.id:
        return
    archive.fleet_session_id = history.id
    archive.updated_at = now or get_datetime_utc()
    session.add(archive)


def resurrect_archive_from_history(
    session: Session,
    archive: TaskforceSessionArchive,
    actor: User,
    *,
    now: datetime | None = None,
) -> None:
    """Return a live agent session to the actor's default Fleet session."""

    history = history_fleet_session_for_actor(session, actor)
    was_inactive = archive.ended_at is not None or (
        history is not None and archive.fleet_session_id == history.id
    )
    if not was_inactive:
        return

    archive.ended_at = None
    archive.fleet_session_id = get_or_create_default_fleet_session(session, actor).id
    archive.updated_at = now or get_datetime_utc()
    session.add(archive)


def reconcile_inactive_fleet_membership(
    session: Session,
    actor: User,
    *,
    now: datetime | None = None,
) -> None:
    """Sweep inactive agent archives into the actor's History session."""

    now = now or get_datetime_utc()
    history = get_or_create_history_fleet_session(session, actor)
    archives = session.exec(
        select(TaskforceSessionArchive)
        .where(TaskforceSessionArchive.actor_id == actor.id)
        .where(TaskforceSessionArchive.fleet_session_id != history.id)
    ).all()
    changed = False
    for archive in archives:
        if not archive_is_inactive(archive, now=now):
            continue
        archive.fleet_session_id = history.id
        archive.updated_at = now
        session.add(archive)
        changed = True
    if changed:
        session.flush()
