from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlmodel import Session

from app.core.metrics import cache_savings, reuse_savings, summary_only_savings
from app.core.metrics.pricing import pricing_for
from app.models import TaskforceUsagePayload, V2Document


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


@pytest.fixture
def opus_pricing(db: Session):  # type: ignore[no-untyped-def]
    pricing = pricing_for(db, "claude-opus-4-7", _utc(2026, 6, 1))
    assert pricing is not None
    return pricing


def _doc(*, summary: int = 0, details: int = 0) -> V2Document:
    return V2Document(
        owner_id=None,  # type: ignore[arg-type]
        title="t",
        summary_tokens=summary,
        details_tokens=details,
    )


def test_cache_savings_zero_when_no_cache_reads(opus_pricing) -> None:  # type: ignore[no-untyped-def]
    usage = TaskforceUsagePayload(model_id="claude-opus-4-7")
    tokens, usd = cache_savings(usage, opus_pricing)
    assert (tokens, usd) == (0, Decimal(0))


def test_cache_savings_priced_at_base_minus_cache_read(opus_pricing) -> None:  # type: ignore[no-untyped-def]
    usage = TaskforceUsagePayload(
        model_id="claude-opus-4-7", cache_read_input_tokens=1_000_000
    )
    tokens, usd = cache_savings(usage, opus_pricing)
    # Opus 4.7: base 5.00, cache_read 0.50 → delta 4.50 per MTok.
    assert tokens == 1_000_000
    assert usd == Decimal("4.5")


def test_cache_savings_returns_zero_usd_when_pricing_missing() -> None:
    usage = TaskforceUsagePayload(
        model_id="claude-opus-4-7", cache_read_input_tokens=500
    )
    tokens, usd = cache_savings(usage, None)
    assert (tokens, usd) == (0, Decimal(0))


def test_summary_only_savings_requires_view_consulted_flag(opus_pricing) -> None:  # type: ignore[no-untyped-def]
    usage = TaskforceUsagePayload(model_id="claude-opus-4-7")
    document = _doc(details=10_000)
    assert summary_only_savings(usage, document, opus_pricing) == (0, Decimal(0))


def test_summary_only_savings_priced_at_base_input(opus_pricing) -> None:  # type: ignore[no-untyped-def]
    usage = TaskforceUsagePayload(model_id="claude-opus-4-7", view_consulted="summary")
    document = _doc(details=2_000_000)
    tokens, usd = summary_only_savings(usage, document, opus_pricing)
    # 2M tokens × $5/MTok base input = $10.
    assert tokens == 2_000_000
    assert usd == Decimal("10")


def test_summary_only_savings_zero_when_details_empty(opus_pricing) -> None:  # type: ignore[no-untyped-def]
    usage = TaskforceUsagePayload(model_id="claude-opus-4-7", view_consulted="summary")
    document = _doc(details=0)
    assert summary_only_savings(usage, document, opus_pricing) == (0, Decimal(0))


def test_reuse_savings_capped_at_bootstrap_cap(opus_pricing) -> None:  # type: ignore[no-untyped-def]
    # 30k + 50k = 80k → capped to 20k.
    document = _doc(summary=30_000, details=50_000)
    tokens, usd = reuse_savings(document, opus_pricing)
    assert tokens == 20_000
    # 20k × $5/MTok = $0.10.
    assert usd == Decimal("0.10")


def test_reuse_savings_uses_total_when_under_cap(opus_pricing) -> None:  # type: ignore[no-untyped-def]
    document = _doc(summary=3_000, details=2_000)
    tokens, usd = reuse_savings(document, opus_pricing)
    assert tokens == 5_000
    # 5k × $5/MTok = $0.025.
    assert usd == Decimal("0.025")


def test_reuse_savings_zero_when_doc_has_no_content(opus_pricing) -> None:  # type: ignore[no-untyped-def]
    document = _doc(summary=0, details=0)
    assert reuse_savings(document, opus_pricing) == (0, Decimal(0))


def test_reuse_savings_no_pricing_returns_zero() -> None:
    document = _doc(summary=10_000, details=10_000)
    assert reuse_savings(document, None) == (0, Decimal(0))
