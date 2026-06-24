"""Tier 2 session entry point (TF-181 + TF-196).

Wraps the existing discover orchestrator and adds:
  - a UUID ``session_id`` (TF-181) so hookless agents (Codex, Cursor)
    can correlate their start → observe call pair through one stable
    identifier.
  - specialist routing (TF-196): picks the best-fit
    :class:`AgentSpecialist` for the request and threads the chosen
    ``specialist_slug`` through every ``document.consulted`` event the
    discover call emits. The Agents tab (TF-194) reads that slug back
    to compute per-specialist stats.

No server-side session state yet — the agent is responsible for
threading the session_id through subsequent observe calls.
"""

from __future__ import annotations

import logging
import time
import uuid

from sqlmodel import Session

from app.core.agents.routing import SpecialistScore, route_specialist
from app.core.taskforce.discover import discover as run_discover
from app.core.taskforce.scoring import DiscoveryRequest
from app.models import (
    MatchedSpecialist,
    MatchedSpecialistLinkedDoc,
    TaskforceDiscoverRequest,
    TaskforceSessionStartRequest,
    TaskforceSessionStartResponse,
    User,
)

log = logging.getLogger(__name__)


def _build_matched_specialist(routed: SpecialistScore) -> MatchedSpecialist:
    """Build the API response shape from the routing engine's output."""

    linked_documents = [
        MatchedSpecialistLinkedDoc(
            document_id=md.document.id,
            title=md.document.title,
            anchor_id=md.anchor_id,
            confidence=round(md.score, 4),
            href=(
                f"/v2/library/{md.document.id}"
                + (f"#{md.anchor_id}" if md.anchor_id else "")
            ),
        )
        for md in routed.matched_docs
    ]
    return MatchedSpecialist(
        slug=routed.specialist.slug,
        name=routed.specialist.name,
        role=routed.specialist.role,
        confidence=round(routed.score, 4),
        band=routed.band if routed.band in {"high", "medium", "low"} else "low",
        href=f"/v2/profiles/{routed.specialist.slug}",
        reasons=routed.reasons,
        linked_documents=linked_documents,
    )


def session_start(
    session: Session,
    *,
    actor: User,
    request: TaskforceSessionStartRequest,
) -> TaskforceSessionStartResponse:
    """Mint a session_id, route to a specialist, run discover.

    Order matters:
      1. Route to a specialist (cheap, in-process; ~5ms for N=5 demo seeds).
      2. Run discover with the chosen ``specialist_slug`` so every
         ``document.consulted`` event we emit carries the slug — that's
         what the Agents page reads to compute per-specialist stats.
      3. Build the response.

    Returns ``matched_specialist=None`` when no specialist clears the
    ``medium`` band; the skill falls back to plain document matches.

    The returned ``suggested_pin`` is the top match's ``document_id``
    when its ``confidence_band`` is ``"high"`` — high enough that the
    agent should adopt it as the active document without a second
    decision step. For medium / low matches the agent picks one (or
    none) on its own.
    """

    session_id = uuid.uuid4()

    # Specialist routing — pure scoring, single batched query for
    # linked docs + last-invoked timestamps. p95 < 100ms on demo seeds.
    routing_start = time.perf_counter()
    scoring_request = DiscoveryRequest(
        prompt=request.prompt,
        files=tuple(request.files),
        recent_commands=tuple(request.recent_commands),
        git_branch=request.git_branch,
        cwd=request.cwd,
    )
    routed = route_specialist(
        session,
        actor=actor,
        request=scoring_request,
        demo=request.demo,
        min_band="medium",
    )
    routing_ms = (time.perf_counter() - routing_start) * 1000

    specialist_slug = routed.specialist.slug if routed is not None else None

    discover_start = time.perf_counter()
    discover_response = run_discover(
        session,
        actor=actor,
        request=TaskforceDiscoverRequest(
            prompt=request.prompt,
            cwd=request.cwd,
            files=list(request.files),
            git_branch=request.git_branch,
            recent_commands=list(request.recent_commands),
            client=request.client,
            k=request.k,
            min_score=request.min_score,
            session_id=str(session_id),
        ),
        demo=request.demo,
        specialist_slug=specialist_slug,
    )
    discover_ms = (time.perf_counter() - discover_start) * 1000

    # Observability — TF-196 ticket called out the need to watch for
    # >100ms regressions on the hot path. Keep it terse so it doesn't
    # spam prod logs on every prompt.
    log.info(
        "taskforce.session_start.timing",
        extra={
            "session_id": str(session_id),
            "specialist_scoring_ms": round(routing_ms, 1),
            "discover_ms": round(discover_ms, 1),
            "matched_specialist": specialist_slug,
            "match_count": len(discover_response.matches),
        },
    )

    suggested_pin = None
    if discover_response.matches:
        top = discover_response.matches[0]
        if top.confidence_band == "high":
            suggested_pin = top.document_id

    matched_specialist = (
        _build_matched_specialist(routed) if routed is not None else None
    )

    return TaskforceSessionStartResponse(
        session_id=session_id,
        matches=discover_response.matches,
        suggested_pin=suggested_pin,
        matched_specialist=matched_specialist,
    )
