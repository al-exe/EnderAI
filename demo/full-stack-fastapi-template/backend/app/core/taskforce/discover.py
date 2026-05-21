"""Discovery orchestrator (TF-175).

Wraps the scoring engine in actor-scoping + token-cost estimation +
metrics emission, so the route handler stays a thin shell.
"""

from __future__ import annotations

import re
import uuid
from typing import Sequence

from sqlmodel import Session

from app.core.metrics.events import record_document_consulted
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
    User,
    V2Document,
)

# Latency budget: cap the candidate list at the user's N most-recently-updated
# docs before scoring. Tuned for p95 < 500ms over a library of ~thousands.
CANDIDATE_LIMIT = 200

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
) -> TaskforceDiscoverResponse:
    """Score the actor's library against the request, record consults.

    Always returns a stable ``query_id`` (even when no matches clear
    ``min_score``) so the hook can correlate consult events back to a
    specific discover call.
    """

    query_id = uuid.uuid4()

    raw_candidates = list_v2_documents_for_actor(session, actor, demo=demo)
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
        )

    return TaskforceDiscoverResponse(query_id=query_id, matches=matches)


def _placeholder_rediscovery_cost(document: V2Document) -> int:
    """Coarse rediscovery cost estimate used until Phase 3 lands.

    Uses the cached ``summary_tokens`` + ``details_tokens`` on V2Document
    that already exist for the reuse-savings calculator. This is roughly
    "if you had to ingest this whole doc from scratch, that's the cost".
    Phase 3 (TF-177) replaces this with the §5.2 structural formula.
    """

    summary = int(getattr(document, "summary_tokens", 0) or 0)
    details = int(getattr(document, "details_tokens", 0) or 0)
    return summary + details
