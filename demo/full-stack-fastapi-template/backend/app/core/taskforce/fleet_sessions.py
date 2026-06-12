"""Fleet session membership helpers (TF-229)."""

from __future__ import annotations

import re
import uuid

from sqlmodel import Session, col, select

from app.models import TaskforceFleetSession, User, get_datetime_utc

DEFAULT_SESSION_NAME = "Session 1"
_SESSION_NUMBER = re.compile(r"^Session ([1-9][0-9]*)$")


def fleet_sessions_for_actor(
    session: Session,
    actor: User,
    *,
    exclude_id: uuid.UUID | None = None,
) -> list[TaskforceFleetSession]:
    statement = (
        select(TaskforceFleetSession)
        .where(TaskforceFleetSession.actor_id == actor.id)
        .order_by(col(TaskforceFleetSession.created_at), col(TaskforceFleetSession.id))
    )
    if exclude_id is not None:
        statement = statement.where(TaskforceFleetSession.id != exclude_id)
    return list(session.exec(statement).all())


def get_or_create_default_fleet_session(
    session: Session,
    actor: User,
    *,
    exclude_id: uuid.UUID | None = None,
) -> TaskforceFleetSession:
    """Return the actor's named default, otherwise their oldest session."""

    fleet_sessions = fleet_sessions_for_actor(session, actor, exclude_id=exclude_id)
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
        for fleet_session in fleet_sessions_for_actor(session, actor)
        if (match := _SESSION_NUMBER.fullmatch(fleet_session.name))
    ]
    return f"Session {max(numbers, default=0) + 1}"
