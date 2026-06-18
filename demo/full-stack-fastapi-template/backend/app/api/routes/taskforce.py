"""Taskforce hook-driven endpoints.

This module hosts the new server-side surface for hook-based discovery
(TF-175 / TF-176) and, in later phases, observation (TF-178). The route
is mounted under ``/api/v1/v2/taskforce/`` so it lives alongside the
existing v2 document + metrics routes for one consistent versioning
story.

See ``~/dev/docs/claude-mcp-brainstorm.md`` §3 for the full design.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import desc
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.core.metrics.ledger import ledger_session_detail, ledger_sessions
from app.core.metrics.queries import taskforce_session_savings
from app.core.taskforce.active_sessions import (
    active_sessions_for_actor,
    get_active_sessions,
    history_agents_for_actor,
    mark_session_turn_ended,
    register_session_heartbeat,
)
from app.core.taskforce.discover import discover as run_discover
from app.core.taskforce.discover import fleet_session_context
from app.core.taskforce.fleet_sessions import (
    archive_is_inactive,
    get_or_create_default_fleet_session,
    get_or_create_history_fleet_session,
    next_fleet_session_name,
    set_default_fleet_session,
)
from app.core.taskforce.installer import (
    build_codex_hook_installer,
    build_cursor_hook_installer,
    build_hook_installer,
)
from app.core.taskforce.observe import observe as run_observe
from app.core.taskforce.session import session_start as run_session_start
from app.core.taskforce.session_activity import session_events_for_actor
from app.core.v2_documents import apply_v2_document_update, get_v2_document_for_actor
from app.models import (
    METRICS_EVENT_DOCUMENT_CONSULTED,
    LedgerDocRefPublic,
    LedgerRawTranscriptPublic,
    LedgerResponse,
    LedgerSessionDetailPublic,
    LedgerSessionRowPublic,
    LedgerTranscriptEventPublic,
    MetricsEvent,
    TaskforceActiveSessionsResponse,
    TaskforceDiscoverRequest,
    TaskforceDiscoverResponse,
    TaskforceFleetAgentPublic,
    TaskforceFleetResponse,
    TaskforceFleetSession,
    TaskforceFleetSessionAssignment,
    TaskforceFleetSessionCreate,
    TaskforceFleetSessionPublic,
    TaskforceFleetSessionUpdate,
    TaskforceObserveRequest,
    TaskforceObserveResponse,
    TaskforceReferenceRequest,
    TaskforceReferenceResponse,
    TaskforceSessionActivityResponse,
    TaskforceSessionArchive,
    TaskforceSessionContextResponse,
    TaskforceSessionEvent,
    TaskforceSessionEventPublic,
    TaskforceSessionHeartbeatRequest,
    TaskforceSessionLogEntry,
    TaskforceSessionLogResponse,
    TaskforceSessionSavingsResponse,
    TaskforceSessionStartRequest,
    TaskforceSessionStartResponse,
    TaskforceSessionTurnEndedRequest,
    V2Document,
    V2DocumentDetailsSection,
    V2DocumentUpdate,
    get_datetime_utc,
)

router = APIRouter(prefix="/v2/taskforce", tags=["taskforce"])

REFERENCED_BY_ANCHOR_ID = "referenced-by"
MAX_REFERENCE_ROWS = 200
PROMPT_PREVIEW_CHARS = 120


@router.get("/install.sh", include_in_schema=False)
def install_taskforce_hooks() -> Response:
    """Serve the public, self-contained Claude Code hook installer."""

    return Response(
        content=build_hook_installer(),
        media_type="text/x-shellscript",
        headers={
            "Cache-Control": "public, max-age=300",
            "Content-Disposition": 'inline; filename="taskforce-install.sh"',
        },
    )


@router.get("/install-codex.sh", include_in_schema=False)
def install_taskforce_codex_hooks() -> Response:
    """Serve the public, self-contained Codex hook installer."""

    return Response(
        content=build_codex_hook_installer(),
        media_type="text/x-shellscript",
        headers={
            "Cache-Control": "public, max-age=300",
            "Content-Disposition": 'inline; filename="taskforce-codex-install.sh"',
        },
    )


@router.get("/install-cursor.sh", include_in_schema=False)
def install_taskforce_cursor_hooks() -> Response:
    """Serve the public, self-contained Cursor hook installer."""

    return Response(
        content=build_cursor_hook_installer(),
        media_type="text/x-shellscript",
        headers={
            "Cache-Control": "public, max-age=300",
            "Content-Disposition": 'inline; filename="taskforce-cursor-install.sh"',
        },
    )


def _format_reference_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _prompt_preview(prompt: str) -> str:
    normalized = " ".join(prompt.split())
    if len(normalized) <= PROMPT_PREVIEW_CHARS:
        return normalized
    return normalized[: PROMPT_PREVIEW_CHARS - 3].rstrip() + "..."


def _reference_row(body: TaskforceReferenceRequest, occurred_at: datetime) -> str:
    timestamp = _format_reference_timestamp(occurred_at)
    session_short = str(body.session_id)[:8]
    return (
        f"- **{timestamp}** · session `{session_short}` · "
        f'"{_prompt_preview(body.user_prompt)}"'
    )


def _document_details_sections(document: V2Document) -> list[V2DocumentDetailsSection]:
    return [
        V2DocumentDetailsSection.model_validate(section)
        for section in document.details_markdown_sections or []
    ]


def _append_reference_row(
    document: V2Document, row: str
) -> list[V2DocumentDetailsSection]:
    sections = _document_details_sections(document)
    referenced_by = next(
        (
            section
            for section in sections
            if section.anchor_id == REFERENCED_BY_ANCHOR_ID
        ),
        None,
    )
    if referenced_by is None:
        referenced_by = V2DocumentDetailsSection(
            anchor_id=REFERENCED_BY_ANCHOR_ID,
            markdown="",
        )
        sections.append(referenced_by)

    rows = [line for line in referenced_by.markdown.splitlines() if line.strip()]
    rows.append(row)
    referenced_by.markdown = "\n".join(rows[-MAX_REFERENCE_ROWS:])
    return sections


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


@router.get("/active-sessions", response_model=TaskforceActiveSessionsResponse)
def active_sessions_route(
    session: SessionDep,
    current_user: CurrentUser,
    demo: bool = Query(default=False),
    session_id: str | None = Query(default=None),
) -> Any:
    """The actor's other currently-active sessions (TF-225 presence rail).

    Read-only counterpart to the ``active_sessions`` roster returned by
    ``/discover`` — used by the frontend, which doesn't run a discover-style
    query on every poll. Pass ``session_id`` to exclude that session from
    its own roster (e.g. a Claude Code session polling on its own behalf).
    """

    active_sessions = get_active_sessions(
        session,
        actor=current_user,
        demo=demo,
        exclude_session_id=session_id,
    )
    return TaskforceActiveSessionsResponse(active_sessions=active_sessions)


@router.post("/reference", response_model=TaskforceReferenceResponse)
def reference_route(
    session: SessionDep,
    current_user: CurrentUser,
    body: TaskforceReferenceRequest,
    demo: bool = Query(default=False),
) -> Any:
    """Append a bounded "referenced by" row to each accessible document.

    This is intentionally side-effect-only: callers use it after injecting
    prior-work context so the consulted documents show which sessions reused
    them. ACL misses are reported as skipped instead of failing the batch.
    """

    row = _reference_row(body, body.occurred_at or get_datetime_utc())
    updated_document_ids: list[uuid.UUID] = []
    skipped_document_ids: list[uuid.UUID] = []

    for document_id in body.document_ids:
        document = get_v2_document_for_actor(
            session, current_user, document_id, demo=demo
        )
        if document is None:
            skipped_document_ids.append(document_id)
            continue

        next_sections = _append_reference_row(document, row)
        apply_v2_document_update(
            document,
            V2DocumentUpdate(details_markdown_sections=next_sections),
        )
        session.add(document)
        session.commit()
        updated_document_ids.append(document_id)

    return TaskforceReferenceResponse(
        updated_document_ids=updated_document_ids,
        skipped_document_ids=skipped_document_ids,
    )


@router.post("/session/heartbeat", status_code=204)
def session_heartbeat_route(
    session: SessionDep,
    current_user: CurrentUser,
    body: TaskforceSessionHeartbeatRequest,
) -> Response:
    """Register a hook-driven session before its first user prompt."""

    register_session_heartbeat(
        session,
        actor=current_user,
        session_id=body.session_id,
        demo=body.demo,
        client=body.client,
        cwd=body.cwd,
        branch=body.git_branch,
        model_id=body.model_id,
    )
    session.commit()
    return Response(status_code=204)


@router.post("/session/turn-ended", status_code=204)
def session_turn_ended_route(
    session: SessionDep,
    current_user: CurrentUser,
    body: TaskforceSessionTurnEndedRequest,
) -> Response:
    """Mark a session's turn as finished so Sessions shows "awaiting prompt".

    Driven by the Claude Code Stop hook. A no-op (still 204) when the session
    has no archive row yet — the next prompt's heartbeat will create one.
    """

    mark_session_turn_ended(
        session,
        actor=current_user,
        session_id=body.session_id,
        demo=body.demo,
    )
    session.commit()
    return Response(status_code=204)


@router.post(
    "/session/start",
    response_model=TaskforceSessionStartResponse,
    status_code=201,
)
def session_start_route(
    session: SessionDep,
    current_user: CurrentUser,
    body: TaskforceSessionStartRequest,
) -> Any:
    """Tier 2 entry point for hookless agents (TF-181).

    Mints a session_id and runs discovery in one call. The agent
    threads the returned ``session_id`` through every subsequent
    ``taskforce_session_observe`` (i.e. POST /observe) call so the
    backend can correlate them.

    ``suggested_pin`` is non-null when the top match cleared the
    high-confidence band; the agent should adopt it as the active
    document without a second decision step.
    """

    response = run_session_start(
        session,
        actor=current_user,
        request=body,
    )
    session.commit()
    return response


@router.post(
    "/observe",
    response_model=TaskforceObserveResponse,
    status_code=202,
)
async def observe_route(
    session: SessionDep,
    current_user: CurrentUser,
    body: TaskforceObserveRequest,
    demo: bool = Query(default=False),
) -> Any:
    """Server-side observation entry point (TF-178 / Phase 4).

    Called by the Stop hook (``kind: "final"``) and the PostToolUse
    hook (``kind: "checkpoint"``). The handler:
      * runs a deterministic materiality check (the only skip path)
      * for any material session, patches the active document (or creates a
        fresh one) so the shared-context feed fills in — content comes from
        the client's structured fields, the haiku summarizer when enabled +
        affordable, or a deterministic free digest as the floor
      * ``TASKFORCE_OBSERVE_SHADOW=1`` no longer blocks the write; it only
        disables the paid haiku enrichment (writes stay on the free path)
      * records ``tokens.consumed`` events for the summarizer and the
        harness-reported session totals
    Returns a structured envelope so the hook can log + the dashboard
    can attribute. Failures never propagate; the hook should treat any
    non-2xx as "skip".
    """

    response = await run_observe(
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


@router.get("/session-activity", response_model=TaskforceSessionActivityResponse)
def session_activity_route(
    session: SessionDep,
    current_user: CurrentUser,
    session_id: str = Query(..., min_length=1, max_length=128),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    """Return the canonical full session timeline, newest-first and owner-scoped."""

    rows = session_events_for_actor(
        session,
        actor=current_user,
        session_id=session_id,
        limit=limit,
    )

    ledger_available = current_user.organization_id is not None
    entries = [
        TaskforceSessionEventPublic(
            id=row.id,
            kind=row.kind,  # type: ignore[arg-type]
            occurred_at=row.occurred_at,
            role=row.role,
            who=row.who,
            text=row.text,
            cmd=row.cmd,
            exit_code=row.exit_code,
            output=row.output,
            file=row.file,
            added=row.added,
            removed=row.removed,
            note=row.note,
            repo=row.repo,
            ledger_href=_activity_ledger_href(row) if ledger_available else None,
        )
        for row in rows
    ]
    return TaskforceSessionActivityResponse(session_id=session_id, entries=entries)


def _activity_ledger_href(row: TaskforceSessionEvent) -> str:
    """Deep-link to this exact canonical event in the Ledger."""

    return f"/v2/ledger?session_id={row.session_id}&event_id={row.id}"


@router.get("/session-savings", response_model=TaskforceSessionSavingsResponse)
def session_savings_route(
    session: SessionDep,
    current_user: CurrentUser,
    session_id: str = Query(..., min_length=1, max_length=128),
    pricing_model_id: str | None = Query(default=None, min_length=1, max_length=128),
) -> Any:
    """Return aggregate net savings for a single Taskforce session."""

    savings = taskforce_session_savings(
        session,
        user_id=current_user.id,
        session_id=session_id,
        pricing_model_id=pricing_model_id,
    )
    return TaskforceSessionSavingsResponse(
        session_id=savings.session_id,
        doc_count=savings.doc_count,
        net_saved_tokens=savings.net_saved_tokens,
        usd_saved=savings.usd_saved,
        pricing_model_id=savings.pricing_model_id,
        occurred_at_first=savings.occurred_at_first,
        occurred_at_last=savings.occurred_at_last,
        specialist_slug=savings.specialist_slug,
        specialist_name=savings.specialist_name,
    )


def _fleet_session_for_actor(
    session: SessionDep,
    *,
    actor_id: uuid.UUID,
    fleet_session_id: uuid.UUID,
) -> TaskforceFleetSession:
    fleet_session = session.get(TaskforceFleetSession, fleet_session_id)
    if fleet_session is None or fleet_session.actor_id != actor_id:
        raise HTTPException(status_code=404, detail="Session group not found")
    return fleet_session


def _fleet_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Session group name is required")
    return name


@router.get("/fleet", response_model=TaskforceFleetResponse)
def fleet_route(
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """Group the current actor's active-session roster into session groups."""

    # No automatic sweep: inactive agents stay in their group (shown gray) until
    # the user archives them. We only ensure the Archive group exists.
    history = get_or_create_history_fleet_session(session, current_user)

    # Guarantee exactly one non-history group is flagged default so the badge —
    # and "new agents join here" — always has a target (incl. a lone session).
    non_history = session.exec(
        select(TaskforceFleetSession)
        .where(TaskforceFleetSession.actor_id == current_user.id)
        .where(TaskforceFleetSession.is_history.is_(False))
    ).all()
    if non_history and not any(item.is_default for item in non_history):
        get_or_create_default_fleet_session(session, current_user)
    session.commit()

    fleet_sessions = list(
        session.exec(
            select(TaskforceFleetSession)
            .where(TaskforceFleetSession.actor_id == current_user.id)
            .order_by(
                col(TaskforceFleetSession.is_history),
                col(TaskforceFleetSession.created_at),
            )
        ).all()
    )
    active_agents = active_sessions_for_actor(session, actor=current_user)
    history_agents = history_agents_for_actor(session, actor=current_user)
    agents_by_fleet: dict[uuid.UUID, list[Any]] = {history.id: history_agents}
    visible_fleet_ids = {fleet_session.id for fleet_session in fleet_sessions}
    for agent in active_agents:
        if agent.fleet_session_id not in visible_fleet_ids:
            continue
        if agent.fleet_session_id == history.id:
            continue
        agents_by_fleet.setdefault(agent.fleet_session_id, []).append(agent)

    return TaskforceFleetResponse(
        fleet_sessions=[
            TaskforceFleetSessionPublic(
                id=fleet_session.id,
                name=fleet_session.name,
                is_history=fleet_session.is_history,
                is_default=fleet_session.is_default,
                created_at=fleet_session.created_at,
                updated_at=fleet_session.updated_at,
                agents=agents_by_fleet.get(fleet_session.id, []),
            )
            for fleet_session in fleet_sessions
        ]
    )


