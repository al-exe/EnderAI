"""Observation orchestrator (TF-178).

Flow:
  1. Materiality check (deterministic; pure).
  2. If material → call the haiku summarizer.
  3. Merge the summarizer delta into the active document, OR create a
     fresh one when no active_document_id is set.
  4. Record metrics events:
       * ``tokens.consumed`` payload subkind ``taskforce_summarizer``
         — what /observe paid haiku to summarize this transcript
       * ``tokens.consumed`` payload subkind ``agent_session`` — the
         harness-reported session totals (authoritative for spend)
       * ``taskforce.observed`` — audit row so we can reconcile checkpoint
         + final calls per session.

Shadow mode: when ``TASKFORCE_OBSERVE_SHADOW=1`` (default), the route
logs the intent and records the audit event but does **not** patch the
document. This is the safety hatch from §7.4 of the brainstorm.
"""

from __future__ import annotations

import logging
import os
import uuid as uuid_module
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlmodel import Session

from app.core.config import settings
from app.core.metrics.events import _build_event, _now
from app.core.taskforce.archive import upsert_session_archive_from_observe
from app.core.taskforce.materiality import assess_materiality
from app.core.taskforce.summarizer import (
    PROMPT_VERSION,
    SUMMARIZER_MODEL,
    SummarizerResult,
    summarize,
)
from app.core.v2_documents import (
    apply_v2_document_update,
    get_v2_document_for_actor,
    refresh_v2_document_token_counts,
)
from app.models import (
    METRICS_EVENT_TASKFORCE_OBSERVED,
    METRICS_EVENT_TOKENS_CONSUMED,
    MetricsEvent,
    TaskforceObserveRequest,
    TaskforceObserveResponse,
    User,
    V2Document,
    V2DocumentDetailsSection,
    V2DocumentParagraph,
    V2DocumentSegment,
    V2DocumentUpdate,
)

logger = logging.getLogger(__name__)

# Daily soft cap (USD) on Taskforce-side observation cost per user. Keeps
# a runaway PostToolUse hook from breaking the budget. Returns
# action="skipped" with reason="cost_capped" past this.
DEFAULT_DAILY_USD_CAP = Decimal("1.00")


def _shadow_mode() -> bool:
    return os.environ.get("TASKFORCE_OBSERVE_SHADOW", "1") not in {
        "0",
        "false",
        "False",
    }


def _has_structured_payload(request: TaskforceObserveRequest) -> bool:
    """TF-181: agent supplied summary_points / details_sections / decisions
    directly, so we can skip the haiku summarizer and just write the patch."""

    return bool(
        request.summary_points
        or request.details_sections
        or request.decisions
        or request.outcome
    )


def _summary_from_structured(request: TaskforceObserveRequest) -> SummarizerResult:
    """Synthesize a SummarizerResult from the request's structured fields.

    Lets the rest of the orchestrator stay shape-stable; downstream code
    doesn't care whether the summary came from haiku or from the agent.
    """

    return SummarizerResult(
        materiality_score=1.0,
        summary_points=list(request.summary_points)[:6],
        details_sections=[
            {"anchor_id": s.anchor_id, "markdown": s.markdown[:4000]}
            for s in request.details_sections
        ][:4],
        files_touched=list(request.files_touched),
        commands_of_interest=[cmd.cmd for cmd in request.commands_run][:8],
        decisions=list(request.decisions)[:4],
        outcome=request.outcome,
        open_questions=[],
        raw_text="<structured>",
        input_tokens=0,
        output_tokens=0,
        usd_cost=Decimal(0),
        prompt_version=PROMPT_VERSION,
    )


