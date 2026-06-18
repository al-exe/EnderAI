"""Session inbox: queue prompts for idle agents and claim them from Stop hooks.

The Sessions "Reply to agent" box enqueues a :class:`TaskforceSessionInboxMessage`
for a session the user owns. When that agent next goes idle, its Stop hook
(Claude Code ``stop.sh`` / Codex ``observe.sh``) calls :func:`claim_inbox_message`
to atomically pop the oldest undelivered row and re-inject it as a fresh user
prompt via the harness ``{"decision":"block","reason":...}`` contract.

Ownership is enforced everywhere by ``actor_id`` plus the archive unique key
``(organization_id, is_demo, session_id)`` — a user can only enqueue to / claim
from sessions they own. Cursor agents have no Stop-hook injection surface and so
never claim; their messages would simply sit pending, which is why the Sessions
UI only exposes the reply box for Claude and Codex agents.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc
from sqlmodel import Session, select

from app.core.taskforce.archive import _now
from app.models import (
    TaskforceSessionArchive,
    TaskforceSessionInboxMessage,
    User,
)


def _archive_for_session(
    session: Session,
    *,
    actor: User,
    session_id: str,
    demo: bool,
) -> TaskforceSessionArchive | None:
    """Resolve the actor's archive row for ``session_id`` (the inbox owner check)."""

    return session.exec(
        select(TaskforceSessionArchive)
        .where(TaskforceSessionArchive.actor_id == actor.id)
        .where(TaskforceSessionArchive.organization_id == actor.organization_id)
        .where(TaskforceSessionArchive.is_demo == demo)
        .where(TaskforceSessionArchive.session_id == session_id)
    ).first()


def enqueue_inbox_message(
    session: Session,
    *,
    actor: User,
    session_id: str,
    demo: bool,
    body: str,
) -> TaskforceSessionInboxMessage | None:
    """Queue a prompt for an idle agent. ``None`` when the session is unknown.

    The caller (route) translates ``None`` into a 404 — we never create an inbox
    for a session the user does not own.
    """

    archive = _archive_for_session(
        session, actor=actor, session_id=session_id, demo=demo
    )
    if archive is None:
        return None

    message = TaskforceSessionInboxMessage(
        session_id=session_id,
        actor_id=actor.id,
        organization_id=actor.organization_id,
        is_demo=demo,
        body=body.strip(),
    )
    session.add(message)
    return message


def list_pending_inbox_messages(
    session: Session,
    *,
    actor: User,
    session_id: str,
    demo: bool,
) -> list[TaskforceSessionInboxMessage]:
    """Undelivered messages for a session, oldest first (delivery order)."""

    return list(
        session.exec(
            select(TaskforceSessionInboxMessage)
            .where(TaskforceSessionInboxMessage.actor_id == actor.id)
            .where(
                TaskforceSessionInboxMessage.organization_id == actor.organization_id
            )
            .where(TaskforceSessionInboxMessage.is_demo == demo)
            .where(TaskforceSessionInboxMessage.session_id == session_id)
            .where(TaskforceSessionInboxMessage.delivered_at.is_(None))
            .order_by(TaskforceSessionInboxMessage.created_at)
        )
    )


def claim_inbox_message(
    session: Session,
    *,
    actor: User,
    session_id: str,
    demo: bool,
    now: datetime | None = None,
) -> TaskforceSessionInboxMessage | None:
    """Atomically pop the oldest undelivered message for a session, or ``None``.

    Uses ``FOR UPDATE SKIP LOCKED`` so two concurrent Stop-hook claims (or a hook
    racing a retry) can never grab the same row — each message is injected exactly
    once. Stamps ``delivered_at`` on the claimed row before returning it.
    """

    now = now or _now()
    statement = (
        select(TaskforceSessionInboxMessage)
        .where(TaskforceSessionInboxMessage.actor_id == actor.id)
        .where(TaskforceSessionInboxMessage.organization_id == actor.organization_id)
        .where(TaskforceSessionInboxMessage.is_demo == demo)
        .where(TaskforceSessionInboxMessage.session_id == session_id)
        .where(TaskforceSessionInboxMessage.delivered_at.is_(None))
        .order_by(TaskforceSessionInboxMessage.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    message = session.exec(statement).first()
    if message is None:
        return None

    message.delivered_at = now
    session.add(message)
    return message