@router.get(
    "/fleet/{fleet_session_id}/context",
    response_model=TaskforceSessionContextResponse,
)
def fleet_session_context_route(
    session: SessionDep,
    current_user: CurrentUser,
    fleet_session_id: uuid.UUID,
    demo: bool = Query(default=False),
) -> Any:
    """Shared-context feed for one session group (Sessions drawer).

    Read-only: reuses the document-discovery corpus scoped to this group
    rather than a bespoke per-session notes table.
    """

    fleet_session = _fleet_session_for_actor(
        session,
        actor_id=current_user.id,
        fleet_session_id=fleet_session_id,
    )
    return fleet_session_context(
        session,
        actor=current_user,
        fleet_session=fleet_session,
        demo=demo,
    )


@router.post(
    "/fleet",
    response_model=TaskforceFleetSessionPublic,
    status_code=201,
)
def create_fleet_session_route(
    session: SessionDep,
    current_user: CurrentUser,
    _body: TaskforceFleetSessionCreate | None = None,
) -> Any:
    """Create an auto-named session owned by the current actor."""

    fleet_session = TaskforceFleetSession(
        actor_id=current_user.id,
        organization_id=current_user.organization_id,
        name=next_fleet_session_name(session, current_user),
    )
    session.add(fleet_session)
    session.commit()
    session.refresh(fleet_session)
    return TaskforceFleetSessionPublic(
        id=fleet_session.id,
        name=fleet_session.name,
        is_history=fleet_session.is_history,
        is_default=fleet_session.is_default,
        created_at=fleet_session.created_at,
        updated_at=fleet_session.updated_at,
        agents=[],
    )


