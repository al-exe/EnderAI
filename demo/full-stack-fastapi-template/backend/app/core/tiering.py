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
from enum import Enum
from typing import Literal

from app.core.config import settings
from app.models import ByokCredential, User

ACTIVE_SUBSCRIPTION_STATUSES: set[str] = {"active", "trialing"}
PublicTier = Literal["free", "pro", "max"]


# Use the (str, Enum) mixin rather than enum.StrEnum — StrEnum landed
# in Python 3.11 and prod runs 3.10 (see backend/Dockerfile FROM line).
# Behavior is equivalent for our purposes: ``Tier.FREE.value == "free"``
# and ``Tier.FREE == "free"`` both hold.
class Tier(str, Enum):
    FREE = "free"
    PRO = "pro"
    MAX = "max"
    ADMIN = "admin"


# Ordering used to combine a complimentary grant with a paid tier. The
# higher rank wins, so a comp grant only ever *raises* a user's tier.
# ADMIN sits above MAX so a comp="max" never shadows the legacy
# admin-checkout price.
_TIER_RANK: dict[Tier, int] = {
    Tier.FREE: 0,
    Tier.PRO: 1,
    Tier.MAX: 2,
    Tier.ADMIN: 3,
}


def _coerce_tier(value: str | None) -> Tier | None:
    """Parse a stored/configured tier string into a ``Tier``.

    Unknown or empty values yield ``None`` rather than raising, so a
    typo'd ``comp_tier`` / ``NEW_USER_DEFAULT_TIER`` degrades to "no
    grant" instead of taking down tier resolution on every request."""

    if not value:
        return None
    try:
        return Tier(value)
    except ValueError:
        return None


def default_comp_tier_for_new_user() -> str | None:
    """Complimentary tier auto-granted to every newly created user while
    the new-user promo is running.

    Returns the canonical ``comp_tier`` value to store (e.g. ``"max"``)
    or ``None`` when the promo is off (``NEW_USER_DEFAULT_TIER`` unset)
    or misconfigured. Read lazily so tests can monkeypatch ``settings``."""

    tier = _coerce_tier(settings.NEW_USER_DEFAULT_TIER)
    return tier.value if tier is not None else None


def _price_id_to_tier() -> dict[str, Tier]:
    """Built lazily so test code that monkeypatches ``settings`` after
    import time sees the override."""

    mapping: dict[str, Tier] = {}
    if settings.STRIPE_PRICE_ID:
        mapping[settings.STRIPE_PRICE_ID] = Tier.ADMIN
    if settings.STRIPE_PRICE_ID_PRO:
        mapping[settings.STRIPE_PRICE_ID_PRO] = Tier.PRO
    if settings.STRIPE_PRICE_ID_MAX:
        mapping[settings.STRIPE_PRICE_ID_MAX] = Tier.MAX
    if settings.STRIPE_TASKFORCE_PRO:
        mapping[settings.STRIPE_TASKFORCE_PRO] = Tier.PRO
    if settings.STRIPE_TASKFORCE_MAX:
        mapping[settings.STRIPE_TASKFORCE_MAX] = Tier.MAX
    return mapping


def _paid_tier(user: User) -> Tier:
    """Resolve a user's paid tier from Stripe state alone.

    A subscription is "live" only when its status is active/trialing AND
    its price_id maps to a known tier. Cancelled/past_due subscriptions
    fall back to Free immediately even if ``stripe_price_id`` is still
    populated — this matches how the existing billing helper interprets
    ``is_subscription_active``."""

    if user.stripe_subscription_status not in ACTIVE_SUBSCRIPTION_STATUSES:
        return Tier.FREE
    price_id = user.stripe_price_id
    if not price_id:
        return Tier.FREE
    return _price_id_to_tier().get(price_id, Tier.FREE)


def resolve_tier(user: User) -> Tier:
    """Resolve a user's effective tier.

    The paid (Stripe) tier and any complimentary ``comp_tier`` grant are
    combined by rank, and the higher of the two wins. The grant is thus a
    *floor*: it can raise a Free/Pro user to Max (the new-user promo) but
    never demotes someone whose Stripe subscription already outranks it.
    Every tier-aware gate composes against this function, so the floor
    applies everywhere uniformly."""

    paid = _paid_tier(user)
    comp = _coerce_tier(user.comp_tier)
    if comp is not None and _TIER_RANK[comp] > _TIER_RANK[paid]:
        return comp
    return paid


def public_tier(tier: Tier) -> PublicTier:
    if tier == Tier.PRO:
        return "pro"
    if tier in {Tier.MAX, Tier.ADMIN}:
        return "max"
    return "free"


def resolve_public_tier(user: User) -> PublicTier:
    return public_tier(resolve_tier(user))


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
      - Max  → always routes through our managed Claude credential.
      - Pro  → must supply BYOK (anthropic OR openai); we route through it.
      - Free → never allowed; UI shows the upsell card.

    BYOK *does not* override managed routing on Max — Max users opted
    into "we pay for the LLM," and we don't second-guess that choice
    here. If a Max user wants BYOK semantics, they downgrade to Pro."""

    tier = resolve_tier(user)

    if tier in {Tier.MAX, Tier.ADMIN}:
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