async def observe(
    session: Session,
    *,
    actor: User,
    request: TaskforceObserveRequest,
    demo: bool,
) -> TaskforceObserveResponse:
    shadow = _shadow_mode()
    structured = _has_structured_payload(request)
    upsert_session_archive_from_observe(
        session,
        actor=actor,
        request=request,
        demo=demo,
        document_id=request.active_document_id,
    )

    materiality = assess_materiality(request)
    if not materiality.material:
        audit = _record_audit(
            session,
            actor=actor,
            request=request,
            action="skipped",
            reason=materiality.reason,
            summarizer_usd_cost=Decimal(0),
            shadow=shadow,
        )
        return TaskforceObserveResponse(
            action="skipped",
            reason=materiality.reason,
            metrics_events_recorded=[audit.id],
            summarizer_usd_cost=Decimal(0),
            shadow=shadow,
            structured_path=structured,
        )

    if structured:
        # Agent already gave us the digest; no LLM call, no cost cap check,
        # no managed-key requirement.
        summary = _summary_from_structured(request)
    else:
        today_cost = _summarizer_cost_today(session, actor=actor)
        if today_cost >= DEFAULT_DAILY_USD_CAP:
            audit = _record_audit(
                session,
                actor=actor,
                request=request,
                action="skipped",
                reason=f"cost_capped (today=${today_cost})",
                summarizer_usd_cost=Decimal(0),
                shadow=shadow,
            )
            return TaskforceObserveResponse(
                action="skipped",
                reason="cost_capped",
                metrics_events_recorded=[audit.id],
                summarizer_usd_cost=Decimal(0),
                shadow=shadow,
                structured_path=structured,
            )

        api_key = settings.ANTHROPIC_API_KEY
        if not api_key:
            audit = _record_audit(
                session,
                actor=actor,
                request=request,
                action="skipped",
                reason="no_managed_anthropic_key",
                summarizer_usd_cost=Decimal(0),
                shadow=shadow,
            )
            return TaskforceObserveResponse(
                action="skipped",
                reason="no_managed_anthropic_key",
                metrics_events_recorded=[audit.id],
                summarizer_usd_cost=Decimal(0),
                shadow=shadow,
                structured_path=structured,
            )

        summary = await summarize(
            transcript=request.transcript,
            prompt=request.prompt,
            api_key=api_key,
        )

    summarizer_event = _record_summarizer_consumption(
        session,
        actor=actor,
        summary=summary,
        is_demo=demo,
    )
    harness_event = _record_harness_consumption(
        session,
        actor=actor,
        request=request,
        is_demo=demo,
    )

    document = _resolve_active_document(
        session, actor=actor, request=request, demo=demo
    )

    if document is None and not summary.summary_points and not summary.details_sections:
        audit = _record_audit(
            session,
            actor=actor,
            request=request,
            action="skipped",
            reason="empty_summary_no_active_doc",
            summarizer_usd_cost=summary.usd_cost,
            shadow=shadow,
        )
        recorded_ids = _ids(summarizer_event, harness_event, audit)
        return TaskforceObserveResponse(
            action="skipped",
            reason="empty_summary_no_active_doc",
            metrics_events_recorded=recorded_ids,
            summarizer_usd_cost=summary.usd_cost,
            shadow=shadow,
            structured_path=structured,
        )

    update_payload = _build_update_payload(summary)
    patched_fields = sorted(update_payload.keys())

    if shadow:
        audit = _record_audit(
            session,
            actor=actor,
            request=request,
            action="updated" if document is not None else "created",
            reason="shadow_mode",
            summarizer_usd_cost=summary.usd_cost,
            shadow=True,
            extra_payload={
                "would_patch_document_id": str(document.id) if document else None,
                "would_patch_fields": patched_fields,
                "structured_path": structured,
            },
        )
        recorded_ids = _ids(summarizer_event, harness_event, audit)
        return TaskforceObserveResponse(
            action="skipped",
            document_id=document.id if document else None,
            reason="shadow_mode",
            patched_fields=patched_fields,
            metrics_events_recorded=recorded_ids,
            summarizer_usd_cost=summary.usd_cost,
            shadow=True,
            structured_path=structured,
        )

    action: str
    target_doc: V2Document
    if document is None:
        target_doc = _create_document_from_summary(
            session, actor=actor, summary=summary, is_demo=demo, request=request
        )
        action = "created"
    else:
        target_doc = document
        update = V2DocumentUpdate(**update_payload)  # type: ignore[arg-type]
        apply_v2_document_update(target_doc, update)
        target_doc.updated_at = _now()
        session.add(target_doc)
        action = "updated"

    upsert_session_archive_from_observe(
        session,
        actor=actor,
        request=request,
        demo=demo,
        document_id=target_doc.id,
    )

    audit = _record_audit(
        session,
        actor=actor,
        request=request,
        action=action,
        reason="ok",
        summarizer_usd_cost=summary.usd_cost,
        shadow=False,
        document=target_doc,
        extra_payload={"patched_fields": patched_fields},
    )
    recorded_ids = _ids(summarizer_event, harness_event, audit)

    return TaskforceObserveResponse(
        action="created" if action == "created" else "updated",
        document_id=target_doc.id,
        patched_fields=patched_fields,
        reason="ok",
        metrics_events_recorded=recorded_ids,
        summarizer_usd_cost=summary.usd_cost,
        shadow=False,
        structured_path=structured,
    )


# ----- helpers --------------------------------------------------------------


def _resolve_active_document(
    session: Session,
    *,
    actor: User,
    request: TaskforceObserveRequest,
    demo: bool,
) -> V2Document | None:
    if request.active_document_id is None:
        return None
    return get_v2_document_for_actor(
        session, actor, request.active_document_id, demo=demo
    )


def _create_document_from_summary(
    session: Session,
    *,
    actor: User,
    summary: SummarizerResult,
    is_demo: bool,
    request: TaskforceObserveRequest,
) -> V2Document:
    title = (
        (summary.summary_points[0] if summary.summary_points else request.prompt)
        or "Taskforce session"
    )[:255]
    visibility = (
        request.visibility
        if request.visibility == "private" or actor.organization_id is not None
        else "private"
    )
    document = V2Document(
        owner_id=actor.id,
        organization_id=actor.organization_id if visibility == "organization" else None,
        visibility=visibility,
        produced_by_client=request.client,
        title=title.strip() or "Taskforce session",
        description=request.prompt.strip()[:500],
        human_summary="",
        ai_generated_summary=" ".join(summary.summary_points)[:600],
        collaborators=[],
        main_body=_main_body_from_summary(summary),
        details_file_name="taskforce.details.md",
        details_markdown_sections=summary.details_sections,
        is_demo=is_demo,
    )
    refresh_v2_document_token_counts(document)
    session.add(document)
    session.flush()
    return document


