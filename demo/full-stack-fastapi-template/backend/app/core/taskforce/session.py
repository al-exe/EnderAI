"""Tier 2 session entry point (TF-181).

Wraps the existing discover orchestrator and adds a UUID `session_id`
so hookless agents (Codex, Cursor) can correlate their start →
observe call pair through one stable identifier. No server-side state
yet — the agent is responsible for threading the session_id through
subsequent observe calls.

If we later need server-side session lookup (e.g. for a "what was the
suggested pin?" query), we'll add a ``taskforce_session`` table; for
now the session_id lives only on event payloads.
"""

from __future__ import annotations

import uuid

from sqlmodel import Session

from app.core.taskforce.discover import discover as run_discover
from app.models import (
    TaskforceDiscoverRequest,
    TaskforceSessionStartRequest,
    TaskforceSessionStartResponse,
    User,
)


def session_start(
    session: Session,
    *,
    actor: User,
    request: TaskforceSessionStartRequest,
) -> TaskforceSessionStartResponse:
    """Mint a session_id and run discover in one call.

    The returned ``suggested_pin`` is the top match's ``document_id``
    when its ``confidence_band`` is ``"high"`` — high enough that the
    agent should adopt it as the active document without a second
    decision step. For medium / low matches the agent picks one (or
    none) on its own.
    """

    session_id = uuid.uuid4()
    discover_response = run_discover(
        session,
        actor=actor,
        request=TaskforceDiscoverRequest(
            prompt=request.prompt,
            cwd=request.cwd,
            files=list(request.files),
            git_branch=request.git_branch,
            recent_commands=list(request.recent_commands),
            k=request.k,
            min_score=request.min_score,
            session_id=str(session_id),
        ),
        demo=request.demo,
    )

    suggested_pin = None
    if discover_response.matches:
        top = discover_response.matches[0]
        if top.confidence_band == "high":
            suggested_pin = top.document_id

    return TaskforceSessionStartResponse(
        session_id=session_id,
        matches=discover_response.matches,
        suggested_pin=suggested_pin,
    )
