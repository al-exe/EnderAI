"""Attributable savings calculators.

Three sources, each measured or estimated against the versioned pricing
snapshot the event was priced at. See docs/taskforce-metrics-engine-plan.md
§2.2. The functions are pure — they take what they need and return a
``(tokens_saved, usd_saved)`` tuple. Persisting events is the caller's job
(``app.core.metrics.events``).

Anything that can't be attributed cleanly is *not* counted here. That's a
product decision baked into the math.
"""

from __future__ import annotations

from decimal import Decimal

from app.models import ModelPricing, TaskforceUsagePayload, V2Document


def _to_decimal(value: int) -> Decimal:
    return Decimal(value)


def _per_mtok(tokens: Decimal, rate: Decimal | None) -> Decimal:
    """Multiply a token count by a $/MTok rate. ``None`` rate → $0."""

    if rate is None:
        return Decimal(0)
    return (tokens / Decimal(1_000_000)) * rate


# ---------- source 1: cache savings (measured) -----------------------------

# Per the Anthropic pricing page, cache reads cost ~10% of base input. The
# delta we save is therefore (base − cache_read) per cache-read token. If
# the pricing row didn't supply a cache_read rate (e.g. legacy models), we
# fall back to ``base_input_rate × 0.9`` so the saving is still defensible.
_FALLBACK_CACHE_READ_FRACTION = Decimal("0.10")


def cache_savings(
    usage: TaskforceUsagePayload,
    pricing: ModelPricing | None,
) -> tuple[int, Decimal]:
    """Tokens-and-USD saved by cache reads on this turn.

    Tokens saved = ``cache_read_input_tokens`` (every cache-read token is
    one we didn't have to pay base-input on). USD saved =
    ``cache_read_tokens × (base_input − cache_read)``.
    """

    cache_read = usage.cache_read_input_tokens
    if cache_read <= 0 or pricing is None:
        return 0, Decimal(0)

    base_rate = pricing.input_per_mtok
    cache_rate = (
        pricing.cache_read_per_mtok
        if pricing.cache_read_per_mtok is not None
        else base_rate * _FALLBACK_CACHE_READ_FRACTION
    )
    delta_per_mtok = base_rate - cache_rate
    if delta_per_mtok <= 0:
        return cache_read, Decimal(0)

    usd = _per_mtok(_to_decimal(cache_read), delta_per_mtok)
    return cache_read, usd


# ---------- source 2: summary-instead-of-details savings (measured) --------


def summary_only_savings(
    usage: TaskforceUsagePayload,
    document: V2Document,
    pricing: ModelPricing | None,
) -> tuple[int, Decimal]:
    """Tokens-and-USD saved by consulting Summary instead of full Details.

    Requires the agent to set ``view_consulted == "summary"`` on the usage
    payload. When it does, the saving = ``details_tokens`` (the Details
    payload the model would otherwise have had to read) priced at base
    input. Cache reads are excluded so this doesn't double-count §1.
    """

    if usage.view_consulted != "summary":
        return 0, Decimal(0)
    if document.details_tokens <= 0 or pricing is None:
        return 0, Decimal(0)

    tokens_saved = int(document.details_tokens)
    usd = _per_mtok(_to_decimal(tokens_saved), pricing.input_per_mtok)
    return tokens_saved, usd


# ---------- source 3: reuse-on-begin savings (estimated) -------------------

# Cap above which "from-scratch bootstrap" stops being a believable
# counterfactual. Plan §11 Open Question 2 settled on 20k tokens.
BOOTSTRAP_TOKENS_CAP = 20_000


def reuse_savings(
    document: V2Document,
    pricing: ModelPricing | None,
) -> tuple[int, Decimal]:
    """Estimated tokens-and-USD saved by reusing this document on begin.

    ``bootstrap_tokens = min(20k, summary_tokens + details_tokens)`` — the
    floor on what a from-scratch session would have to re-derive. Priced
    at base input.
    """

    if pricing is None:
        return 0, Decimal(0)

    total = max(0, int(document.summary_tokens) + int(document.details_tokens))
    bootstrap = min(BOOTSTRAP_TOKENS_CAP, total)
    if bootstrap <= 0:
        return 0, Decimal(0)

    usd = _per_mtok(_to_decimal(bootstrap), pricing.input_per_mtok)
    return bootstrap, usd
