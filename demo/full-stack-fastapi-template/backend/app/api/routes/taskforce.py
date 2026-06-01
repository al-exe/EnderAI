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
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.core.metrics.queries import (
    cross_boundary_reuse,
    taskforce_session_savings,
)
from app.core.taskforce.discover import discover as run_discover
from app.core.taskforce.observe import observe as run_observe
from app.core.taskforce.session import session_start as run_session_start
from app.core.v2_documents import apply_v2_document_update, get_v2_document_for_actor
from app.models import (
    METRICS_EVENT_DOCUMENT_CONSULTED,
    CrossBoundaryReuseEventPublic,
    CrossBoundaryReuseResponse,
    MetricsEvent,
    TaskforceDiscoverRequest,
    TaskforceDiscoverResponse,
    TaskforceObserveRequest,
    TaskforceObserveResponse,
    TaskforceReferenceRequest,
    TaskforceReferenceResponse,
    TaskforceSessionLogEntry,
    TaskforceSessionLogResponse,
    TaskforceSessionSavingsResponse,
    TaskforceSessionStartRequest,
    TaskforceSessionStartResponse,
    V2Document,
    V2DocumentDetailsSection,
    V2DocumentUpdate,
    get_datetime_utc,
)

router = APIRouter(prefix="/v2/taskforce", tags=["taskforce"])

REFERENCED_BY_ANCHOR_ID = "referenced-by"
MAX_REFERENCE_ROWS = 200
PROMPT_PREVIEW_CHARS = 120


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
      * runs a deterministic materiality check
      * calls the haiku summarizer when material
      * patches the active document (or creates a fresh one) — unless
        ``TASKFORCE_OBSERVE_SHADOW=1`` (default), in which case the
        intent is audited but no doc state changes
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


@router.get("/cross-boundary-reuse", response_model=CrossBoundaryReuseResponse)
def cross_boundary_reuse_route(
    session: SessionDep,
    current_user: CurrentUser,
    demo: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=MAX_REFERENCE_ROWS),
) -> Any:
    """Cross-person reuse ledger for the caller's organization (TF-202 / C3).

    The empty-cell proof's read surface: documents produced by one teammate
    and later reused/consulted by another, with the origin + consuming tool,
    both display names, measured token savings and an estimated USD floor, and
    the provenance trail. Org-scoped — a 422 is returned for solo users.
    Nothing is seeded; every row is a real C1/C2 event.
    """

    if current_user.organization_id is None:
        raise HTTPException(
            status_code=422,
            detail="User does not belong to an organization",
        )

    rows = cross_boundary_reuse(
        session,
        organization_id=current_user.organization_id,
        is_demo=demo,
        limit=limit,
    )
    events = [
        CrossBoundaryReuseEventPublic(
            event_id=row.event_id,
            kind=row.kind,
            occurred_at=row.occurred_at,
            document_id=row.document_id,
            document_title=row.document_title,
            document_href=f"/v2/documents/{row.document_id}",
            produced_by_client=row.produced_by_client,
            consumed_by_client=row.consumed_by_client,
            owner_id=row.owner_id,
            owner_name=row.owner_name,
            consumer_id=row.consumer_id,
            consumer_name=row.consumer_name,
            net_saved_tokens=row.net_saved_tokens,
            usd_amount=row.usd_amount,
            usd_is_estimated=row.usd_is_estimated,
            specialist_slug=row.specialist_slug,
            specialist_name=row.specialist_name,
            session_id=row.session_id,
            query_id=row.query_id,
            match_reasons=row.match_reasons,
            score=row.score,
            confidence_band=row.confidence_band,
        )
        for row in rows
    ]
    return CrossBoundaryReuseResponse(
        organization_id=current_user.organization_id,
        proven_event_count=len(events),
        proven_net_saved_tokens=sum(event.net_saved_tokens for event in events),
        estimated_usd_total=sum((event.usd_amount for event in events), Decimal(0)),
        events=events,
    )
