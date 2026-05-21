"""Pragmatic scoring for hook-driven discovery (TF-175).

This is intentionally simpler than the MCP's TypeScript scoring engine
(``mcp/enderai-api-mcp/src/v2Documents/scoring/``). That engine has
conflict signals (tenant / repo / error-family / terminal-state) and a
weighted multi-signal architecture. Hooks fire on every user prompt and
need p95 < 500ms over a 200-doc library — so we trade some precision for
predictability and speed.

What we score on:
  * **Title overlap** — exact match (full strength) or token Jaccard
  * **Corpus overlap** — token Jaccard against title+description+summary+body
  * **File / symbol / error substring match** against the doc corpus
  * **Recency** — exponential decay over ``reuse_within_seconds`` (default 30d)

What's deliberately deferred to a follow-up:
  * Conflict signals (tenant / repo / error-family / terminal-state)
  * Outcome weighting beyond a passive ``outcome`` field on the result
  * Embedding-based recall

The output ``score`` lives in ``[0, 1]``. The confidence bands follow the
MCP's bandFor mapping (low < 0.30, medium < 0.65, high otherwise) so
downstream consumers don't have to relearn cutoffs.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Literal, Sequence

from app.models import V2Document, V2DocumentDetailsSection, V2DocumentParagraph

ConfidenceBand = Literal["high", "medium", "low"]

DEFAULT_RECENCY_HALF_LIFE_SECONDS = 30 * 24 * 3600  # 30d

# Weights — sum to 1.0 so the final ``score`` lives in [0, 1] without further
# normalization. Tunable from real-consult data in a follow-up.
WEIGHTS = {
    "title": 0.30,
    "corpus": 0.25,
    "files": 0.15,
    "symbols": 0.10,
    "errors": 0.05,
    "recency": 0.15,
}

_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for",
        "with", "by", "is", "are", "was", "were", "be", "been", "being",
        "this", "that", "these", "those", "it", "its", "as", "at", "from",
    }
)

_TOKEN_SPLIT = re.compile(r"[^\w./\-]+", flags=re.UNICODE)


def tokenize(value: str | None) -> list[str]:
    """Lowercase, split on non-word characters, drop short tokens + stopwords.

    Mirrors the TS ``tokenize`` in ``scoring/signals.ts`` so divergence
    between the two implementations stays bounded to *which* signals fire,
    not *how* tokens are extracted.
    """

    if not value:
        return []
    lowered = value.lower()
    parts = _TOKEN_SPLIT.split(lowered)
    return [p for p in parts if len(p) > 1 and p not in _STOPWORDS]


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    intersect = len(a & b)
    union = len(a) + len(b) - intersect
    if union == 0:
        return 0.0
    return intersect / union


def _flatten_body(paragraphs: Sequence[V2DocumentParagraph]) -> str:
    out: list[str] = []
    for paragraph in paragraphs:
        segments = paragraph.get("segments") if isinstance(paragraph, dict) else paragraph.segments  # type: ignore[union-attr]
        for segment in segments:
            text = segment.get("text") if isinstance(segment, dict) else segment.text  # type: ignore[union-attr]
            if text:
                out.append(text)
    return "\n".join(out)


def _flatten_details(sections: Sequence[V2DocumentDetailsSection]) -> str:
    out: list[str] = []
    for section in sections:
        markdown = section.get("markdown") if isinstance(section, dict) else section.markdown  # type: ignore[union-attr]
        if markdown:
            out.append(markdown)
    return "\n".join(out)


def _doc_corpus(doc: V2Document) -> str:
    return "\n".join(
        filter(
            None,
            [
                doc.title or "",
                doc.description or "",
                doc.human_summary or "",
                doc.ai_generated_summary or "",
                _flatten_body(doc.main_body or []),
                _flatten_details(doc.details_markdown_sections or []),
            ],
        )
    )


def _substring_match_ratio(needles: Iterable[str], haystack: str) -> tuple[float, list[str]]:
    """Return ``(ratio_matched, list_of_matched_needles)``.

    For file paths we also try the basename so ``app/foo/bar.py`` still
    matches a doc that only mentions ``bar.py``.
    """

    needles_list = [n.strip() for n in needles if n and n.strip()]
    if not needles_list:
        return 0.0, []
    hay_lower = haystack.lower()
    matched: list[str] = []
    for needle in needles_list:
        n_lower = needle.lower()
        if n_lower in hay_lower:
            matched.append(needle)
            continue
        # basename fallback for file paths
        if "/" in n_lower:
            basename = n_lower.rsplit("/", 1)[-1]
            if basename and basename != n_lower and basename in hay_lower:
                matched.append(needle)
    return len(matched) / len(needles_list), matched


def _recency_score(last_touched_at: datetime | None, half_life_seconds: int) -> float:
    if last_touched_at is None or half_life_seconds <= 0:
        return 0.0
    now = datetime.now(timezone.utc)
    if last_touched_at.tzinfo is None:
        last_touched_at = last_touched_at.replace(tzinfo=timezone.utc)
    age_seconds = max(0.0, (now - last_touched_at).total_seconds())
    return math.exp(-math.log(2) * age_seconds / half_life_seconds)


def band_for(score: float) -> ConfidenceBand:
    """Map a 0..1 score to {low, medium, high}.

    Cutoffs picked to match the TS engine's ``bandFor``: a high band fires
    around the same scoring volume in either implementation.
    """

    if score >= 0.65:
        return "high"
    if score >= 0.30:
        return "medium"
    return "low"


@dataclass(frozen=True)
class DiscoveryRequest:
    prompt: str
    title: str | None = None
    files: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    recent_commands: tuple[str, ...] = ()
    git_branch: str | None = None
    cwd: str | None = None
    recency_half_life_seconds: int = DEFAULT_RECENCY_HALF_LIFE_SECONDS


@dataclass(frozen=True)
class ScoredCandidate:
    document: V2Document
    score: float
    band: ConfidenceBand
    match_reasons: list[str]


def score_document(
    document: V2Document,
    request: DiscoveryRequest,
) -> ScoredCandidate:
    """Score one candidate doc against a request. Pure; no I/O."""

    corpus = _doc_corpus(document)
    request_tokens = set(tokenize(request.title or request.prompt))
    title_tokens = set(tokenize(document.title))
    corpus_tokens = set(tokenize(corpus))

    reasons: list[str] = []

    # --- title overlap ---
    title_score = 0.0
    if request.title and document.title and request.title.strip().lower() == document.title.strip().lower():
        title_score = 1.0
        reasons.append(f'Exact title match: "{document.title}"')
    else:
        title_score = _jaccard(title_tokens, request_tokens)
        if title_score > 0:
            shared = sorted(title_tokens & request_tokens)[:6]
            if shared:
                reasons.append(
                    "Title tokens overlap on " + ", ".join(f"'{t}'" for t in shared)
                )

    # --- corpus overlap ---
    corpus_score = _jaccard(corpus_tokens, request_tokens)
    if corpus_score >= 0.05:
        reasons.append(f"Doc body overlaps request tokens ({corpus_score:.0%})")

    # --- files / symbols / errors ---
    files_score, files_hit = _substring_match_ratio(request.files, corpus)
    symbols_score, symbols_hit = _substring_match_ratio(request.symbols, corpus)
    errors_score, errors_hit = _substring_match_ratio(request.errors, corpus)
    if files_hit:
        reasons.append("Files referenced: " + ", ".join(files_hit[:3]))
    if symbols_hit:
        reasons.append("Symbols referenced: " + ", ".join(symbols_hit[:3]))
    if errors_hit:
        reasons.append("Error strings referenced: " + ", ".join(errors_hit[:3]))

    # --- recency ---
    recency_score = _recency_score(
        document.updated_at, request.recency_half_life_seconds
    )

    total = (
        WEIGHTS["title"] * title_score
        + WEIGHTS["corpus"] * corpus_score
        + WEIGHTS["files"] * files_score
        + WEIGHTS["symbols"] * symbols_score
        + WEIGHTS["errors"] * errors_score
        + WEIGHTS["recency"] * recency_score
    )
    total = max(0.0, min(1.0, total))

    if not reasons and recency_score > 0.5:
        reasons.append("Recently updated")

    return ScoredCandidate(
        document=document,
        score=total,
        band=band_for(total),
        match_reasons=reasons,
    )


def rank_candidates(
    documents: Iterable[V2Document],
    request: DiscoveryRequest,
    *,
    k: int = 3,
    min_score: float = 0.3,
) -> list[ScoredCandidate]:
    """Score, filter, sort, slice. Caller passes already-fetched candidates."""

    scored = [score_document(doc, request) for doc in documents]
    above = [s for s in scored if s.score >= min_score]
    above.sort(key=lambda s: s.score, reverse=True)
    return above[: max(0, k)]
