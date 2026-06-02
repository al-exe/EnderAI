"""Read endpoints for the Taskforce Metrics engine.

Plan §7. Two endpoints:

* ``GET /v2/metrics/definitions`` — the code-defined registry, used by the
  frontend to self-describe card layouts.
* ``GET /v2/metrics`` — totals + series + breakdowns for the requested
  metrics over a 7d / 30d / all-time window, optionally for the org.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, SessionDep
from app.core.metrics import (
    REGISTRY,
    MetricDefinition,
    all_metric_names,
    cross_boundary_reuse_totals,
    daily_series,
    documents_consulted_count,
    documents_touched_count,
    resolve_window,
    reuse_rate,
    savings_breakdown,
    sum_metric_total,
    top_models,
)
from app.core.metrics.events import record_search_usage
from app.models import (
    MetricBreakdownEntry,
    MetricDefinitionPublic,
    MetricDefinitionsResponse,
    MetricEventRecordedPublic,
    MetricPresentationPublic,
    MetricSeriesPoint,
    MetricsResponse,
    MetricValuePublic,
    TaskforceUsagePayload,
)

router = APIRouter(prefix="/v2/metrics", tags=["v2-metrics"])


def _to_definition_public(defn: MetricDefinition) -> MetricDefinitionPublic:
    return MetricDefinitionPublic(
        name=defn.name,
        display_name=defn.display_name,
        unit=defn.unit,
        description=defn.description,
        presentation=MetricPresentationPublic(
            format=defn.presentation.format,
            trend=defn.presentation.trend,
            icon=defn.presentation.icon,
        ),
    )


@router.get("/definitions", response_model=MetricDefinitionsResponse)
def read_metric_definitions() -> Any:
    return MetricDefinitionsResponse(
        data=[_to_definition_public(REGISTRY[name]) for name in all_metric_names()]
    )


_BREAKDOWN_LABELS = {
    "tokens.saved.cache": "Cache hits",
    "tokens.saved.summary_only": "Summary only",
    "tokens.saved.reuse": "Reuse on begin",
}


def _delta_pct(current: Decimal, previous: Decimal) -> Decimal | None:
    if previous == 0:
        return None
    return ((current - previous) / previous).quantize(Decimal("0.0001"))


def _delta_abs(current: Decimal, previous: Decimal) -> Decimal:
    return current - previous


def _compute_metric_value(
    session: Any,
    *,
    user_id: Any,
    is_demo: bool,
    window: Any,
    defn: MetricDefinition,
    include_breakdowns: bool,
) -> MetricValuePublic:
    if defn.name in {"documents_touched", "documents_consulted"}:
        counter = (
            documents_touched_count
            if defn.name == "documents_touched"
            else documents_consulted_count
        )
        total = Decimal(
            counter(session, user_id=user_id, is_demo=is_demo, window=window)
        )
        prev_window = window.previous()
        prev_total = (
            Decimal(
                counter(session, user_id=user_id, is_demo=is_demo, window=prev_window)
            )
            if prev_window is not None
            else None
        )
        return MetricValuePublic(
            total=total,
            delta_vs_prev_window=(
                _delta_pct(total, prev_total) if prev_total is not None else None
            ),
        )

    if defn.name == "reuse_rate":
        total = reuse_rate(session, user_id=user_id, is_demo=is_demo, window=window)
        prev_window = window.previous()
        if prev_window is not None:
            prev = reuse_rate(
                session, user_id=user_id, is_demo=is_demo, window=prev_window
            )
            return MetricValuePublic(
                total=total,
                delta_vs_prev_window=_delta_abs(total, prev),
            )
        return MetricValuePublic(total=total)

    if defn.name in {"cross_boundary_reuse_rate", "cross_boundary_tokens_saved"}:
        totals = cross_boundary_reuse_totals(
            session,
            user_id=user_id,
            is_demo=is_demo,
            window=window,
        )
        if defn.name == "cross_boundary_reuse_rate":
            return MetricValuePublic(total=totals.rate)
        return MetricValuePublic(
            total=Decimal(totals.cross_boundary_tokens),
            breakdown_by_source=[
                MetricBreakdownEntry(
                    key="cross_boundary",
                    label="Cross-boundary",
                    tokens=totals.cross_boundary_tokens,
                    usd=totals.cross_boundary_usd,
                ),
                MetricBreakdownEntry(
                    key="same_boundary",
                    label="Same owner/tool",
                    tokens=totals.same_boundary_tokens,
                    usd=totals.same_boundary_usd,
                ),
            ],
        )

    total = sum_metric_total(
        session,
        user_id=user_id,
        is_demo=is_demo,
        window=window,
        definition=defn,
    )
    prev_window = window.previous()
    delta: Decimal | None = None
    if prev_window is not None:
        prev = sum_metric_total(
            session,
            user_id=user_id,
            is_demo=is_demo,
            window=prev_window,
            definition=defn,
        )
        delta = _delta_pct(total, prev)

    series_points: list[MetricSeriesPoint] = []
    for point in daily_series(
        session,
        user_id=user_id,
        is_demo=is_demo,
        window=window,
        definition=defn,
    ):
        series_points.append(MetricSeriesPoint(day=point.day, value=point.value))

    value = MetricValuePublic(
        total=total,
        delta_vs_prev_window=delta,
        series=series_points,
    )

    if include_breakdowns and defn.name == "tokens_saved":
        breakdown = savings_breakdown(
            session,
            user_id=user_id,
            is_demo=is_demo,
            window=window,
            field="input_tokens",
        )
        value.breakdown_by_source = [
            MetricBreakdownEntry(
                key="tokens.saved.cache",
                label=_BREAKDOWN_LABELS["tokens.saved.cache"],
                tokens=int(breakdown.cache),
                usd=Decimal(0),
            ),
            MetricBreakdownEntry(
                key="tokens.saved.summary_only",
                label=_BREAKDOWN_LABELS["tokens.saved.summary_only"],
                tokens=int(breakdown.summary_only),
                usd=Decimal(0),
            ),
            MetricBreakdownEntry(
                key="tokens.saved.reuse",
                label=_BREAKDOWN_LABELS["tokens.saved.reuse"],
                tokens=int(breakdown.reuse),
                usd=Decimal(0),
            ),
        ]
    if include_breakdowns and defn.name == "tokens_consumed":
        rows = top_models(session, user_id=user_id, is_demo=is_demo, window=window)
        value.top_models = [
            MetricBreakdownEntry(
                key=row.model_id,
                label=row.model_id,
                tokens=row.tokens,
                usd=row.usd,
            )
            for row in rows
        ]
    return value


@router.get("", response_model=MetricsResponse)
def read_metrics(
    session: SessionDep,
    current_user: CurrentUser,
    window: Literal["7d", "30d", "all"] = Query(default="7d"),
    metrics: str | None = Query(default=None),
    demo: bool = Query(default=False),
    scope: Literal["personal", "organization"] = Query(default="personal"),
) -> Any:
    """Return totals + series + breakdowns for the requested metrics.

    ``metrics`` is a comma-separated list of metric names; omitted →
    return every metric in the registry. ``scope=organization`` is only
    available to org admins; non-admins get a 403."""

    requested_names = (
        [n.strip() for n in metrics.split(",") if n.strip()]
        if metrics
        else all_metric_names()
    )
    for name in requested_names:
        if name not in REGISTRY:
            raise HTTPException(status_code=404, detail=f"Unknown metric: {name}")

    if scope == "organization":
        if current_user.organization_id is None:
            raise HTTPException(
                status_code=422,
                detail="User does not belong to an organization",
            )
        if current_user.organization_role != "admin":
            raise HTTPException(
                status_code=403,
                detail="Only organization admins can view org-scope metrics",
            )

    resolved = resolve_window(window)
    response = MetricsResponse(
        window=window,
        to=resolved.end,
        scope=scope,
        is_demo=demo,
        metrics={},
    )
    response.from_ = resolved.start

    # Phase 4 ships personal scope only. The org scope path requires
    # a fan-out over members which we'll add in a follow-up; for now
    # the admin gate above prevents accidental personal-only data leaks
    # under an org=true URL.
    for name in requested_names:
        defn = REGISTRY[name]
        include_breakdowns = name in ("tokens_saved", "tokens_consumed")
        response.metrics[name] = _compute_metric_value(
            session,
            user_id=current_user.id,
            is_demo=demo,
            window=resolved,
            defn=defn,
            include_breakdowns=include_breakdowns,
        )
    return response


@router.post(
    "/usage",
    response_model=MetricEventRecordedPublic,
    status_code=201,
)
def record_session_usage(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    usage: TaskforceUsagePayload,
    source: str = Query(
        default="hook",
        max_length=32,
        description=(
            "Free-form label written to the metrics_event payload so the "
            "read API can split spend by origin (e.g. 'hook', 'search', "
            "'cli'). Defaults to 'hook' which is the Claude Code Stop "
            "hook ingest path."
        ),
    ),
    demo: bool = Query(default=False),
) -> Any:
    """Record a ``tokens.consumed`` event without requiring an active
    document.

    The document-scoped ``POST /v2/documents/{id}/usage`` route assumes
    the agent is mid-task with an active document; the Claude Code
    Stop hook (and Codex, Cursor, etc.) doesn't necessarily have one.
    This endpoint lets a harness fire-and-forget per-turn usage so the
    Metrics page populates regardless of whether the agent went
    through the V2 document lifecycle."""

    event = record_search_usage(
        session,
        user=current_user,
        usage=usage,
        document=None,
        is_demo=demo,
        billed_to=source,
    )
    session.commit()
    session.refresh(event)
    return MetricEventRecordedPublic(
        id=event.id,
        kind=event.kind,
        occurred_at=event.occurred_at,
        model_id=event.model_id,
        input_tokens=event.input_tokens,
        output_tokens=event.output_tokens,
        cache_read_tokens=event.cache_read_tokens,
        usd_amount=str(event.usd_amount) if event.usd_amount is not None else None,
    )