@router.patch("/fleet/{fleet_session_id}", response_model=TaskforceFleetSessionPublic)
def update_fleet_session_route(
    session: SessionDep,
    current_user: CurrentUser,
    fleet_session_id: uuid.UUID,
    body: TaskforceFleetSessionUpdate,
) -> Any:
    """Rename one session group, or mark it the actor's default."""

    fleet_session = _fleet_session_for_actor(
        session,
        actor_id=current_user.id,
        fleet_session_id=fleet_session_id,
    )
    if fleet_session.is_history:
        if body.is_default:
            raise HTTPException(status_code=422, detail="History cannot be the default")
        raise HTTPException(status_code=422, detail="History cannot be renamed")
    if body.name is not None:
        fleet_session.name = _fleet_name(body.name)
    if body.is_default:
        # Exactly one default: this flips the flag here and clears it elsewhere.
        set_default_fleet_session(session, current_user, fleet_session)
    fleet_session.updated_at = get_datetime_utc()
    session.add(fleet_session)
    session.commit()
    session.refresh(fleet_session)
    agents = [
        agent
        for agent in active_sessions_for_actor(session, actor=current_user)
        if agent.fleet_session_id == fleet_session.id
    ]
    return TaskforceFleetSessionPublic(
        id=fleet_session.id,
        name=fleet_session.name,
        is_history=fleet_session.is_history,
        is_default=fleet_session.is_default,
        created_at=fleet_session.created_at,
        updated_at=fleet_session.updated_at,
        agents=agents,
    )


