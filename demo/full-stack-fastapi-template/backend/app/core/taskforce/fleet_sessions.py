"""Session group membership helpers (TF-229)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlmodel import Session, col, select

from app.models import (
    TaskforceFleetSession,
    TaskforceSessionArchive,
    User,
    get_datetime_utc,
)

DEFAULT_SESSION_NAME = "Session 1"
# The user-controlled "Archive" bucket. Agents are never swept here
# automatically — archiving is a deliberate, user-initiated drag (TF). The
# ``is_history`` column name predates the rename and is kept for schema
# stability; the display name is "Archive".
HISTORY_SESSION_NAME = "Archive"
_SESSION_NUMBER = re.compile(r"^Session ([1-9][0-9]*)$")

# How long an agent's last heartbeat can age before it is considered inactive
# (gray "Inactive" state). Inactive agents stay put in their group — they are
# not moved anywhere — until the user archives them. Matches MAX_AGE so an
# agent stays live for a full working session before flipping to Inactive.
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
    """Return the actor's default session group.

    Prefers the session explicitly flagged ``is_default``. When none is flagged
    (e.g. legacy actors, or a brand-new single session), it falls back to the
    conventionally-named default, then the oldest non-history session, and
    *persists* the flag onto that pick so exactly one group is always marked.
    """

    fleet_sessions = fleet_sessions_for_actor(
        session,
        actor,
        exclude_id=exclude_id,
        include_history=False,
    )

    flagged = next(
        (fleet_session for fleet_session in fleet_sessions if fleet_session.is_default),
        None,
    )
    if flagged is not None:
        return flagged

    default = next(
        (
            fleet_session
            for fleet_session in fleet_sessions
            if fleet_session.name == DEFAULT_SESSION_NAME
        ),
        fleet_sessions[0] if fleet_sessions else None,
    )

    now = get_datetime_utc()
    if default is None:
        default = TaskforceFleetSession(
            actor_id=actor.id,
            organization_id=actor.organization_id,
            name=DEFAULT_SESSION_NAME,
            is_default=True,
            created_at=now,
            updated_at=now,
        )
        session.add(default)
        session.flush()
        return default

    # No session was flagged yet — mark the heuristic pick so the badge always
    # points at exactly one group (and a lone session is always the default).
    default.is_default = True
    default.updated_at = now
    session.add(default)
    session.flush()
    return default


def set_default_fleet_session(
    session: Session,
    actor: User,
    target: TaskforceFleetSession,
    *,
    now: datetime | None = None,
) -> None:
    """Mark ``target`` as the actor's sole default, clearing the flag elsewhere."""

    now = now or get_datetime_utc()
    for fleet_session in fleet_sessions_for_actor(
        session, actor, include_history=False
    ):
        should_be_default = fleet_session.id == target.id
        if fleet_session.is_default == should_be_default:
            continue
        fleet_session.is_default = should_be_default
        fleet_session.updated_at = now
        session.add(fleet_session)
    session.flush()


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
    """Bring an inactive agent back to life when the user types in it again.

    Two cases:

    - The agent went **Inactive in place** (``ended_at`` set, still in its own
      group): just clear ``ended_at`` so it reports ``running`` again. It stays
      in the same group — we never relocate a session the user didn't move.
    - The agent was **archived** (sitting in the actor's Archive group): clear
      ``ended_at`` *and* pull it back into the default working group, since the
      Archive is for sessions the user has set aside.
    """

    history = history_fleet_session_for_actor(session, actor)
    in_archive = history is not None and archive.fleet_session_id == history.id
    if archive.ended_at is None and not in_archive:
        return

    archive.ended_at = None
    if in_archive:
        archive.fleet_session_id = get_or_create_default_fleet_session(
            session, actor
        ).id
    archive.updated_at = now or get_datetime_utc()
    session.add(archive)
