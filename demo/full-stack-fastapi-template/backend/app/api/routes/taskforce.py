"""Taskforce hook-driven endpoints.

This module hosts the new server-side surface for hook-based discovery
(TF-175 / TF-176) and, in later phases, observation (TF-178). The route
is mounted under ``/api/v1/v2/taskforce/`` so it lives alongside the
existing v2 document + metrics routes for one consistent versioning
story.

See ``~/dev/docs/claude-mcp-brainstorm.md`` §3 for the full design.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import desc
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.core.taskforce.discover import discover as run_discover
from app.models import (
    METRICS_EVENT_DOCUMENT_CONSULTED,
    MetricsEvent,
    TaskforceDiscoverRequest,
    TaskforceDiscoverResponse,
    TaskforceSessionLogEntry,
    TaskforceSessionLogResponse,
    V2Document,
)

router = APIRouter(prefix="/v2/taskforce", tags=["taskforce"])


@router.post("/discover", response_model=TaskforceDiscoverResponse)
def discover_route(
    session: SessionDep,
    current_user: CurrentUser,
    body: TaskforceDiscoverRequest,
    demo: bool = Query(default=False),
) -> Any:
    """Top 1–3 V2 documents related to ``body.prompt`` from the actor's library.

    Records one ``document.consulted`` metrics event per returned match so
    the dashboard can attribute downstream consultation to a specific
    ``query_id``. Always returns the ``query_id`` — even when the match
    list is empty — so the hook (TF-176) can emit a stable banner.
    """

    response = run_discover(
        session,
        actor=current_user,
        request=body,
        demo=demo,
    )
    session.commit()
    return response


@router.get("/session-log", response_model=TaskforceSessionLogResponse)
def session_log_route(
    session: SessionDep,
    current_user: CurrentUser,
    session_id: str = Query(..., min_length=1, max_length=128),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    """Return the per-session consultation log (TF-176).

    Backs the ``/taskforce`` slash command and the future "Recent activity"
    web widget. Filters ``document.consulted`` events by the ``session_id``
    that the hook embeds in each event's payload, owner-scoped.
    """

    statement = (
        select(MetricsEvent, V2Document)
        .join(V2Document, V2Document.id == MetricsEvent.document_id)
        .where(MetricsEvent.kind == METRICS_EVENT_DOCUMENT_CONSULTED)
        .where(MetricsEvent.user_id == current_user.id)
        .where(MetricsEvent.payload["session_id"].astext == session_id)  # type: ignore[index]
        .order_by(desc(col(MetricsEvent.occurred_at)))
        .limit(limit)
    )

    entries: list[TaskforceSessionLogEntry] = []
    for event, document in session.exec(statement).all():
        payload = event.payload or {}
        entries.append(
            TaskforceSessionLogEntry(
                document_id=document.id,
                title=document.title,
                score=float(payload.get("score") or 0.0),
                confidence_band=payload.get("band") or "low",
                match_reasons=list(payload.get("match_reasons") or []),
                summary_markdown=document.ai_generated_summary
                or document.description
                or "",
                occurred_at=event.occurred_at,
                query_id=str(payload.get("query_id") or ""),
                net_saved_tokens=int(payload.get("net_saved_tokens") or 0),
            )
        )

    return TaskforceSessionLogResponse(session_id=session_id, entries=entries)
