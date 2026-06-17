"""Discovery orchestrator (TF-175).

Wraps the scoring engine in actor-scoping + token-cost estimation +
metrics emission, so the route handler stays a thin shell.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.metrics.events import record_document_consulted
from app.core.taskforce.active_sessions import (
    get_active_sessions,
    touch_session_heartbeat,
)
from app.core.taskforce.scoring import (
    DiscoveryRequest,
    ScoredCandidate,
    rank_candidates,
)
from app.core.v2_documents import list_v2_documents_for_actor
from app.models import (
    TaskforceDiscoverMatch,
    TaskforceDiscoverRequest,
    TaskforceDiscoverResponse,
    TaskforceFleetSession,
    TaskforceSessionArchive,
    TaskforceSessionContextEntry,
    TaskforceSessionContextResponse,
    User,
    V2Document,
)

# Latency budget: cap the candidate list at the user's N most-recently-updated
# docs before scoring. Tuned for p95 < 500ms over a library of ~thousands.
CANDIDATE_LIMIT = 200

# Shared-context feed (Sessions drawer): how many of a group's documents to
# surface, and the token budget the hooks honor when injecting them into an
# agent turn. Newest documents win when the feed exceeds the budget.
FLEET_CONTEXT_LIMIT = 20
INJECT_TOKEN_BUDGET = 2000
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Tokens-per-character ratio used as a coarse estimate for the
# ``consult_token_cost`` field. Real tokenization happens in the model
# pipeline; this is just so the savings math has a plausible value to
# compare against ``rediscovery_cost_tokens`` (Phase 3 will start writing
# the latter to a real column).
_CHARS_PER_TOKEN = 4.0
_NONALNUM = re.compile(r"\s+")


def _estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    # Simple chars/4 heuristic; matches OpenAI's published guidance and the
    # MCP's ``estimateTokens`` helper. Good enough for budget math.
    return max(1, round(len(text) / _CHARS_PER_TOKEN))


def _summary_markdown(document: V2Document, max_chars: int = 800) -> str:
    """Pick the best available short description of the doc for the preamble.

    Preference order: ``ai_generated_summary`` → ``description`` → first
    ``main_body`` paragraph. Always truncated to ``max_chars`` so the hook's
    budget math (Phase 2) stays bounded.
    """

    if document.ai_generated_summary:
        text = document.ai_generated_summary
    elif document.description:
        text = document.description
    else:
        first_body = (document.main_body or [{}])[0]
        segments = (
            first_body.get("segments")
            if isinstance(first_body, dict)
            else getattr(first_body, "segments", [])
        )
        joined: list[str] = []
        for seg in segments or []:
            t = seg.get("text") if isinstance(seg, dict) else getattr(seg, "text", "")
            if t:
                joined.append(t)
        text = " ".join(joined)
    text = _NONALNUM.sub(" ", text or "").strip()
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars].rsplit(" ", 1)[0]
    return truncated + "…"


def _outcome_for(document: V2Document) -> str | None:
    """Pull the latest ``outcome`` marker out of details sections, if any.

    Conventions: ``enderai_finish_document`` appends a section whose
    ``anchor_id`` starts with ``outcome`` and whose markdown begins with
    ``# Outcome``. We accept any anchor id with the substring "outcome" so
    we can evolve the writer without lockstep.
    """

    for section in document.details_markdown_sections or []:
        anchor = (
            section.get("anchor_id")
            if isinstance(section, dict)
            else getattr(section, "anchor_id", "")
        )
        markdown = (
            section.get("markdown")
            if isinstance(section, dict)
            else getattr(section, "markdown", "")
        )
        if anchor and "outcome" in anchor.lower():
            # Strip a leading "# Outcome" heading line if present.
            lines = [
                line.strip()
                for line in (markdown or "").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            return " ".join(lines)[:280] if lines else None
    return None


def discover(
    session: Session,
    *,
    actor: User,
    request: TaskforceDiscoverRequest,
    demo: bool,
    specialist_slug: str | None = None,
) -> TaskforceDiscoverResponse:
    """Score the actor's library against the request, record consults.

    Always returns a stable ``query_id`` (even when no matches clear
    ``min_score``) so the hook can correlate consult events back to a
    specific discover call.
    """

    query_id = uuid.uuid4()

    archive = touch_session_heartbeat(session, actor=actor, request=request, demo=demo)
    raw_candidates = list_v2_documents_for_actor(session, actor, demo=demo)
    if archive is not None:
        raw_candidates = [
            document
            for document in raw_candidates
            if document.fleet_session_id is None
            or document.fleet_session_id == archive.fleet_session_id
        ]
    capped = raw_candidates[:CANDIDATE_LIMIT]

    scoring_request = DiscoveryRequest(
        prompt=request.prompt,
        title=None,  # hooks don't supply a separate title field today
        files=tuple(request.files),
        symbols=(),  # reserved for Phase 2 if the hook starts extracting them
        errors=(),
        recent_commands=tuple(request.recent_commands),
        git_branch=request.git_branch,
        cwd=request.cwd,
    )

    ranked: Sequence[ScoredCandidate] = rank_candidates(
        capped,
        scoring_request,
        k=request.k,
        min_score=request.min_score,
    )

    matches: list[TaskforceDiscoverMatch] = []
    for scored in ranked:
        summary = _summary_markdown(scored.document)
        consult_token_cost = _estimate_tokens(summary)
        # ``rediscovery_cost_tokens`` lives on a column that Phase 3
        # introduces. Until then, fall back to a coarse estimate from the
        # doc's existing structure so the savings math degrades smoothly.
        rediscovery_cost_tokens = _placeholder_rediscovery_cost(scored.document)

        match = TaskforceDiscoverMatch(
            document_id=scored.document.id,
            title=scored.document.title,
            score=round(scored.score, 4),
            confidence_band=scored.band,
            match_reasons=scored.match_reasons,
            matched_anchor_id=scored.matched_anchor_id,
            summary_markdown=summary,
            last_touched_at=scored.document.updated_at,
            outcome=_outcome_for(scored.document),
            rediscovery_cost_tokens=rediscovery_cost_tokens,
            consult_token_cost=consult_token_cost,
        )
        matches.append(match)

        record_document_consulted(
            session,
            user=actor,
            document=scored.document,
            score=scored.score,
            band=scored.band,
            match_reasons=scored.match_reasons,
            summary_tokens=consult_token_cost,
            rediscovery_cost_tokens=rediscovery_cost_tokens,
            query_id=query_id,
            source="discover_endpoint",
            is_demo=demo,
            session_id=request.session_id,
            specialist_slug=specialist_slug,
            prompt=request.prompt,
            consumed_by_client=request.client,
        )

    active_sessions = get_active_sessions(
        session,
        actor=actor,
        demo=demo,
        exclude_session_id=request.session_id,
    )

    return TaskforceDiscoverResponse(
        query_id=query_id,
        matches=matches,
        active_sessions=active_sessions,
        session_active_document_id=(
            archive.active_document_id if archive is not None else None
        ),
    )


def _group_member_document_ids(
    session: Session,
    *,
    actor: User,
    fleet_session: TaskforceFleetSession,
    demo: bool,
) -> set[uuid.UUID]:
    """Doc ids touched by the agent sessions currently assigned to this group.

    Each archive records the documents it produced/referenced
    (``active_document_id`` + ``referenced_document_ids``). Unioning those over
    the archives whose ``fleet_session_id`` is this group gives a membership set
    that moves with the agents: a session that leaves the group takes its docs
    out of the feed automatically.
    """

    archives = session.exec(
        select(TaskforceSessionArchive)
        .where(TaskforceSessionArchive.actor_id == actor.id)
        .where(TaskforceSessionArchive.is_demo == demo)
        .where(TaskforceSessionArchive.fleet_session_id == fleet_session.id)
    ).all()

    document_ids: set[uuid.UUID] = set()
    for archive in archives:
        if archive.active_document_id is not None:
            document_ids.add(archive.active_document_id)
        for raw in archive.referenced_document_ids or []:
            try:
                document_ids.add(uuid.UUID(str(raw)))
            except (TypeError, ValueError):
                continue
    return document_ids


def fleet_session_context(
    session: Session,
    *,
    actor: User,
    fleet_session: TaskforceFleetSession,
    demo: bool,
    limit: int = FLEET_CONTEXT_LIMIT,
) -> TaskforceSessionContextResponse:
    """Shared-context feed for one session group, from the discovery corpus.

    Context follows the **agents currently in the group**, not a frozen stamp:
    we gather the documents touched by the session archives whose
    ``fleet_session_id`` is this group right now, so when an agent moves to
    another group (or is archived), its docs leave this group's context with
    it. This avoids the old write-once ``document.fleet_session_id`` stamp,
    which was set on creation and never unset — leaving every doc a session ever
    produced piled up here forever.

    Returns those documents newest first, shaped like ``discover`` matches so
    the Sessions "shared context" drawer reuses the existing document store
    instead of a bespoke per-session notes table. Read-only: no consult metrics
    are emitted and nothing is mutated.
    """

    member_document_ids = _group_member_document_ids(
        session, actor=actor, fleet_session=fleet_session, demo=demo
    )
    documents = [
        document
        for document in list_v2_documents_for_actor(session, actor, demo=demo)
        if document.id in member_document_ids
    ]
    documents.sort(
        key=lambda document: document.updated_at or document.created_at or _EPOCH,
        reverse=True,
    )

    entries: list[TaskforceSessionContextEntry] = []
    token_estimate = 0
    for document in documents[:limit]:
        summary = _summary_markdown(document)
        token_cost = _estimate_tokens(summary)
        token_estimate += token_cost
        entries.append(
            TaskforceSessionContextEntry(
                document_id=document.id,
                title=document.title,
                summary_markdown=summary,
                produced_by_client=document.produced_by_client,
                outcome=_outcome_for(document),
                last_touched_at=document.updated_at,
                token_cost=token_cost,
            )
        )

    return TaskforceSessionContextResponse(
        fleet_session_id=fleet_session.id,
        scope=fleet_session.name,
        entry_count=len(entries),
        token_estimate=token_estimate,
        inject_token_budget=INJECT_TOKEN_BUDGET,
        entries=entries,
    )


def _placeholder_rediscovery_cost(document: V2Document) -> int:
    """Pull the cached rediscovery cost computed by Phase 3 (TF-177).

    The column is populated on every doc mutation by
    ``refresh_v2_document_token_counts``; a backfill migration seeded
    existing rows. The placeholder name is kept so call sites can swap
    without churn if the source changes again.
    """

    return int(getattr(document, "rediscovery_cost_tokens", 0) or 0)