@router.delete("/fleet/{fleet_session_id}", status_code=204)
def delete_fleet_session_route(
    session: SessionDep,
    current_user: CurrentUser,
    fleet_session_id: uuid.UUID,
) -> Response:
    """Delete a session, moving its agents to the actor's default session."""

    fleet_session = _fleet_session_for_actor(
        session,
        actor_id=current_user.id,
        fleet_session_id=fleet_session_id,
    )
    if fleet_session.is_history:
        raise HTTPException(status_code=422, detail="History cannot be deleted")
    members = session.exec(
        select(TaskforceSessionArchive)
        .where(TaskforceSessionArchive.actor_id == current_user.id)
        .where(TaskforceSessionArchive.fleet_session_id == fleet_session.id)
    ).all()
    replacement = get_or_create_default_fleet_session(
        session,
        current_user,
        exclude_id=fleet_session.id,
    )
    history = get_or_create_history_fleet_session(session, current_user)
    now = get_datetime_utc()
    for member in members:
        if archive_is_inactive(member, now=now):
            member.fleet_session_id = history.id
        else:
            member.fleet_session_id = replacement.id
        session.add(member)
    session.delete(fleet_session)
    session.commit()
    return Response(status_code=204)


@router.patch(
    "/session/{session_id}",
    response_model=TaskforceFleetAgentPublic,
)
def assign_fleet_session_route(
    session: SessionDep,
    current_user: CurrentUser,
    session_id: str,
    body: TaskforceFleetSessionAssignment,
) -> Any:
    """Move an agent between session groups and/or rename its session label."""

    if body.fleet_session_id is None and body.display_name is None:
        raise HTTPException(
            status_code=422,
            detail="Provide fleet_session_id and/or display_name",
        )

    archive = session.exec(
        select(TaskforceSessionArchive)
        .where(TaskforceSessionArchive.actor_id == current_user.id)
        .where(TaskforceSessionArchive.session_id == session_id)
    ).first()
    if archive is None:
        raise HTTPException(status_code=404, detail="Taskforce session not found")

    if body.display_name is not None:
        archive.display_name = body.display_name.strip()
        archive.updated_at = get_datetime_utc()
        session.add(archive)

    if body.fleet_session_id is not None:
        agent = next(
            (
                item
                for item in active_sessions_for_actor(session, actor=current_user)
                if item.session_id == session_id
            ),
            None,
        )
        if agent is None:
            raise HTTPException(
                status_code=404, detail="Active Taskforce session not found"
            )

        _fleet_session_for_actor(
            session,
            actor_id=current_user.id,
            fleet_session_id=body.fleet_session_id,
        )
        destination = session.get(TaskforceFleetSession, body.fleet_session_id)
        assert destination is not None
        # Moving into the Archive group is an explicit, user-initiated action —
        # this is the only way a session reaches Archive. (Typing in an archived
        # session resurrects it back out; see resurrect_archive_from_history.)

        archive.fleet_session_id = body.fleet_session_id
        archive.updated_at = get_datetime_utc()
        session.add(archive)
        session.commit()
        agent.fleet_session_id = body.fleet_session_id
        if destination.is_history:
            agent.status = "inactive"
        if body.display_name is not None:
            agent.display_name = archive.display_name or agent.display_name
        return agent

    session.commit()
    agents = active_sessions_for_actor(session, actor=current_user)
    agent = next((item for item in agents if item.session_id == session_id), None)
    if agent is not None:
        if body.display_name is not None:
            agent.display_name = archive.display_name or agent.display_name
        return agent

    history_agents = history_agents_for_actor(session, actor=current_user)
    history_agent = next(
        (item for item in history_agents if item.session_id == session_id),
        None,
    )
    if history_agent is not None:
        if body.display_name is not None:
            history_agent.display_name = (
                archive.display_name or history_agent.display_name
            )
        return history_agent

    raise HTTPException(
        status_code=404, detail="Taskforce session not found in Sessions"
    )


