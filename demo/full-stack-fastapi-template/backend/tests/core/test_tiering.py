"""Tier resolution + Search eligibility — pure unit tests, no DB.

Covers the full Stripe-status × price_id × BYOK matrix the routes
depend on. If any of these change, every Search gate decision shifts
with it, so the matrix needs to be lock-tight."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.core import tiering
from app.core.tiering import (
    SearchEligibility,
    Tier,
    can_use_search,
    resolve_tier,
    sync_subscription_tier,
)
from app.models import ByokCredential, User

PRO_PRICE = "price_pro_test"
MAX_PRICE = "price_max_test"


@pytest.fixture(autouse=True)
def _patch_price_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tier helper reads ``settings`` lazily; pin both price IDs
    so the tests don't depend on the deployment's real Stripe config."""

    monkeypatch.setattr(tiering.settings, "STRIPE_PRICE_ID_PRO", PRO_PRICE)
    monkeypatch.setattr(tiering.settings, "STRIPE_PRICE_ID_MAX", MAX_PRICE)
    monkeypatch.setattr(tiering.settings, "STRIPE_PRICE_ID", "price_legacy_pro")


def _make_user(
    *,
    status: str | None = None,
    price_id: str | None = None,
    is_superuser: bool = False,
    subscription_tier: str = "free",
) -> User:
    return User(
        id=uuid.uuid4(),
        email="t@example.com",
        hashed_password="x",
        is_superuser=is_superuser,
        stripe_subscription_status=status,
        stripe_price_id=price_id,
        subscription_tier=subscription_tier,
    )


def _make_byok(provider: str, *, revoked: bool = False) -> ByokCredential:
    return ByokCredential(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        provider=provider,  # type: ignore[arg-type]
        encrypted_api_key=b"x",
        key_fingerprint="…abcd",
        created_at=datetime.now(timezone.utc),
        revoked_at=datetime.now(timezone.utc) if revoked else None,
    )


# ---- resolve_tier ----------------------------------------------------


def test_resolve_tier_free_when_no_subscription() -> None:
    assert resolve_tier(_make_user()) == Tier.FREE


def test_resolve_tier_admin_for_superuser() -> None:
    assert resolve_tier(_make_user(is_superuser=True)) == Tier.ADMIN


def test_resolve_tier_free_when_inactive_status() -> None:
    user = _make_user(status="past_due", price_id=PRO_PRICE)
    assert resolve_tier(user) == Tier.FREE


def test_resolve_tier_free_when_unknown_price_id() -> None:
    user = _make_user(status="active", price_id="price_legacy")
    assert resolve_tier(user) == Tier.FREE


def test_resolve_tier_pro_when_active_pro_price() -> None:
    user = _make_user(status="active", price_id=PRO_PRICE)
    assert resolve_tier(user) == Tier.PRO


def test_resolve_tier_pro_for_legacy_checkout_price() -> None:
    user = _make_user(status="active", price_id="price_legacy_pro")
    assert resolve_tier(user) == Tier.PRO


def test_resolve_tier_from_stored_tier_when_price_id_missing() -> None:
    user = _make_user(status="active", subscription_tier="max")
    assert resolve_tier(user) == Tier.MAX


def test_resolve_tier_max_when_trialing_max_price() -> None:
    user = _make_user(status="trialing", price_id=MAX_PRICE)
    assert resolve_tier(user) == Tier.MAX


# ---- can_use_search --------------------------------------------------


def test_can_use_search_free_blocked_with_upgrade_reason() -> None:
    user = _make_user()
    eligibility = can_use_search(user, [])
    assert eligibility == SearchEligibility(
        tier=Tier.FREE, allowed=False, reason="upgrade_required", byok=[]
    )


def test_can_use_search_max_always_managed() -> None:
    user = _make_user(status="active", price_id=MAX_PRICE)
    out = can_use_search(user, [])
    assert out.allowed is True
    assert out.route == "managed"
    assert out.reason is None


def test_can_use_search_admin_routes_to_managed() -> None:
    user = _make_user(is_superuser=True)
    out = can_use_search(user, [])
    assert out.allowed is True
    assert out.tier == Tier.ADMIN
    assert out.route == "managed"


def test_sync_subscription_tier_persists_effective_tier() -> None:
    user = _make_user(status="active", price_id=PRO_PRICE)
    assert sync_subscription_tier(user) == Tier.PRO
    assert user.subscription_tier == "pro"


def test_can_use_search_pro_without_byok_blocked() -> None:
    user = _make_user(status="active", price_id=PRO_PRICE)
    out = can_use_search(user, [])
    assert out.allowed is False
    assert out.reason == "byok_required"
    assert out.route is None


def test_can_use_search_pro_with_anthropic_byok() -> None:
    user = _make_user(status="active", price_id=PRO_PRICE)
    out = can_use_search(user, [_make_byok("anthropic")])
    assert out.allowed is True
    assert out.route == "byok:anthropic"


def test_can_use_search_pro_with_openai_byok() -> None:
    user = _make_user(status="active", price_id=PRO_PRICE)
    out = can_use_search(user, [_make_byok("openai")])
    assert out.allowed is True
    assert out.route == "byok:openai"


def test_can_use_search_pro_revoked_byok_blocks() -> None:
    user = _make_user(status="active", price_id=PRO_PRICE)
    out = can_use_search(user, [_make_byok("openai", revoked=True)])
    assert out.allowed is False
    assert out.reason == "byok_required"


def test_can_use_search_max_does_not_override_to_byok() -> None:
    """Max users get managed routing even when they have BYOK on file.

    Premium tier = "we pay for the LLM"; user supplying a key while
    paying for Max is treated as a leftover from a downgrade attempt,
    not a request to switch routes."""

    user = _make_user(status="active", price_id=MAX_PRICE)
    out = can_use_search(user, [_make_byok("anthropic")])
    assert out.route == "managed"
