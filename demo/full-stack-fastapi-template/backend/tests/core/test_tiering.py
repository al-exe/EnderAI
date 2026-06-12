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
    default_comp_tier_for_new_user,
    resolve_public_tier,
    resolve_tier,
)
from app.models import ByokCredential, User

ADMIN_PRICE = "price_admin_test"
PRO_PRICE = "price_pro_test"
MAX_PRICE = "price_max_test"
TASKFORCE_PRO_PRICE = "price_taskforce_pro_live"
TASKFORCE_MAX_PRICE = "price_taskforce_max_live"


@pytest.fixture(autouse=True)
def _patch_price_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tier helper reads ``settings`` lazily; pin both price IDs
    so the tests don't depend on the deployment's real Stripe config."""

    monkeypatch.setattr(tiering.settings, "STRIPE_PRICE_ID", ADMIN_PRICE)
    monkeypatch.setattr(tiering.settings, "STRIPE_PRICE_ID_PRO", PRO_PRICE)
    monkeypatch.setattr(tiering.settings, "STRIPE_PRICE_ID_MAX", MAX_PRICE)
    monkeypatch.setattr(tiering.settings, "STRIPE_TASKFORCE_PRO", TASKFORCE_PRO_PRICE)
    monkeypatch.setattr(tiering.settings, "STRIPE_TASKFORCE_MAX", TASKFORCE_MAX_PRICE)


def _make_user(
    *,
    status: str | None = None,
    price_id: str | None = None,
    comp_tier: str | None = None,
) -> User:
    return User(
        id=uuid.uuid4(),
        email="t@example.com",
        hashed_password="x",
        stripe_subscription_status=status,
        stripe_price_id=price_id,
        comp_tier=comp_tier,
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


def test_resolve_tier_free_when_inactive_status() -> None:
    user = _make_user(status="past_due", price_id=PRO_PRICE)
    assert resolve_tier(user) == Tier.FREE


def test_resolve_tier_free_when_unknown_price_id() -> None:
    user = _make_user(status="active", price_id="price_legacy")
    assert resolve_tier(user) == Tier.FREE


def test_resolve_tier_pro_when_active_pro_price() -> None:
    user = _make_user(status="active", price_id=PRO_PRICE)
    assert resolve_tier(user) == Tier.PRO


def test_resolve_tier_max_when_trialing_max_price() -> None:
    user = _make_user(status="trialing", price_id=MAX_PRICE)
    assert resolve_tier(user) == Tier.MAX


def test_resolve_tier_admin_when_active_legacy_checkout_price() -> None:
    user = _make_user(status="active", price_id=ADMIN_PRICE)
    assert resolve_tier(user) == Tier.ADMIN
    assert resolve_public_tier(user) == "max"


def test_resolve_tier_maps_live_taskforce_prices() -> None:
    assert (
        resolve_tier(_make_user(status="active", price_id=TASKFORCE_PRO_PRICE))
        == Tier.PRO
    )
    assert (
        resolve_tier(_make_user(status="active", price_id=TASKFORCE_MAX_PRICE))
        == Tier.MAX
    )


# ---- comp_tier grant (new-user promo) --------------------------------


def test_comp_tier_raises_free_user_to_max() -> None:
    """The new-user promo grant: a user with no Stripe subscription but a
    stored comp_tier="max" resolves to Max."""

    user = _make_user(comp_tier="max")
    assert resolve_tier(user) == Tier.MAX
    assert resolve_public_tier(user) == "max"


def test_comp_tier_acts_as_floor_not_a_cap() -> None:
    """A lower comp grant never demotes a higher paid tier."""

    user = _make_user(status="active", price_id=MAX_PRICE, comp_tier="pro")
    assert resolve_tier(user) == Tier.MAX


def test_comp_tier_does_not_shadow_admin() -> None:
    user = _make_user(status="active", price_id=ADMIN_PRICE, comp_tier="max")
    assert resolve_tier(user) == Tier.ADMIN


def test_comp_tier_upgrades_pro_to_max() -> None:
    user = _make_user(status="active", price_id=PRO_PRICE, comp_tier="max")
    assert resolve_tier(user) == Tier.MAX


def test_comp_tier_none_leaves_stripe_tier_unchanged() -> None:
    assert resolve_tier(_make_user(comp_tier=None)) == Tier.FREE
    user = _make_user(status="active", price_id=PRO_PRICE, comp_tier=None)
    assert resolve_tier(user) == Tier.PRO


def test_comp_tier_invalid_value_is_ignored() -> None:
    """A typo'd grant degrades to "no grant" rather than raising."""

    assert resolve_tier(_make_user(comp_tier="platinum")) == Tier.FREE


def test_comp_tier_max_grants_search_access() -> None:
    """The grant flows through every tier-aware gate, including Search."""

    out = can_use_search(_make_user(comp_tier="max"), [])
    assert out.tier == Tier.MAX
    assert out.allowed is True
    assert out.route == "managed"


# ---- default_comp_tier_for_new_user (promo knob) ---------------------


def test_default_comp_tier_returns_configured_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tiering.settings, "NEW_USER_DEFAULT_TIER", "max")
    assert default_comp_tier_for_new_user() == "max"


def test_default_comp_tier_none_when_promo_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tiering.settings, "NEW_USER_DEFAULT_TIER", None)
    assert default_comp_tier_for_new_user() is None


def test_default_comp_tier_none_when_misconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tiering.settings, "NEW_USER_DEFAULT_TIER", "platinum")
    assert default_comp_tier_for_new_user() is None


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
    user = _make_user(status="active", price_id=ADMIN_PRICE)
    out = can_use_search(user, [])
    assert out.tier == Tier.ADMIN
    assert out.allowed is True
    assert out.route == "managed"
    assert out.reason is None


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
