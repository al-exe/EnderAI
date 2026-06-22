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

Always-write contract: a *material* session always produces or refreshes
one document so the Sessions shared-context feed fills in as the agent
conversation develops. The document content comes from, in priority order:

  1. structured fields the client supplied (free, no LLM),
  2. the haiku summarizer — only when a managed key is configured, we're
     under the daily cost cap, and the paid summarizer is enabled,
  3. a deterministic digest built from the prompt + files + commands +
     transcript the hook already ships (free fallback).

``TASKFORCE_OBSERVE_SHADOW=1`` no longer suppresses the write — the
deterministic floor (1)/(3) always lands so a missing managed key or a
stale rollout flag can't silently starve the shared context. The flag now
only disables the *paid* haiku enrichment (falls back to 3 instead of 2).
The old behavior ("record audit, write nothing") was the §7.4 rollout
safety hatch and is retired now that the feature ships.
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
from app.core.taskforce.evolution import mark_session_for_evolution
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
    TaskforceSessionArchive,
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


def _paid_summarizer_enabled() -> bool:
    """Whether the paid haiku enrichment may run this turn.

    Was the TF-178 "shadow mode" kill switch (``TASKFORCE_OBSERVE_SHADOW``).
    Now that deterministic writes always land, the flag only gates the
    *paid* summarizer: ``TASKFORCE_OBSERVE_SHADOW=1`` keeps writes on the
    free deterministic path; unset/``0`` allows the haiku enrichment when a
    managed key is configured. Default is enabled (write rich when we can).
    """

    return os.environ.get("TASKFORCE_OBSERVE_SHADOW", "0") in {
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


def _distinct_commands(request: TaskforceObserveRequest) -> list[str]:
    """Order-preserving, deduped shell commands from the request."""

    seen: set[str] = set()
    out: list[str] = []
    for command in request.commands_run:
        normalized = " ".join(command.cmd.split())
        if normalized and normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out


def _activity_markdown(request: TaskforceObserveRequest) -> str:
    """Compact 'what happened' section from the data the hook already ships.

    Keeps the deterministic floor readable in the Library/shared-context
    without an LLM: a bullet list of files touched and commands run.
    """

    lines: list[str] = []
    if request.files_touched:
        lines.append("**Files touched**")
        lines.extend(f"- `{path}`" for path in request.files_touched[:20])
    commands = _distinct_commands(request)
    if commands:
        if lines:
            lines.append("")
        lines.append("**Commands run**")
        lines.extend(f"- `{cmd[:200]}`" for cmd in commands[:20])
    return "\n".join(lines)


def _summary_from_request(request: TaskforceObserveRequest) -> SummarizerResult:
    """Deterministic, zero-cost digest from the hook payload.

    The free floor under the always-write contract: guarantees every material
    session has writable content even when the paid summarizer is disabled or
    no managed key is configured. The haiku summarizer is enrichment on top of
    this, never a gate.
    """

    points: list[str] = [p.strip() for p in request.summary_points[:6] if p.strip()]
    if not points and request.prompt.strip():
        points.append(request.prompt.strip()[:280])
    if request.files_touched:
        shown = ", ".join(request.files_touched[:6])
        points.append(f"Touched {len(request.files_touched)} file(s): {shown}")
    commands = _distinct_commands(request)
    if commands:
        points.append("Ran: " + "; ".join(cmd[:80] for cmd in commands[:5]))
    if not points:
        points.append("Taskforce session")

    details = [
        {"anchor_id": s.anchor_id, "markdown": s.markdown[:4000]}
        for s in request.details_sections
    ][:4]
    if not details:
        activity = _activity_markdown(request)
        if activity:
            details.append({"anchor_id": "activity", "markdown": activity[:4000]})

    return SummarizerResult(
        materiality_score=1.0,
        summary_points=points[:6],
        details_sections=details,
        files_touched=list(request.files_touched),
        commands_of_interest=[command.cmd for command in request.commands_run][:8],
        decisions=list(request.decisions)[:4],
        outcome=request.outcome,
        open_questions=[],
        raw_text="<deterministic>",
        input_tokens=0,
        output_tokens=0,
        usd_cost=Decimal(0),
        prompt_version=PROMPT_VERSION,
    )


async def _resolve_summary(
    session: Session,
    *,
    actor: User,
    request: TaskforceObserveRequest,
    structured: bool,
) -> tuple[SummarizerResult, bool]:
    """Pick the summary source under the always-write contract.

    Returns ``(summary, used_paid_summarizer)``. Structured payloads win
    (free). Otherwise the haiku summarizer runs only when it's enabled, a
    managed key exists, and we're under the daily cost cap; anything else
    falls back to the deterministic free digest. The summarizer is never
    wrapped in a try/except here — a raised error still aborts the request so
    the early archive commit (see ``persist_session_archive_capture``) is what
    preserves the transcript on a hook timeout.
    """

    if structured:
        return _summary_from_structured(request), False

    if _paid_summarizer_enabled():
        api_key = settings.ANTHROPIC_API_KEY
        if (
            api_key
            and _summarizer_cost_today(session, actor=actor) < DEFAULT_DAILY_USD_CAP
        ):
            summary = await summarize(
                transcript=request.transcript,
                prompt=request.prompt,
                api_key=api_key,
            )
            if summary.summary_points or summary.details_sections:
                return summary, True

    return _summary_from_request(request), False


def persist_session_archive_capture(session: Session) -> None:
    """Commit ledger capture before slow observe work.

    Stop/PostToolUse hooks time out at 15–30s while the haiku summarizer can
    run longer. The route commits again at the end, but if the client aborts
    mid-request the open transaction rolls back and the archive upsert is lost.
    """

    session.commit()


async def observe(
    session: Session,
    *,
    actor: User,
    request: TaskforceObserveRequest,
    demo: bool,
) -> TaskforceObserveResponse:
    structured = _has_structured_payload(request)
    archive = upsert_session_archive_from_observe(
        session,
        actor=actor,
        request=request,
        demo=demo,
        document_id=request.active_document_id,
    )
    # Persist transcript before the slow summarizer path. Hooks time out at
    # 15s (PostToolUse) / 30s (Stop); client disconnect rolls back the route
    # transaction — without this commit the ledger freezes at the last observe.
    persist_session_archive_capture(session)

    materiality = assess_materiality(request)
    if not materiality.material:
        # The only skip path: a trivial session isn't worth a document.
        audit = _record_audit(
            session,
            actor=actor,
            request=request,
            action="skipped",
            reason=materiality.reason,
            summarizer_usd_cost=Decimal(0),
            shadow=False,
        )
        return TaskforceObserveResponse(
            action="skipped",
            reason=materiality.reason,
            metrics_events_recorded=[audit.id],
            summarizer_usd_cost=Decimal(0),
            shadow=False,
            structured_path=structured,
        )

    # Always-write: structured → haiku enrichment (when enabled/affordable) →
    # deterministic free digest. _resolve_summary never returns empty for a
    # material session, so the write below always lands.
    summary, _ = await _resolve_summary(
        session, actor=actor, request=request, structured=structured
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
        session, actor=actor, request=request, demo=demo, archive=archive
    )

    update_payload = _build_update_payload(summary)
    patched_fields = sorted(update_payload.keys())

    action: str
    target_doc: V2Document
    if document is None:
        target_doc = _create_document_from_summary(
            session,
            actor=actor,
            summary=summary,
            is_demo=demo,
            request=request,
            fleet_session_id=archive.fleet_session_id if archive else None,
        )
        action = "created"
    else:
        target_doc = document
        # Repair a title a command-only first turn poisoned: if the existing
        # title is still a digest/generic line and this turn can produce a real
        # one, upgrade it. A human-readable title is never overwritten.
        if _is_digest_title(target_doc.title):
            better = _document_title(request, summary)
            if not _is_digest_title(better):
                update_payload["title"] = better
                patched_fields = sorted(update_payload.keys())
        update = V2DocumentUpdate(**update_payload)  # type: ignore[arg-type]
        apply_v2_document_update(target_doc, update)
        target_doc.updated_at = _now()
        session.add(target_doc)
        action = "updated"

    archive = upsert_session_archive_from_observe(
        session,
        actor=actor,
        request=request,
        demo=demo,
        document_id=target_doc.id,
    )
    mark_session_for_evolution(
        archive,
        summary=summary,
        visibility=request.visibility,
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
    archive: TaskforceSessionArchive | None = None,
) -> V2Document | None:
    """Resolve the document this observe call should patch.

    Hooks often omit ``active_document_id`` on checkpoint turns — the local
    ``~/.taskforce/<session_id>.active`` pointer may not exist yet. Fall back
    to the session archive's pinned doc so one agent session keeps one Library
    document across prompts/checkpoints.
    """

    document_id = request.active_document_id
    if document_id is None and archive is not None:
        document_id = archive.active_document_id
    if document_id is None:
        return None
    return get_v2_document_for_actor(session, actor, document_id, demo=demo)


# The free digest emits diagnostic lines ("Ran: …", "Touched …") that read fine
# inside a body but make terrible document titles. The generic fallback is no
# better. Treat all of these as "not a real title" so we can both avoid picking
# them at creation and repair them on a later turn.
_DIGEST_TITLE_PREFIXES = ("Ran: ", "Touched ")
_GENERIC_TITLE = "Taskforce session"


def _is_digest_title(text: str) -> bool:
    stripped = text.strip()
    return (
        not stripped
        or stripped == _GENERIC_TITLE
        or stripped.startswith(_DIGEST_TITLE_PREFIXES)
    )


def _document_title(request: TaskforceObserveRequest, summary: SummarizerResult) -> str:
    """Pick a human-readable title — never a 'Ran: …'/'Touched …' digest line.

    Checkpoint turns arrive with an empty prompt and only read-only commands, so
    the free digest's first point is a raw shell one-liner. Prefer the
    originating prompt, then the first prose summary point, before the generic
    fallback.
    """

    prompt = request.prompt.strip()
    if prompt:
        return prompt[:255]
    for point in summary.summary_points:
        candidate = point.strip()
        if candidate and not _is_digest_title(candidate):
            return candidate[:255]
    return _GENERIC_TITLE


def _create_document_from_summary(
    session: Session,
    *,
    actor: User,
    summary: SummarizerResult,
    is_demo: bool,
    request: TaskforceObserveRequest,
    fleet_session_id: uuid_module.UUID | None,
    auto_created: bool = False,
    evolution_confidence: float | None = None,
    evolution_provenance: dict[str, Any] | None = None,
) -> V2Document:
    title = _document_title(request, summary)
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
        fleet_session_id=fleet_session_id,
        title=title,
        description=request.prompt.strip()[:500],
        human_summary="",
        ai_generated_summary=" ".join(summary.summary_points)[:600],
        collaborators=[],
        main_body=_main_body_from_summary(summary),
        details_file_name="taskforce.details.md",
        details_markdown_sections=summary.details_sections,
        is_demo=is_demo,
        auto_created=auto_created,
        evolution_confidence=evolution_confidence,
        evolution_provenance=dict(evolution_provenance or {}),
    )
    refresh_v2_document_token_counts(document)
    session.add(document)
    session.flush()
    return document


def create_v2_document_from_session_summary(
    session: Session,
    *,
    actor: User,
    summary: SummarizerResult,
    is_demo: bool,
    request: TaskforceObserveRequest,
    fleet_session_id: uuid_module.UUID | None,
    auto_created: bool = False,
    evolution_confidence: float | None = None,
    evolution_provenance: dict[str, Any] | None = None,
) -> V2Document:
    """Public doc-create entry shared by observe and offline evolution (T1)."""

    return _create_document_from_summary(
        session,
        actor=actor,
        summary=summary,
        is_demo=is_demo,
        request=request,
        fleet_session_id=fleet_session_id,
        auto_created=auto_created,
        evolution_confidence=evolution_confidence,
        evolution_provenance=evolution_provenance,
    )


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
