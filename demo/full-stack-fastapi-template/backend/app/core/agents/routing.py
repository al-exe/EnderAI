"""Deterministic specialist routing (TF-196).

Given a prompt + recent files, pick the best-fit
:class:`~app.models.AgentSpecialist` for the actor. No LLM router —
just trigger overlap, linked-doc match, recency, and file overlap.

This is the hot-path code that fires on every ``/v2/taskforce/session/start``
call. Keep it pure (no I/O during scoring), cheap (no LLM, no embedding),
and observable (log timings).

Scoring shape::

    score = (
        0.45 * trigger_overlap          # routing_triggers token Jaccard
      + 0.35 * linked_doc_match_score    # max score across linked V2 docs
      + 0.10 * recency_boost             # exp decay on specialist last invoked
      + 0.10 * file_overlap              # request.files vs linked-doc corpora
    )

A negative trigger (``specialist.negative_triggers``) firing at strength
> 0.5 short-circuits the specialist out — even a strong positive match
gets vetoed when the prompt clearly belongs elsewhere (e.g. a "pricing
page copy" prompt should not route to the Billing Reliability
specialist).

The output band names mirror :mod:`app.core.taskforce.scoring`'s
``bandFor`` (high / medium / low) so downstream callers don't have to
relearn cutoffs.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlmodel import Session, col, select

from app.core.taskforce.scoring import DiscoveryRequest, score_document, tokenize
from app.models import (
    AgentSpecialist,
    AgentSpecialistDocumentLink,
    V2Document,
)

# Match the document-side recency half-life from
# ``app.core.taskforce.scoring`` so specialists and documents age out at
# the same rate.
DEFAULT_RECENCY_HALF_LIFE_SECONDS = 30 * 24 * 3600

# Negative trigger strength above which we veto the specialist entirely.
# Picked so a single multi-word negative trigger ("pricing page copy")
# matching the prompt is enough to short-circuit.
_NEGATIVE_VETO_THRESHOLD = 0.5

# Band cutoffs mirror ``scoring.py::band_for`` so the skill doesn't have
# to learn two confidence vocabularies.
_BAND_HIGH = 0.65
_BAND_MEDIUM = 0.40

# Weights — sum to 1.0 so the final score lives in [0, 1] without
# further normalization. Tunable from real routing data later.
_WEIGHTS = {
    "trigger_overlap": 0.45,
    "linked_doc_match": 0.35,
    "recency_boost": 0.10,
    "file_overlap": 0.10,
}


@dataclass(frozen=True)
class SpecialistMatchedDoc:
    """One V2 document linked to a routed specialist with its contribution."""

    document: V2Document
    anchor_id: str | None
    score: float


@dataclass(frozen=True)
class SpecialistScore:
    """Per-specialist score + the components that fed into it.

    ``reasons`` carries 2-3 short bullets the skill renders under
    "Why <specialist>:" — explanatory, not load-bearing for ranking.
    """

    specialist: AgentSpecialist
    score: float
    band: str  # "high" | "medium" | "low" | "none"
    reasons: list[str] = field(default_factory=list)
    matched_docs: list[SpecialistMatchedDoc] = field(default_factory=list)


def band_for(score: float) -> str:
    """Map a 0..1 score to ``"high"`` | ``"medium"`` | ``"low"``."""

    if score >= _BAND_HIGH:
        return "high"
    if score >= _BAND_MEDIUM:
        return "medium"
    return "low"


def _trigger_overlap(triggers: Sequence[str], prompt: str) -> float:
    """Fraction of triggers that match prompt tokens (phrase-wise).

    Multi-word triggers like "plan upgrade" check substring presence in
    the lowercased prompt so phrases don't have to be split into bag-of-
    words to land. Single-word triggers fall back to tokenized membership
    so we still get the stopword + length filtering from the document
    scorer.
    """

    if not triggers:
        return 0.0
    prompt_lower = prompt.lower()
    prompt_tokens = set(tokenize(prompt))
    matched = 0
    for trigger in triggers:
        t = trigger.strip().lower()
        if not t:
            continue
        # Multi-word phrase → substring check on raw prompt
        if " " in t or "." in t:
            if t in prompt_lower:
                matched += 1
            continue
        # Single token → tokenized-membership for stopword + len > 1
        if t in prompt_tokens:
            matched += 1
    return matched / len(triggers)


def _recency_boost(
    last_invoked_at: datetime | None, half_life_seconds: int
) -> float:
    """Exponential decay; ~1.0 for fresh use, ~0.5 at one half-life."""

    if last_invoked_at is None or half_life_seconds <= 0:
        return 0.0
    now = datetime.now(timezone.utc)
    if last_invoked_at.tzinfo is None:
        last_invoked_at = last_invoked_at.replace(tzinfo=timezone.utc)
    age_seconds = max(0.0, (now - last_invoked_at).total_seconds())
    return math.exp(-math.log(2) * age_seconds / half_life_seconds)


def _file_overlap(request_files: Sequence[str], linked_docs: Sequence[V2Document]) -> float:
    """Ratio of request files mentioned somewhere in any linked doc."""

    if not request_files:
        return 0.0
    if not linked_docs:
        return 0.0
    haystack = ""
    for doc in linked_docs:
        haystack += (doc.title or "") + "\n"
        haystack += (doc.description or "") + "\n"
        haystack += (doc.human_summary or "") + "\n"
        haystack += (doc.ai_generated_summary or "") + "\n"
        for section in doc.details_markdown_sections or []:
            markdown = (
                section.get("markdown")
                if isinstance(section, dict)
                else getattr(section, "markdown", "")
            )
            if markdown:
                haystack += markdown + "\n"
    haystack_lower = haystack.lower()
    matched = 0
    for path in request_files:
        p = path.strip().lower()
        if not p:
            continue
        if p in haystack_lower:
            matched += 1
            continue
        # Basename fallback for absolute paths
        if "/" in p:
            base = p.rsplit("/", 1)[-1]
            if base and base in haystack_lower:
                matched += 1
    return matched / len(request_files)


def _format_reasons(
    specialist: AgentSpecialist,
    *,
    trigger_overlap: float,
    linked_doc_match_score: float,
    recency_boost: float,
    file_overlap: float,
    matched_doc_titles: list[str],
) -> list[str]:
    """Build 2-3 short bullets for the skill's "Why <specialist>:" block."""

    reasons: list[str] = []

    # Trigger overlap is the strongest single signal — name what fired.
    if trigger_overlap >= 0.3:
        reasons.append(
            f"Strong match on routing triggers: "
            f"{round(trigger_overlap * 100)}% overlap with prompt"
        )
    elif trigger_overlap > 0:
        reasons.append(
            f"Partial match on routing triggers "
            f"({round(trigger_overlap * 100)}%)"
        )

    if linked_doc_match_score >= 0.30 and matched_doc_titles:
        top_title = matched_doc_titles[0]
        reasons.append(
            f"Linked knowledge matches the request — top: \"{top_title}\""
        )

    if file_overlap >= 0.5:
        reasons.append(
            f"Request files referenced in linked docs "
            f"({round(file_overlap * 100)}%)"
        )

    if recency_boost >= 0.5 and not any("Recently" in r for r in reasons):
        reasons.append("Recently invoked")

    if not reasons:
        reasons.append(
            f"Best-fit specialist for this prompt based on "
            f"role: {specialist.role}"
        )

    return reasons[:3]