def _ledger_response_from_page(
    *,
    organization_id: uuid.UUID | None,
    page: Any,
) -> LedgerResponse:
    rows = [_ledger_row_public(row) for row in page.rows]
    return LedgerResponse(
        organization_id=organization_id,
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        rows=rows,
    )


def _ledger_row_public(row: Any) -> LedgerSessionRowPublic:
    return LedgerSessionRowPublic(
        session_id=row.session_id,
        actor_id=row.actor_id,
        actor_name=row.actor_name,
        client=row.client,
        specialist_slug=row.specialist_slug,
        specialist_name=row.specialist_name,
        specialist_href=(
            f"/v2/agents/{row.specialist_slug}" if row.specialist_slug else None
        ),
        documents=[
            LedgerDocRefPublic(
                document_id=doc.document_id,
                title=doc.title,
                href=f"/v2/library/{doc.document_id}",
            )
            for doc in row.documents
        ],
        kinds=row.kinds,
        net_saved_tokens=row.net_saved_tokens,
        usd_amount=row.usd_amount,
        event_count=row.event_count,
        cross_boundary=row.cross_boundary,
        occurred_at_first=row.occurred_at_first,
        occurred_at_last=row.occurred_at_last,
        title=row.title,
        short_session_id=row.session_id[:8],
        actor_handle=row.actor_handle,
        harness_label=row.harness_label,
        harness_version=row.harness_version,
        model_id=row.model_id,
        repo=row.repo,
        branch=row.branch,
        cwd=row.cwd,
        started_at=row.started_at,
        ended_at=row.ended_at,
        duration_ms=row.duration_ms,
        imported_at=row.imported_at,
        message_count=row.message_count,
        command_count=row.command_count,
        edit_count=row.edit_count,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        cache_read_tokens=row.cache_read_tokens,
        cache_write_tokens=row.cache_write_tokens,
        source=row.source,
        transcript_available=row.transcript_available,
    )


