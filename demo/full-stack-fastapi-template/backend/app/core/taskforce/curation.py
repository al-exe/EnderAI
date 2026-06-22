"""Quality gate for offline evolution writes (T3).

Every auto-create (T1) and auto-update (T2/T4) passes through
``evaluate_curation_gate`` before mutating Library documents. Scores
confidence, detects contradictions with high-confidence existing content,
and stamps freshness signals on allowed writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from app.core.taskforce.evolution_summary import StoredEvolutionSummary
from app.core.taskforce.scoring import tokenize
from app.models import V2Document, get_datetime_utc

# Sub-threshold confidence: block updates; creates may proceed as provisional.
TAU_CONFIDENCE = 0.35

# Contradiction checks apply only when the target doc is already high-confidence.
HIGH_CONFIDENCE_FOR_CONTRADICTION = 0.65

# Docs without a recent verification stamp are flagged stale after this TTL.
EVOLUTION_STALE_TTL_SECONDS = 90 * 24 * 3600  # 90d

CurationAction = Literal["create", "update"]
CurationBlockReason = Literal["low_confidence", "contradiction"]

_NEGATION_PAIRS: tuple[tuple[str, str], ...] = (
    ("should", "should not"),
    ("must", "must not"),
    ("always", "never"),
    ("enable", "disable"),
    ("recommend", "avoid"),
    ("use", "do not use"),
    ("works", "does not work"),
    ("is safe", "is unsafe"),
    ("required", "forbidden"),
)


@dataclass(frozen=True)
class ContradictionResult:
    existing_phrase: str
    incoming_phrase: str
    overlap_tokens: tuple[str, ...]


@dataclass(frozen=True)
class CurationGateResult:
    allowed: bool
    confidence: float
    provisional: bool = False
    block_reason: CurationBlockReason | None = None
    contradiction: ContradictionResult | None = None


def score_evolution_confidence(
    *,
    materiality_score: float,
    match_score: float = 0.0,
    has_decisions: bool = False,
    has_outcome: bool = False,
) -> float:
    """Blend materiality, matcher score, and corroboration into [0, 1]."""

    base = max(materiality_score, match_score * 0.5)
    corroboration = 0.0
    if has_decisions:
        corroboration += 0.1
    if has_outcome:
        corroboration += 0.05
    blended = base * 0.75 + match_score * 0.25 + corroboration
    return min(1.0, max(0.0, blended))


def _document_body_text(document: V2Document) -> str:
    parts: list[str] = []
    for field in (
        document.title,
        document.description,
        document.ai_generated_summary,
        document.human_summary,
    ):
        if field:
            parts.append(str(field))
    for paragraph in document.main_body or []:
        segments = (
            paragraph.get("segments")
            if isinstance(paragraph, dict)
            else paragraph.segments
        )
        for segment in segments or []:
            text = (
                segment.get("text")
                if isinstance(segment, dict)
                else segment.text
            )
            if text:
                parts.append(str(text))
    return "\n".join(parts)


def detect_contradiction(
    document: V2Document,
    *,
    summary_points: list[str],
    decisions: list[str] | None = None,
) -> ContradictionResult | None:
    """Return a contradiction when incoming text negates high-confidence content."""

    existing_confidence = document.evolution_confidence
    if existing_confidence is None or existing_confidence < HIGH_CONFIDENCE_FOR_CONTRADICTION:
        return None

    corpus = _document_body_text(document).lower()
    if not corpus.strip():
        return None

    incoming = " ".join([*summary_points, *(decisions or [])]).lower()
    if not incoming.strip():
        return None

    corpus_tokens = set(tokenize(corpus))
    incoming_tokens = set(tokenize(incoming))
    overlap = corpus_tokens & incoming_tokens
    if len(overlap) < 2:
        return None

    for affirmative, negative in _NEGATION_PAIRS:
        if affirmative in corpus and negative in incoming:
            return ContradictionResult(
                existing_phrase=affirmative,
                incoming_phrase=negative,
                overlap_tokens=tuple(sorted(overlap))[:8],
            )
        if negative in corpus and affirmative in incoming:
            return ContradictionResult(
                existing_phrase=negative,
                incoming_phrase=affirmative,
                overlap_tokens=tuple(sorted(overlap))[:8],
            )

    return None


def is_evolution_stale(
    document: V2Document,
    *,
    now: datetime | None = None,
) -> bool:
    """True when the doc is explicitly flagged or past the verification TTL."""

    if document.evolution_stale:
        return True

    verified_at = document.last_verified_at
    if verified_at is None:
        return bool(document.auto_created)

    reference = now or datetime.now(timezone.utc)
    if verified_at.tzinfo is None:
        verified_at = verified_at.replace(tzinfo=timezone.utc)
    age_seconds = (reference - verified_at).total_seconds()
    return age_seconds > EVOLUTION_STALE_TTL_SECONDS


def stamp_freshness(
    document: V2Document,
    *,
    confidence: float,
    provisional: bool = False,
) -> None:
    """Refresh verification metadata after an allowed auto-write."""

    document.evolution_confidence = confidence
    document.last_verified_at = get_datetime_utc()
    document.evolution_stale = provisional


def flag_contradiction_on_document(
    document: V2Document,
    contradiction: ContradictionResult,
    *,
    source_session_id: str,
) -> None:
    """Mark a doc stale and record the competing claim for future review (T6)."""

    provenance = dict(document.evolution_provenance or {})
    provenance["curation_contradiction"] = {
        "source_session_id": source_session_id,
        "existing_phrase": contradiction.existing_phrase,
        "incoming_phrase": contradiction.incoming_phrase,
        "overlap_tokens": list(contradiction.overlap_tokens),
    }
    document.evolution_provenance = provenance
    document.evolution_stale = True


def evaluate_curation_gate(
    *,
    action: CurationAction,
    stored: StoredEvolutionSummary,
    match_score: float = 0.0,
    document: V2Document | None = None,
) -> CurationGateResult:
    """Decide whether an offline evolution write may proceed."""

    confidence = score_evolution_confidence(
        materiality_score=stored.materiality_score,
        match_score=match_score,
        has_decisions=bool(stored.decisions),
        has_outcome=bool(stored.outcome),
    )

    if action == "update" and document is not None:
        contradiction = detect_contradiction(
            document,
            summary_points=list(stored.summary_points),
            decisions=list(stored.decisions),
        )
        if contradiction is not None:
            return CurationGateResult(
                allowed=False,
                confidence=confidence,
                block_reason="contradiction",
                contradiction=contradiction,
            )

    if confidence < TAU_CONFIDENCE:
        if action == "create":
            return CurationGateResult(
                allowed=True,
                confidence=confidence,
                provisional=True,
            )
        return CurationGateResult(
            allowed=False,
            confidence=confidence,
            block_reason="low_confidence",
        )

    return CurationGateResult(allowed=True, confidence=confidence)
