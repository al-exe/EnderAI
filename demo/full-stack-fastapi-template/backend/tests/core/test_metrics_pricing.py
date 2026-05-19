from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlmodel import Session, delete, select

from app.core.metrics import pricing_for
from app.models import ModelPricing


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fresh_pricing(db: Session) -> Generator[None, None, None]:
    """Remove any ``test-model-*`` rows before and after every test in this
    file so a failed test doesn't leak rows into a sibling. The seeded
    ``claude-*`` rows are intentionally left alone.
    """

    def _cleanup() -> None:
        db.execute(
            delete(ModelPricing).where(
                ModelPricing.model_id.like("test-model-%")  # type: ignore[union-attr]
            )
        )
        db.commit()

    _cleanup()
    yield
    _cleanup()


def _make_row(
    model_id: str,
    effective_from: datetime,
    effective_to: datetime | None = None,
    input_rate: str = "1.0000",
) -> ModelPricing:
    return ModelPricing(
        provider="test",
        model_id=model_id,
        effective_from=effective_from,
        effective_to=effective_to,
        input_per_mtok=Decimal(input_rate),
        output_per_mtok=Decimal("2.0000"),
    )


def test_pricing_for_returns_none_when_model_unknown(db: Session) -> None:
    assert pricing_for(db, "test-model-does-not-exist", _utc(2026, 6, 1)) is None


def test_pricing_for_returns_single_active_row(db: Session) -> None:
    row = _make_row("test-model-a", _utc(2026, 1, 1), input_rate="3.0000")
    db.add(row)
    db.commit()

    result = pricing_for(db, "test-model-a", _utc(2026, 6, 1))
    assert result is not None
    assert result.input_per_mtok == Decimal("3.0000")


def test_pricing_for_picks_latest_effective_from_when_multiple_rows_overlap(
    db: Session,
) -> None:
    older = _make_row("test-model-b", _utc(2026, 1, 1), input_rate="2.0000")
    newer = _make_row("test-model-b", _utc(2026, 4, 1), input_rate="5.0000")
    db.add(older)
    db.add(newer)
    db.commit()

    result = pricing_for(db, "test-model-b", _utc(2026, 6, 1))
    assert result is not None
    assert result.input_per_mtok == Decimal("5.0000")


def test_pricing_for_returns_older_row_when_query_predates_newer_row(
    db: Session,
) -> None:
    older = _make_row("test-model-c", _utc(2026, 1, 1), input_rate="2.0000")
    newer = _make_row("test-model-c", _utc(2026, 4, 1), input_rate="5.0000")
    db.add(older)
    db.add(newer)
    db.commit()

    # Event at 2026-03-15 happened before the new pricing took effect.
    result = pricing_for(db, "test-model-c", _utc(2026, 3, 15))
    assert result is not None
    assert result.input_per_mtok == Decimal("2.0000")


def test_pricing_for_honours_effective_to_window(db: Session) -> None:
    closed = _make_row(
        "test-model-d",
        effective_from=_utc(2026, 1, 1),
        effective_to=_utc(2026, 3, 1),
        input_rate="2.0000",
    )
    db.add(closed)
    db.commit()

    inside_window = pricing_for(db, "test-model-d", _utc(2026, 2, 1))
    assert inside_window is not None
    assert inside_window.input_per_mtok == Decimal("2.0000")

    # Exactly at effective_to → window is half-open [from, to), so this is
    # outside the window.
    on_boundary = pricing_for(db, "test-model-d", _utc(2026, 3, 1))
    assert on_boundary is None

    after_window = pricing_for(
        db, "test-model-d", _utc(2026, 3, 1) + timedelta(seconds=1)
    )
    assert after_window is None


def test_pricing_for_skips_rows_whose_effective_from_is_in_the_future(
    db: Session,
) -> None:
    future = _make_row("test-model-e", _utc(2027, 1, 1), input_rate="9.0000")
    db.add(future)
    db.commit()

    result = pricing_for(db, "test-model-e", _utc(2026, 6, 1))
    assert result is None


def test_seed_migration_loaded_anthropic_catalog(db: Session) -> None:
    """Smoke test: the May 2026 Anthropic seed rows exist with the expected
    base rates. Catches accidental schema/seed regressions."""

    opus = pricing_for(db, "claude-opus-4-7", _utc(2026, 6, 1))
    assert opus is not None
    assert opus.provider == "anthropic"
    assert opus.input_per_mtok == Decimal("5.0000")
    assert opus.output_per_mtok == Decimal("25.0000")
    assert opus.cache_read_per_mtok == Decimal("0.5000")
    assert opus.batch_discount == Decimal("0.500")

    sonnet = pricing_for(db, "claude-sonnet-4-6", _utc(2026, 6, 1))
    assert sonnet is not None
    assert sonnet.input_per_mtok == Decimal("3.0000")
    assert sonnet.output_per_mtok == Decimal("15.0000")

    haiku = pricing_for(db, "claude-haiku-4-5", _utc(2026, 6, 1))
    assert haiku is not None
    assert haiku.input_per_mtok == Decimal("1.0000")
    assert haiku.output_per_mtok == Decimal("5.0000")


def test_seed_migration_did_not_load_non_anthropic_pricing(db: Session) -> None:
    """Plan §11 Open Question 3: ship Claude-only in Phase 1."""

    non_anthropic = db.exec(
        select(ModelPricing).where(ModelPricing.provider != "anthropic")
    ).all()
    assert non_anthropic == []
