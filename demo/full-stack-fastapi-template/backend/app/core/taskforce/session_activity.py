"""Per-turn activity timeline capture (TF-247).

Maintains the append-only ``taskforce_session_activity`` log that backs the
Fleet agent-session detail timeline. One row is created per user prompt on
``/discover`` (the "working on" line as it arrives); the following ``/observe``
backfills ``response_summary`` so each row reads as a single turn.

This is deliberately separate from ``TaskforceSessionArchive``, whose ``title``
and ``transcript_events`` are overwritten every request — that overwrite is
exactly why the timeline could previously only show "now".
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import desc
from sqlmodel import Session, select

from app.models import TaskforceSessionActivity, User

_MAX_PROMPT = 255
_MAX_SUMMARY = 2000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize(text: str | None, limit: int) -> str:
    return " ".join((text or "").split())[:limit]


def _latest_row(
    session: Session,
    *,
    actor: User,
    session_id: str,
    demo: bool,
) -> TaskforceSessionActivity | None:
    return session.exec(
        select(TaskforceSessionActivity)
        .where(TaskforceSessionActivity.session_id == session_id)
        .where(TaskforceSessionActivity.actor_id == actor.id)
        .where(TaskforceSessionActivity.is_demo == demo)
        .order_by(desc(TaskforceSessionActivity.occurred_at))
        .limit(1)
    ).first()


def record_activity_prompt(
    session: Session,
    *,
    actor: User,
    session_id: str,
    prompt: str,
    demo: bool,
    fleet_session_id: uuid.UUID | None,
    now: datetime | None = None,
) -> TaskforceSessionActivity | None:
    """Append one activity row for a new user prompt.

    No-ops when the prompt is empty or identical to this session's most recent
    row, so a ``/discover`` that re-fires without a fresh prompt doesn't create
    a duplicate timeline line.
    """

    text = _normalize(prompt, _MAX_PROMPT)
    if not session_id or not text:
        return None

    latest = _latest_row(session, actor=actor, session_id=session_id, demo=demo)
    if latest is not None and latest.prompt == text and latest.response_summary is None:
        return None

    now = now or _now()
    row = TaskforceSessionActivity(
        session_id=session_id,
        actor_id=actor.id,
        organization_id=actor.organization_id,
        fleet_session_id=fleet_session_id,
        is_demo=demo,
        prompt=text,
        occurred_at=now,
        created_at=now,
    )
    session.add(row)
    return row


def attach_response_summary(
    session: Session,
    *,
    actor: User,
    session_id: str,
    summary: str,
    demo: bool,
) -> TaskforceSessionActivity | None:
    """Backfill ``response_summary`` on this session's most recent row.

    The ``/observe`` that follows a turn carries the agent's work summary; we
    attach it to the latest prompt row so the turn reads ask → response. If
    several observes land in one turn the latest summary wins (overwrite).
    """

    text = _normalize(summary, _MAX_SUMMARY)
    if not session_id or not text:
        return None

    latest = _latest_row(session, actor=actor, session_id=session_id, demo=demo)
    if latest is None:
        return None
    latest.response_summary = text
    session.add(latest)
    return latest
