"""Unit tests for the Taskforce hook scoring engine (TF-175).

These tests are deliberately DB-free — the scoring engine is pure. We
fabricate ``V2Document`` instances with only the fields the scoring
module reads.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.taskforce.scoring import (
    DEFAULT_RECENCY_HALF_LIFE_SECONDS,
    DiscoveryRequest,
    band_for,
    rank_candidates,
    score_document,
    tokenize,
)
from app.models import V2Document


def _doc(
    *,
    title: str = "Untitled",
    description: str = "",
    human_summary: str = "",
    ai_generated_summary: str = "",
    main_body: list | None = None,
    details_markdown_sections: list | None = None,
    updated_at: datetime | None = None,
) -> V2Document:
    return V2Document(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        title=title,
        description=description,
        human_summary=human_summary,
        ai_generated_summary=ai_generated_summary,
        main_body=main_body or [],
        details_file_name="",
        details_markdown_sections=details_markdown_sections or [],
        updated_at=updated_at or datetime.now(timezone.utc),
    )


def test_tokenize_drops_stopwords_and_short_tokens() -> None:
    assert tokenize("The Library Page refactor") == ["library", "page", "refactor"]


def test_tokenize_keeps_slash_separated_paths() -> None:
    assert "src/foo.py" in tokenize("touched src/foo.py")


def test_tokenize_empty_input() -> None:
    assert tokenize("") == []
    assert tokenize(None) == []


def test_band_for_cutoffs_match_design() -> None:
    assert band_for(0.7) == "high"
    assert band_for(0.65) == "high"
    assert band_for(0.5) == "medium"
    assert band_for(0.3) == "medium"
    assert band_for(0.29) == "low"
    assert band_for(0.0) == "low"


def test_exact_title_match_scores_high() -> None:
    doc = _doc(title="TF-156 metrics polish")
    request = DiscoveryRequest(prompt="anything", title="TF-156 metrics polish")
    result = score_document(doc, request)
    assert result.score >= 0.30 * 1.0  # title weight contributes a full 0.30
    assert "Exact title match" in result.match_reasons[0]


def test_token_overlap_in_title_contributes() -> None:
    doc = _doc(title="Library card polish")
    request = DiscoveryRequest(prompt="fix library card alignment")
    result = score_document(doc, request)
    assert result.score > 0
    assert any("Title tokens overlap" in reason for reason in result.match_reasons)


def test_file_substring_match_contributes_and_uses_basename() -> None:
    doc = _doc(
        title="Refactor",
        description="Updated src/components/Library.tsx and friends.",
    )
    request = DiscoveryRequest(
        prompt="why is the library slow",
        files=("Library.tsx",),
    )
    result = score_document(doc, request)
    assert result.score > 0
    assert any("Library.tsx" in reason for reason in result.match_reasons)


def test_recency_boosts_recent_docs() -> None:
    now = datetime.now(timezone.utc)
    fresh = _doc(title="metrics", updated_at=now - timedelta(hours=1))
    stale = _doc(title="metrics", updated_at=now - timedelta(days=180))
    request = DiscoveryRequest(prompt="check metrics")
    fresh_score = score_document(fresh, request).score
    stale_score = score_document(stale, request).score
    assert fresh_score > stale_score


def test_rank_candidates_filters_below_min_score_and_caps_k() -> None:
    request = DiscoveryRequest(prompt="library polish")
    candidates = [
        _doc(title="Library polish"),
        _doc(title="completely unrelated banana yacht"),
        _doc(title="library card layout"),
        _doc(title="library tree node alignment"),
    ]
    top = rank_candidates(candidates, request, k=3, min_score=0.1)
    assert len(top) <= 3
    # All matches should mention library/polish in some signal
    assert all(c.score >= 0.1 for c in top)
    assert all("library" in c.document.title.lower() for c in top)


def test_rank_candidates_empty_input_returns_empty() -> None:
    request = DiscoveryRequest(prompt="anything")
    assert rank_candidates([], request) == []


def test_default_recency_half_life_is_30_days() -> None:
    assert DEFAULT_RECENCY_HALF_LIFE_SECONDS == 30 * 24 * 3600