@router.get("/documents/{document_id}/sessions", response_model=LedgerResponse)
def document_sessions_route(
    session: SessionDep,
    current_user: CurrentUser,
    document_id: uuid.UUID,
    demo: bool = Query(default=False),
    limit: int = Query(default=10, ge=1, le=MAX_REFERENCE_ROWS),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """Sessions that produced or consulted one document (TF-209 / P2).

    This powers the quiet "Sessions / Reused by" strip on the document detail
    surface. It is intentionally the Ledger read model filtered to one
    accessible document, not a second provenance system.
    """

    document = get_v2_document_for_actor(session, current_user, document_id, demo=demo)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    if (
        current_user.organization_id is None
        or document.organization_id != current_user.organization_id
    ):
        return LedgerResponse(
            organization_id=current_user.organization_id,
            total=0,
            limit=limit,
            offset=offset,
            rows=[],
        )

    page = ledger_sessions(
        session,
        organization_id=current_user.organization_id,
        is_demo=demo,
        document_id=document.id,
        limit=limit,
        offset=offset,
    )
    return _ledger_response_from_page(
        organization_id=current_user.organization_id,
        page=page,
    )


@router.get("/ledger", response_model=LedgerResponse)
def ledger_route(
    session: SessionDep,
    current_user: CurrentUser,
    demo: bool = Query(default=False),
    actor_id: uuid.UUID | None = Query(default=None),
    client: str | None = Query(default=None, max_length=32),
    specialist: str | None = Query(default=None, max_length=64),
    cross_boundary: bool = Query(default=False),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    sort: str = Query(default="newest", pattern="^(newest|oldest)$"),
    limit: int = Query(default=50, ge=1, le=MAX_REFERENCE_ROWS),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """Org-wide session ledger — the raw tier of the pipeline (TF-208 / P1).

    A paginated, newest-first feed of the org's Taskforce sessions across all
    tools: who did work, in which ``client``, under which specialist, which
    documents it touched, and what it saved. Sessions are grouped from
    ``metrics_event.payload->>'session_id'`` (no Session table). This is a
    recall/activity surface — ``cross_boundary`` is a filter, not a headline.
    Org-scoped; a 422 is returned for solo users.

    Filters: ``actor_id``, ``client`` (tool), ``specialist`` (slug),
    ``cross_boundary`` (person- or tool-boundary crossings only), ``since`` /
    ``until`` (UTC bounds), ``q`` (free-text over prompt + document title).
    """

    if current_user.organization_id is None:
        raise HTTPException(
            status_code=422,
            detail="User does not belong to an organization",
        )

    page = ledger_sessions(
        session,
        organization_id=current_user.organization_id,
        is_demo=demo,
        actor_id=actor_id,
        client=client,
        specialist_slug=specialist,
        cross_boundary_only=cross_boundary,
        since=since,
        until=until,
        query=q,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return _ledger_response_from_page(
        organization_id=current_user.organization_id,
        page=page,
    )


@router.get("/ledger/{session_id}", response_model=LedgerSessionDetailPublic)
def ledger_detail_route(
    session: SessionDep,
    current_user: CurrentUser,
    session_id: str,
    demo: bool = Query(default=False),
) -> Any:
    """Return one org-scoped Ledger session with transcript detail."""

    if current_user.organization_id is None:
        raise HTTPException(
            status_code=422,
            detail="User does not belong to an organization",
        )

    detail = ledger_session_detail(
        session,
        organization_id=current_user.organization_id,
        session_id=session_id,
        is_demo=demo,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Ledger session not found")

    row = _ledger_row_public(detail.row)
    return LedgerSessionDetailPublic(
        **row.model_dump(),
        transcript_events=[
            LedgerTranscriptEventPublic(
                id=event.id,
                kind=event.kind,  # type: ignore[arg-type]
                occurred_at=event.occurred_at,
                role=event.role,
                who=event.who,
                text=event.text,
                cmd=event.cmd,
                exit_code=event.exit_code,
                output=event.output,
                file=event.file,
                added=event.added,
                removed=event.removed,
                note=event.note,
                repo=event.repo,
            )
            for event in detail.transcript_events
        ],
        raw_transcript_available=detail.raw_transcript_available,
        source_metadata=detail.source_metadata,
    )


@router.get(
    "/ledger/{session_id}/raw-transcript",
    response_model=LedgerRawTranscriptPublic,
)
def ledger_raw_transcript_route(
    session: SessionDep,
    current_user: CurrentUser,
    session_id: str,
    demo: bool = Query(default=False),
) -> Any:
    """Return conversational turns derived from the canonical event stream."""

    if current_user.organization_id is None:
        raise HTTPException(
            status_code=422,
            detail="User does not belong to an organization",
        )

    events = session.exec(
        select(TaskforceSessionEvent)
        .where(TaskforceSessionEvent.organization_id == current_user.organization_id)
        .where(TaskforceSessionEvent.is_demo == demo)
        .where(TaskforceSessionEvent.session_id == session_id)
        .where(col(TaskforceSessionEvent.kind).in_(["prompt", "reply"]))
        .order_by(
            TaskforceSessionEvent.occurred_at,
            TaskforceSessionEvent.source_order,
            TaskforceSessionEvent.created_at,
        )
    ).all()
    if not events:
        raise HTTPException(status_code=404, detail="Transcript not found")

    return LedgerRawTranscriptPublic(
        session_id=session_id,
        events=[
            {
                "id": str(event.id),
                "role": event.role
                or ("user" if event.kind == "prompt" else "assistant"),
                "content": event.text or "",
                "occurred_at": event.occurred_at.isoformat(),
            }
            for event in events
        ],
    )
