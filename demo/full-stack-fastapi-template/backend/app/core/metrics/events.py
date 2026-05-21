"""Event emitters for the Taskforce metrics engine.

Each ``record_*`` function inserts the metrics_event rows for one logical
agent action and returns the list of rows it created. Callers are
responsible for committing the session — emitters never commit themselves
so they compose with the surrounding doc-mutation transaction.

Conventions:
  * The "primary" event (document.created / updated / reused / finished)
    is always inserted first.
  * When a ``TaskforceUsagePayload`` is present, a paired
    ``tokens.consumed`` event is inserted with the priced USD amount.
  * Each savings source that applies appends its own ``tokens.saved.*``
    event so the read path can attribute totals without re-computing.
"""

from __future__ import annotations

import uuid as uuid_module
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlmodel import Session

from app.core.metrics.pricing import pricing_for
from app.core.metrics.savings import (
    cache_savings,
    reuse_savings,
    summary_only_savings,
)
from app.models import (
    METRICS_EVENT_DOCUMENT_CONSULTED,
    METRICS_EVENT_DOCUMENT_CREATED,
    METRICS_EVENT_DOCUMENT_FINISHED,
    METRICS_EVENT_DOCUMENT_REUSED,
    METRICS_EVENT_DOCUMENT_UPDATED,
    METRICS_EVENT_TOKENS_CONSUMED,
    METRICS_EVENT_TOKENS_SAVED_CACHE,
    METRICS_EVENT_TOKENS_SAVED_REUSE,
    METRICS_EVENT_TOKENS_SAVED_SUMMARY_ONLY,
    MetricsEvent,
    ModelPricing,
    TaskforceUsagePayload,
    User,
    V2Document,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _price_usage(
    session: Session,
    usage: TaskforceUsagePayload,
    occurred_at: datetime,
) -> tuple[ModelPricing | None, Decimal]:
    """Return ``(pricing_row, usd_amount)`` for a usage payload.

    USD = input + output + cache-read + cache-write line items, each
    priced from the same snapshot row. Missing rate fields silently
    contribute $0 so a partial pricing row still produces a defensible
    total.
    """

    pricing = pricing_for(session, usage.model_id, occurred_at)
    if pricing is None:
        return None, Decimal(0)

    def _line(tokens: int, rate: Decimal | None) -> Decimal:
        if tokens <= 0 or rate is None:
            return Decimal(0)
        return (Decimal(tokens) / Decimal(1_000_000)) * rate

    usd = (
        _line(usage.input_tokens, pricing.input_per_mtok)
        + _line(usage.output_tokens, pricing.output_per_mtok)
        + _line(usage.cache_read_input_tokens, pricing.cache_read_per_mtok)
        + _line(usage.cache_creation_input_tokens, pricing.cache_write_5m_per_mtok)
    )
    return pricing, usd


def _build_event(
    *,
    kind: str,
    user: User,
    document: V2Document | None,
    occurred_at: datetime,
    is_demo: bool,
    model_id: str | None = None,
    pricing: ModelPricing | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_tokens: int | None = None,
    cache_write_tokens: int | None = None,
    usd_amount: Decimal | None = None,
    payload: dict[str, Any] | None = None,
) -> MetricsEvent:
    return MetricsEvent(
        occurred_at=occurred_at,
        user_id=user.id,
        organization_id=user.organization_id,
        document_id=document.id if document is not None else None,
        kind=kind,
        model_id=model_id,
        pricing_id=pricing.id if pricing is not None else None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        usd_amount=usd_amount,
        is_demo=is_demo,
        payload=payload or {},
    )


def _record_usage_events(
    session: Session,
    *,
    user: User,
    document: V2Document,
    usage: TaskforceUsagePayload,
    is_demo: bool,
) -> list[MetricsEvent]:
    """Insert the tokens.consumed event plus any tokens.saved.* events
    triggered by this usage payload. Returns the inserted rows."""

    occurred_at = usage.occurred_at or _now()
    pricing, usd = _price_usage(session, usage, occurred_at)

    cache_write_tokens = (
        usage.cache_creation_input_tokens
        if usage.cache_creation_input_tokens > 0
        else None
    )
    consumed = _build_event(
        kind=METRICS_EVENT_TOKENS_CONSUMED,
        user=user,
        document=document,
        occurred_at=occurred_at,
        is_demo=is_demo,
        model_id=usage.model_id,
        pricing=pricing,
        input_tokens=usage.input_tokens or None,
        output_tokens=usage.output_tokens or None,
        cache_read_tokens=usage.cache_read_input_tokens or None,
        cache_write_tokens=cache_write_tokens,
        usd_amount=usd if usd > 0 else None,
        payload={"view_consulted": usage.view_consulted}
        if usage.view_consulted is not None
        else {},
    )
    session.add(consumed)
    events: list[MetricsEvent] = [consumed]

    cache_tokens, cache_usd = cache_savings(usage, pricing)
    if cache_tokens > 0:
        events.append(
            _build_event(
                kind=METRICS_EVENT_TOKENS_SAVED_CACHE,
                user=user,
                document=document,
                occurred_at=occurred_at,
                is_demo=is_demo,
                model_id=usage.model_id,
                pricing=pricing,
                cache_read_tokens=cache_tokens,
                usd_amount=cache_usd if cache_usd > 0 else None,
            )
        )

    summary_tokens, summary_usd = summary_only_savings(usage, document, pricing)
    if summary_tokens > 0:
        events.append(
            _build_event(
                kind=METRICS_EVENT_TOKENS_SAVED_SUMMARY_ONLY,
                user=user,
                document=document,
                occurred_at=occurred_at,
                is_demo=is_demo,
                model_id=usage.model_id,
                pricing=pricing,
                input_tokens=summary_tokens,
                usd_amount=summary_usd if summary_usd > 0 else None,
                payload={"details_tokens": int(document.details_tokens)},
            )
        )

    for event in events[1:]:
        session.add(event)
    return events


def record_usage(
    session: Session,
    *,
    user: User,
    document: V2Document,
    usage: TaskforceUsagePayload,
    is_demo: bool,
) -> list[MetricsEvent]:
    """Public entry point used by POST /v2/documents/{id}/usage."""

    return _record_usage_events(
        session,
        user=user,
        document=document,
        usage=usage,
        is_demo=is_demo,
    )


def record_search_usage(
    session: Session,
    *,
    user: User,
    usage: TaskforceUsagePayload,
    document: V2Document | None = None,
    is_demo: bool = False,
    billed_to: str = "managed",
) -> MetricsEvent:
    """Emit a single ``tokens.consumed`` event for a Search call.

    Unlike ``record_usage``, this is *not* document-scoped — Search
    queries may reference zero or many docs. When the answer cited a
    top-ranked document, pass it as ``document`` so per-document
    metrics still attribute correctly; otherwise leave it None and the
    event simply rolls into the user-level totals.

    ``billed_to`` is recorded on the payload for downstream cost
    accounting ("managed" vs "byok:anthropic" vs "byok:openai")."""

    occurred_at = usage.occurred_at or _now()
    pricing, usd = _price_usage(session, usage, occurred_at)
    cache_write_tokens = (
        usage.cache_creation_input_tokens
        if usage.cache_creation_input_tokens > 0
        else None
    )
    event = _build_event(
        kind=METRICS_EVENT_TOKENS_CONSUMED,
        user=user,
        document=document,
        occurred_at=occurred_at,
        is_demo=is_demo,
        model_id=usage.model_id,
        pricing=pricing,
        input_tokens=usage.input_tokens or None,
        output_tokens=usage.output_tokens or None,
        cache_read_tokens=usage.cache_read_input_tokens or None,
        cache_write_tokens=cache_write_tokens,
        # BYOK calls don't cost us anything; the payload tags the call
        # source so the metrics read API can split spend by route.
        usd_amount=(usd if (usd > 0 and billed_to == "managed") else None),
        payload={"source": "search", "billed_to": billed_to},
    )
    session.add(event)
    return event


def record_document_created(
    session: Session,
    *,
    user: User,
    document: V2Document,
    usage: TaskforceUsagePayload | None,
    is_demo: bool,
) -> list[MetricsEvent]:
    occurred_at = (usage.occurred_at if usage else None) or _now()
    primary = _build_event(
        kind=METRICS_EVENT_DOCUMENT_CREATED,
        user=user,
        document=document,
        occurred_at=occurred_at,
        is_demo=is_demo,
        model_id=usage.model_id if usage else None,
    )
    session.add(primary)
    events: list[MetricsEvent] = [primary]
    if usage is not None:
        events.extend(
            _record_usage_events(
                session,
                user=user,
                document=document,
                usage=usage,
                is_demo=is_demo,
            )
        )
    return events


def record_document_updated(
    session: Session,
    *,
    user: User,
    document: V2Document,
    usage: TaskforceUsagePayload | None,
    is_demo: bool,
) -> list[MetricsEvent]:
    occurred_at = (usage.occurred_at if usage else None) or _now()
    primary = _build_event(
        kind=METRICS_EVENT_DOCUMENT_UPDATED,
        user=user,
        document=document,
        occurred_at=occurred_at,
        is_demo=is_demo,
        model_id=usage.model_id if usage else None,
    )
    session.add(primary)
    events: list[MetricsEvent] = [primary]
    if usage is not None:
        events.extend(
            _record_usage_events(
                session,
                user=user,
                document=document,
                usage=usage,
                is_demo=is_demo,
            )
        )
    return events


def record_document_finished(
    session: Session,
    *,
    user: User,
    document: V2Document,
    status: str,
    usage: TaskforceUsagePayload | None,
    is_demo: bool,
) -> list[MetricsEvent]:
    occurred_at = (usage.occurred_at if usage else None) or _now()
    primary = _build_event(
        kind=METRICS_EVENT_DOCUMENT_FINISHED,
        user=user,
        document=document,
        occurred_at=occurred_at,
        is_demo=is_demo,
        model_id=usage.model_id if usage else None,
        payload={"status": status},
    )
    session.add(primary)
    events: list[MetricsEvent] = [primary]
    if usage is not None:
        events.extend(
            _record_usage_events(
                session,
                user=user,
                document=document,
                usage=usage,
                is_demo=is_demo,
            )
        )
    return events


def record_document_reused(
    session: Session,
    *,
    user: User,
    document: V2Document,
    score: int | None,
    band: str | None,
    reasons: list[str] | None,
    usage: TaskforceUsagePayload | None,
    is_demo: bool,
) -> list[MetricsEvent]:
    """Emit ``document.reused`` + a paired ``tokens.saved.reuse`` event.

    The reuse-savings calculation uses the doc's cached
    ``summary_tokens`` / ``details_tokens`` and the pricing snapshot
    effective at ``occurred_at``. Pricing model defaults to the agent's
    declared model_id, or a sensible fallback if the agent didn't pass
    one (we still want to record reuse even without usage data).
    """

    occurred_at = (usage.occurred_at if usage else None) or _now()
    model_id_for_pricing = usage.model_id if usage else "claude-opus-4-7"
    pricing = pricing_for(session, model_id_for_pricing, occurred_at)
    bootstrap_tokens, bootstrap_usd = reuse_savings(document, pricing)

    primary = _build_event(
        kind=METRICS_EVENT_DOCUMENT_REUSED,
        user=user,
        document=document,
        occurred_at=occurred_at,
        is_demo=is_demo,
        model_id=usage.model_id if usage else None,
        payload={
            "score": score,
            "band": band,
            "reasons": reasons or [],
            "bootstrap_tokens": bootstrap_tokens,
        },
    )
    session.add(primary)
    events: list[MetricsEvent] = [primary]

    if bootstrap_tokens > 0:
        saved = _build_event(
            kind=METRICS_EVENT_TOKENS_SAVED_REUSE,
            user=user,
            document=document,
            occurred_at=occurred_at,
            is_demo=is_demo,
            model_id=usage.model_id if usage else model_id_for_pricing,
            pricing=pricing,
            input_tokens=bootstrap_tokens,
            usd_amount=bootstrap_usd if bootstrap_usd > 0 else None,
        )
        session.add(saved)
        events.append(saved)

    if usage is not None:
        events.extend(
            _record_usage_events(
                session,
                user=user,
                document=document,
                usage=usage,
                is_demo=is_demo,
            )
        )
    return events


# Default pricing model used when the consulting agent didn't declare one
# (the discover endpoint doesn't know the agent's model). Matches the
# fallback in ``record_document_reused``.
_DEFAULT_CONSULT_PRICING_MODEL = "claude-opus-4-7"


def record_document_consulted(
    session: Session,
    *,
    user: User,
    document: V2Document,
    score: float,
    band: str,
    match_reasons: list[str],
    summary_tokens: int,
    rediscovery_cost_tokens: int,
    query_id: uuid_module.UUID,
    source: str,
    is_demo: bool,
    pricing_model_id: str | None = None,
) -> MetricsEvent:
    """Record one ``document.consulted`` event (TF-175 / Phase 1 + TF-177 / Phase 3).

    Emits a single event with two savings-bearing fields:
      * ``input_tokens`` carries ``net_saved_tokens`` so the registry's
        ``avoided_rediscovery`` metric can ``sum(input_tokens)`` without
        parsing JSONB.
      * ``usd_amount`` carries the priced value of those tokens, snapshotted
        at the current pricing for the agent's model (or the configured
        default model when the caller didn't pass one). That feeds the
        ``avoided_rediscovery_usd`` metric.

    No primary "document.*" event fires — this is purely a "the agent
    looked at this" signal. Consult events are *not* counted in
    ``reuse_rate`` (which is about the create-vs-reuse decision, not
    consultation).
    """

    occurred_at = _now()
    net_saved_tokens = max(0, rediscovery_cost_tokens - summary_tokens)

    pricing_model = pricing_model_id or _DEFAULT_CONSULT_PRICING_MODEL
    pricing = pricing_for(session, pricing_model, occurred_at)
    usd_amount: Decimal | None = None
    if pricing is not None and net_saved_tokens > 0 and pricing.input_per_mtok is not None:
        usd_amount = (Decimal(net_saved_tokens) / Decimal(1_000_000)) * pricing.input_per_mtok

    payload: dict[str, Any] = {
        "source": source,
        "score": round(score, 4),
        "band": band,
        "query_id": str(query_id),
        "summary_tokens": summary_tokens,
        "rediscovery_cost_tokens": rediscovery_cost_tokens,
        "net_saved_tokens": net_saved_tokens,
        "match_reasons": match_reasons,
        "pricing_model_id": pricing_model,
    }

    event = _build_event(
        kind=METRICS_EVENT_DOCUMENT_CONSULTED,
        user=user,
        document=document,
        occurred_at=occurred_at,
        is_demo=is_demo,
        model_id=pricing_model,
        pricing=pricing,
        # ``input_tokens`` doubles as the headline savings field so the
        # registry's ``avoided_rediscovery`` metric can ``sum(input_tokens)``
        # across ``document.consulted`` events without parsing JSONB.
        input_tokens=net_saved_tokens or None,
        usd_amount=usd_amount if usd_amount and usd_amount > 0 else None,
        payload=payload,
    )
    session.add(event)
    return event