def score_specialist(
    specialist: AgentSpecialist,
    request: DiscoveryRequest,
    linked_docs: Sequence[V2Document],
    *,
    last_invoked_at: datetime | None = None,
    recency_half_life_seconds: int = DEFAULT_RECENCY_HALF_LIFE_SECONDS,
) -> SpecialistScore:
    """Score one specialist against a request. Pure; no I/O.

    Caller passes ``linked_docs`` (the V2 documents already linked to
    this specialist via ``AgentSpecialistDocumentLink``) so this stays
    pure and we don't N+1 the DB during the scoring loop.

    ``last_invoked_at`` is the max ``occurred_at`` across the
    specialist's prior ``metrics_event`` rows (passed in so callers can
    batch the query rather than running it per-specialist).
    """

    # Veto on negative trigger before doing any other work.
    negative_hit = _trigger_overlap(specialist.negative_triggers, request.prompt)
    if negative_hit > _NEGATIVE_VETO_THRESHOLD:
        return SpecialistScore(
            specialist=specialist,
            score=0.0,
            band="none",
            reasons=[
                f"Negative trigger fired (strength {negative_hit:.2f}); "
                "routing to a different specialist"
            ],
            matched_docs=[],
        )

    trigger_overlap = _trigger_overlap(specialist.routing_triggers, request.prompt)

    # Linked-doc match score: run the existing document scorer over each
    # linked doc, take the max. Keep the per-doc scores so we can return
    # the top contributors to the caller (for the skill's preview).
    per_doc: list[SpecialistMatchedDoc] = []
    for doc in linked_docs:
        doc_score = score_document(doc, request)
        per_doc.append(
            SpecialistMatchedDoc(
                document=doc,
                anchor_id=doc_score.matched_anchor_id,
                score=doc_score.score,
            )
        )
    per_doc.sort(key=lambda m: m.score, reverse=True)
    linked_doc_match_score = per_doc[0].score if per_doc else 0.0

    recency_boost_val = _recency_boost(
        last_invoked_at, recency_half_life_seconds
    )
    file_overlap_val = _file_overlap(
        request.files, [m.document for m in per_doc]
    )

    score = (
        _WEIGHTS["trigger_overlap"] * trigger_overlap
        + _WEIGHTS["linked_doc_match"] * linked_doc_match_score
        + _WEIGHTS["recency_boost"] * recency_boost_val
        + _WEIGHTS["file_overlap"] * file_overlap_val
    )
    score = max(0.0, min(1.0, score))
    band = band_for(score)

    reasons = _format_reasons(
        specialist,
        trigger_overlap=trigger_overlap,
        linked_doc_match_score=linked_doc_match_score,
        recency_boost=recency_boost_val,
        file_overlap=file_overlap_val,
        matched_doc_titles=[m.document.title for m in per_doc if m.score > 0],
    )

    return SpecialistScore(
        specialist=specialist,
        score=score,
        band=band,
        reasons=reasons,
        matched_docs=per_doc[:3],
    )


