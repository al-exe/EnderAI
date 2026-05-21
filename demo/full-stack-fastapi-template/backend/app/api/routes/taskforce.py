"""Taskforce hook-driven endpoints.

This module hosts the new server-side surface for hook-based discovery
(TF-175) and, in later phases, observation (TF-178). The route is mounted
under ``/api/v1/v2/taskforce/`` so it lives alongside the existing v2
document + metrics routes for one consistent versioning story.

See ``~/dev/docs/claude-mcp-brainstorm.md`` §3 for the full design.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, SessionDep
from app.core.taskforce.discover import discover as run_discover
from app.models import (
    TaskforceDiscoverRequest,
    TaskforceDiscoverResponse,
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
