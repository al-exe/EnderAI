"""Tier resolution + Search eligibility.

First piece of code that introduces a real tier model. Until Phase 1 of
Search, billing was a single is-subscription-active boolean — this
module maps Stripe price_ids onto Free / Pro / Max and exposes the
``can_use_search`` decision so the Search routes don't have to know how
billing is configured.

Other features that need tier-aware gating should compose against
``resolve_tier`` rather than re-reading ``user.stripe_price_id``."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from app.core.config import settings
from app.models import ByokCredential, User

ACTIVE_SUBSCRIPTION_STATUSES: set[str] = {"active", "trialing"}


class Tier(StrEnum):
    FREE = "free"
    PRO = "pro"
    MAX = "max"
    ADMIN = "admin"


def _price_id_to_tier() -> dict[str, Tier]:
    """Built lazily so test code that monkeypatches ``settings`` after
    import time sees the override."""

    mapping: dict[str, Tier] = {}
    if settings.STRIPE_PRICE_ID_PRO:
        mapping[settings.STRIPE_PRICE_ID_PRO] = Tier.PRO
    if settings.STRIPE_PRICE_ID_MAX:
        mapping[settings.STRIPE_PRICE_ID_MAX] = Tier.MAX
    if settings.STRIPE_PRICE_ID and settings.STRIPE_PRICE_ID not in mapping:
        mapping[settings.STRIPE_PRICE_ID] = Tier.PRO
    return mapping


def normalize_tier(value: str | None) -> Tier:
    if not value:
        return Tier.FREE
    try:
        return Tier(value)
    except ValueError:
        return Tier.FREE


def tier_from_price_id(price_id: str | None) -> Tier | None:
    if not price_id:
        return None
    return _price_id_to_tier().get(price_id)


def resolve_tier(user: User) -> Tier:
    """Resolve a user's current effective tier.

    Admins are always Admin. Non-admin paid tiers are live only when
    Stripe says the subscription is active/trialing. Cancelled/past_due
    subscriptions fall back to Free immediately even if ``stripe_price_id``
    or the stored ``subscription_tier`` still says Pro/Max."""

    if user.is_superuser:
        return Tier.ADMIN

    if user.stripe_subscription_status not in ACTIVE_SUBSCRIPTION_STATUSES:
        return Tier.FREE

    price_tier = tier_from_price_id(user.stripe_price_id)
    if price_tier in {Tier.PRO, Tier.MAX}:
        return price_tier

    stored_tier = normalize_tier(getattr(user, "subscription_tier", None))
    if stored_tier in {Tier.PRO, Tier.MAX}:
        return stored_tier
    return Tier.FREE


def sync_subscription_tier(user: User) -> Tier:
    """Persist the effective account tier for API consumers and gates."""

    tier = resolve_tier(user)
    user.subscription_tier = tier.value
    return tier


@dataclass(frozen=True)
class SearchEligibility:
    """Internal decision shape; mirrors ``SearchEligibilityPublic`` for
    the wire response but stays as a plain dataclass to keep this
    module free of Pydantic / SQLModel deps."""

    tier: Tier
    allowed: bool
    route: Literal["managed", "byok:anthropic", "byok:openai"] | None = None
    reason: Literal["upgrade_required", "byok_required"] | None = None
    byok: list[ByokCredential] = field(default_factory=list)


def _active_byok(creds: list[ByokCredential]) -> ByokCredential | None:
    for c in creds:
        if c.revoked_at is None:
            return c
    return None


def can_use_search(
    user: User, byok_credentials: list[ByokCredential]
) -> SearchEligibility:
    """Resolve whether the user is allowed to issue a Search query and,
    if so, how the LLM call should be routed.

    Routing rules:
      - Admin/Max → always routes through our managed Claude credential.
      - Pro       → must supply BYOK (anthropic OR openai); we route through it.
      - Free      → never allowed; UI shows the upsell card.

    BYOK *does not* override managed routing on Max — Max users opted
    into "we pay for the LLM," and we don't second-guess that choice
    here. If a Max user wants BYOK semantics, they downgrade to Pro."""

    tier = resolve_tier(user)

    if tier in {Tier.ADMIN, Tier.MAX}:
        return SearchEligibility(
            tier=tier, allowed=True, route="managed", byok=byok_credentials
        )

    if tier == Tier.PRO:
        active = _active_byok(byok_credentials)
        if active is not None:
            route: Literal["byok:anthropic", "byok:openai"] = (
                "byok:anthropic" if active.provider == "anthropic" else "byok:openai"
            )
            return SearchEligibility(
                tier=tier, allowed=True, route=route, byok=byok_credentials
            )
        return SearchEligibility(
            tier=tier,
            allowed=False,
            reason="byok_required",
            byok=byok_credentials,
        )

    return SearchEligibility(
        tier=tier,
        allowed=False,
        reason="upgrade_required",
        byok=byok_credentials,
    )