def route_specialist(
    session: Session,
    *,
    actor,  # User; typed broadly to avoid a circular import
    request: DiscoveryRequest,
    demo: bool,
    min_band: str = "medium",
) -> SpecialistScore | None:
    """Pick the best-fit specialist for a request, or ``None``.

    Returns ``None`` when no candidate clears ``min_band``. ``/tf`` then
    falls back to plain document matches.

    Performance note: fetches all active specialists for the actor in
    one query, then runs the pure scoring loop in-process. For demo
    seeds N=5 specialists; this stays well under the 100ms p95 budget
    the ticket calls out.
    """

    from app.core.agents.access import build_agent_specialist_acl_filter

    # Lazy import to avoid touching MetricsEvent during agents-only paths.
    from app.models import METRICS_EVENT_DOCUMENT_CONSULTED, MetricsEvent

    acl_filter = build_agent_specialist_acl_filter(actor, demo=demo)
    specialists = list(
        session.exec(
            select(AgentSpecialist)
            .where(AgentSpecialist.status == "active")
            .where(acl_filter)
        ).all()
    )
    if not specialists:
        return None

    # Batch: pull linked docs for every candidate specialist in one query.
    specialist_ids = [s.id for s in specialists]
    link_rows = list(
        session.exec(
            select(
                AgentSpecialistDocumentLink.specialist_id,
                V2Document,
            )
            .join(
                V2Document,
                col(V2Document.id) == col(AgentSpecialistDocumentLink.document_id),
            )
            .where(col(AgentSpecialistDocumentLink.specialist_id).in_(specialist_ids))
        ).all()
    )
    links_by_specialist: dict = {sid: [] for sid in specialist_ids}
    for sid, doc in link_rows:
        links_by_specialist[sid].append(doc)

    # Batch: pull last-invoked-at per specialist via metrics_event join.
    # Done in one query per specialist slug list; keeps the loop O(1) DB.
    slugs = [s.slug for s in specialists]
    last_invoked_rows = list(
        session.exec(
            # Use the JSONB ``payload->>'specialist_slug'`` we tag on each
            # consult event (TF-196 — this same ticket wires the writes).
            # Until those rows exist this returns empty; specialists then
            # score with recency_boost = 0, which is fine.
            select(
                MetricsEvent.payload["specialist_slug"].astext,  # type: ignore[index]
                MetricsEvent.occurred_at,
            )
            .where(MetricsEvent.kind == METRICS_EVENT_DOCUMENT_CONSULTED)
            .where(MetricsEvent.user_id == actor.id)
            .where(
                MetricsEvent.payload["specialist_slug"].astext.in_(slugs)  # type: ignore[index]
            )
        ).all()
    )
    last_invoked_by_slug: dict[str, datetime] = {}
    for slug, occurred_at in last_invoked_rows:
        if slug and (
            slug not in last_invoked_by_slug
            or occurred_at > last_invoked_by_slug[slug]
        ):
            last_invoked_by_slug[slug] = occurred_at

    # Score every candidate, then pick the best one that clears min_band.
    min_band_threshold = _BAND_HIGH if min_band == "high" else _BAND_MEDIUM
    scored: list[SpecialistScore] = []
    for specialist in specialists:
        linked_docs = links_by_specialist.get(specialist.id, [])
        last_invoked = last_invoked_by_slug.get(specialist.slug)
        result = score_specialist(
            specialist,
            request,
            linked_docs,
            last_invoked_at=last_invoked,
        )
        scored.append(result)

    scored.sort(key=lambda s: s.score, reverse=True)
    top = scored[0] if scored else None
    if top is None or top.score < min_band_threshold:
        return None
    return top