def _build_update_payload(summary: SummarizerResult) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if summary.summary_points:
        payload["main_body"] = _main_body_from_summary(summary)
    if summary.details_sections:
        payload["details_markdown_sections"] = [
            V2DocumentDetailsSection(
                anchor_id=section["anchor_id"], markdown=section["markdown"]
            )
            for section in summary.details_sections
        ]
    if summary.summary_points:
        payload["ai_generated_summary"] = " ".join(summary.summary_points)[:600]
    return payload


def _main_body_from_summary(summary: SummarizerResult) -> list[dict[str, Any]]:
    return [
        V2DocumentParagraph(segments=[V2DocumentSegment(text=point)]).model_dump(
            mode="json"
        )
        for point in summary.summary_points
    ]


def _ids(*events: MetricsEvent | None) -> list[uuid_module.UUID]:
    return [event.id for event in events if event is not None]


def _record_summarizer_consumption(
    session: Session,
    *,
    actor: User,
    summary: SummarizerResult,
    is_demo: bool,
) -> MetricsEvent | None:
    if summary.input_tokens == 0 and summary.output_tokens == 0:
        return None
    event = _build_event(
        kind=METRICS_EVENT_TOKENS_CONSUMED,
        user=actor,
        document=None,
        occurred_at=_now(),
        is_demo=is_demo,
        model_id=SUMMARIZER_MODEL,
        input_tokens=summary.input_tokens or None,
        output_tokens=summary.output_tokens or None,
        usd_amount=summary.usd_cost if summary.usd_cost > 0 else None,
        payload={
            "subkind": "taskforce_summarizer",
            "prompt_version": summary.prompt_version,
        },
    )
    session.add(event)
    return event


def _record_harness_consumption(
    session: Session,
    *,
    actor: User,
    request: TaskforceObserveRequest,
    is_demo: bool,
) -> MetricsEvent | None:
    harness = request.harness
    if harness is None:
        return None
    total_tokens = (
        (harness.total_input_tokens or 0)
        + (harness.total_output_tokens or 0)
        + (harness.total_cache_read_tokens or 0)
        + (harness.total_cache_write_tokens or 0)
    )
    if total_tokens == 0:
        return None
    event = _build_event(
        kind=METRICS_EVENT_TOKENS_CONSUMED,
        user=actor,
        document=None,
        occurred_at=_now(),
        is_demo=is_demo,
        model_id=harness.model_id,
        input_tokens=harness.total_input_tokens or None,
        output_tokens=harness.total_output_tokens or None,
        cache_read_tokens=harness.total_cache_read_tokens or None,
        cache_write_tokens=harness.total_cache_write_tokens or None,
        payload={
            "subkind": "agent_session",
            "session_id": request.session_id,
            "specialist_slug": request.specialist_slug,
            "kind": request.kind,
        },
    )
    session.add(event)
    return event


def _record_audit(
    session: Session,
    *,
    actor: User,
    request: TaskforceObserveRequest,
    action: str,
    reason: str,
    summarizer_usd_cost: Decimal,
    shadow: bool,
    document: V2Document | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> MetricsEvent:
    payload: dict[str, Any] = {
        "kind": request.kind,
        "session_id": request.session_id,
        "specialist_slug": request.specialist_slug,
        "checkpoint_index": request.checkpoint_index,
        "action": action,
        "reason": reason,
        "shadow": shadow,
        "summarizer_usd_cost": str(summarizer_usd_cost),
        "files_touched_count": len(request.files_touched),
        "commands_run_count": len(request.commands_run),
        "duration_ms": request.duration_ms,
        "prompt_version": PROMPT_VERSION,
    }
    if extra_payload:
        payload.update(extra_payload)

    event = _build_event(
        kind=METRICS_EVENT_TASKFORCE_OBSERVED,
        user=actor,
        document=document,
        occurred_at=_now(),
        is_demo=False,
        payload=payload,
    )
    session.add(event)
    return event


def _summarizer_cost_today(session: Session, *, actor: User) -> Decimal:
    """Sum of summarizer USD billed to this user since UTC midnight.

    Used for the per-user daily cost cap so a runaway hook can't drain
    the budget. Cheap query: indexed on user_id + kind.
    """

    from sqlalchemy import func
    from sqlmodel import col, select

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    statement = (
        select(func.coalesce(func.sum(MetricsEvent.usd_amount), 0))
        .where(MetricsEvent.user_id == actor.id)
        .where(MetricsEvent.kind == METRICS_EVENT_TOKENS_CONSUMED)
        .where(col(MetricsEvent.occurred_at) >= today_start)
        .where(MetricsEvent.payload["subkind"].astext == "taskforce_summarizer")  # type: ignore[index]
    )
    total = session.exec(statement).first()
    return Decimal(str(total or 0))
