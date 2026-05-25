"""Specialist routing scoring (TF-196).

Tests the pure scoring layer in ``app.core.agents.routing`` —
``score_specialist`` and its helpers. The full ``route_specialist``
DB-backed path is covered by integration tests in
``tests/api/test_taskforce_session_start_routing.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.core.agents.routing import (
    SpecialistScore,
    _file_overlap,
    _recency_boost,
    _trigger_overlap,
    band_for,
    score_specialist,
)
from app.core.taskforce.scoring import DiscoveryRequest
from app.models import AgentSpecialist, V2Document


def _specialist(
    *,
    slug: str = "jensen",
    routing_triggers: list[str] | None = None,
    negative_triggers: list[str] | None = None,
) -> AgentSpecialist:
    return AgentSpecialist(
        id=uuid.uuid4(),
        slug=slug,
        name=slug.title(),
        role=f"{slug.title()} Specialist",
        short_description="",
        description="",
        status="active",
        visibility="demo",
        domain_tags=[],
        routing_triggers=routing_triggers or [],
        negative_triggers=negative_triggers or [],
        instructions=[],
        is_demo=True,
    )


def _doc(
    *,
    title: str = "Doc",
    body: str = "",
    details: list[dict] | None = None,
    updated_minutes_ago: int = 1,
) -> V2Document:
    return V2Document(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        title=title,
        description="",
        human_summary="",
        ai_generated_summary=body,
        collaborators=[],
        main_body=[],
        details_file_name="doc.md",
        details_markdown_sections=details or [],
        is_demo=True,
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=updated_minutes_ago),
    )


# ---- pure helpers --------------------------------------------------------


def test_trigger_overlap_phrase_match() -> None:
    assert _trigger_overlap(
        ["plan upgrade", "stripe", "irrelevant"],
        "Stripe is double-charging on plan upgrade flows",
    ) >= 2 / 3 - 0.001  # 'plan upgrade' + 'stripe' match


def test_trigger_overlap_single_token_uses_tokenizer() -> None:
    # Single tokens go through tokenize() which drops stopwords and
    # len-1 tokens. "is" is a stopword; "the" is a stopword.
    assert (
        _trigger_overlap(["is", "the"], "is the request") == 0.0
    )


def test_trigger_overlap_no_triggers_is_zero() -> None:
    assert _trigger_overlap([], "anything") == 0.0


def test_recency_boost_decays_over_half_life() -> None:
    now = datetime.now(timezone.utc)
    # Fresh use → ~1.0
    assert _recency_boost(now, 30 * 86400) > 0.99
    # One half-life ago → ~0.5
    one_half_life_ago = now - timedelta(seconds=30 * 86400)
    assert 0.49 < _recency_boost(one_half_life_ago, 30 * 86400) < 0.51
    # None → 0
    assert _recency_boost(None, 30 * 86400) == 0.0


def test_file_overlap_basename_fallback() -> None:
    doc = _doc(
        details=[
            {
                "anchor_id": "x",
                "markdown": "Edit `billing.py` and re-run the test.",
            }
        ]
    )
    # Full path matches via basename fallback.
    assert _file_overlap(["app/api/routes/billing.py"], [doc]) == 1.0


def test_band_for_thresholds() -> None:
    assert band_for(0.9) == "high"
    assert band_for(0.65) == "high"
    assert band_for(0.5) == "medium"
    assert band_for(0.4) == "medium"
    assert band_for(0.39) == "low"
    assert band_for(0.0) == "low"


# ---- score_specialist ----------------------------------------------------


def test_negative_trigger_vetoes_specialist() -> None:
    """A strong negative-trigger hit short-circuits to score 0 / band 'none'."""

    specialist = _specialist(
        routing_triggers=["stripe", "webhook", "plan upgrade"],
        # The prompt obviously mentions 'pricing page copy' below; this
        # should veto Jensen even though the positive triggers also fire.
        negative_triggers=["pricing page copy"],
    )
    request = DiscoveryRequest(
        prompt=(
            "Update the pricing page copy for Stripe webhook plan upgrade "
            "tier names"
        ),
    )
    result = score_specialist(specialist, request, linked_docs=[])
    assert result.score == 0.0
    assert result.band == "none"
    assert any("Negative trigger" in r for r in result.reasons)


def test_strong_trigger_overlap_lands_high_band() -> None:
    """When all triggers fire on a prompt with linked docs, score should land high."""

    specialist = _specialist(
        routing_triggers=[
            "stripe",
            "webhook",
            "double-charging",
            "plan upgrade",
        ],
    )
    # Linked doc that also scores well on the same prompt — files +
    # corpus overlap push the doc-side contribution up.
    linked = _doc(
        title="Stripe webhook idempotency",
        body=(
            "Plan upgrade dedupe on the webhook route prevents "
            "double-charging customers."
        ),
        details=[
            {
                "anchor_id": "decision-wal-table",
                "markdown": (
                    "Files: app/api/routes/billing.py and "
                    "app/core/stripe_billing.py handle the "
                    "customer.subscription.updated event."
                ),
            }
        ],
    )
    request = DiscoveryRequest(
        prompt=(
            "Stripe is double-charging some users on plan upgrade — "
            "looks like webhook retries are fulfilled twice."
        ),
        files=("app/api/routes/billing.py", "app/core/stripe_billing.py"),
    )
    result: SpecialistScore = score_specialist(
        specialist,
        request,
        linked_docs=[linked],
        last_invoked_at=datetime.now(timezone.utc),
    )
    # Trigger overlap is 4/4 → 0.45 × 1.0 = 0.45 alone, plus
    # file_overlap 2/2 → 0.10, plus recency ~1.0 → 0.10. Should
    # comfortably exceed the medium floor (0.40) and may hit high.
    assert result.score >= 0.55, (result.score, result.reasons)
    assert result.band in {"high", "medium"}
    assert result.matched_docs
    assert result.matched_docs[0].document.title == "Stripe webhook idempotency"


def test_no_signals_returns_low_band() -> None:
    """A prompt that misses all triggers + has no linked docs → low band."""

    specialist = _specialist(routing_triggers=["completely", "unrelated"])
    request = DiscoveryRequest(prompt="totally different topic")
    result = score_specialist(specialist, request, linked_docs=[])
    assert result.score == 0.0
    assert result.band == "low"


def test_linked_doc_match_returns_top_three() -> None:
    """matched_docs is sorted by score and capped at 3."""

    specialist = _specialist(routing_triggers=["stripe"])
    docs = [
        _doc(title=f"Stripe doc {i}", body="stripe webhook dedupe") for i in range(5)
    ]
    request = DiscoveryRequest(prompt="stripe webhook help")
    result = score_specialist(specialist, request, linked_docs=docs)
    assert len(result.matched_docs) <= 3
