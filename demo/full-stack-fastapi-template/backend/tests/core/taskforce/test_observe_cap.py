"""TF-265: env-configurable per-user daily USD cap on the paid summarizer.

Covers the `_daily_usd_cap()` helper (setting read + fallbacks) and that the
`_resolve_summary` gate actually honors it — over-cap must fall back to the free
deterministic digest and never invoke the paid haiku summarizer.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from app.core.config import settings
from app.core.taskforce import observe
from app.core.taskforce.summarizer import SummarizerResult
from app.models import TaskforceObserveRequest, TaskforceTranscriptTurn


def _request(**overrides) -> TaskforceObserveRequest:
    base = {
        "kind": "final",
        "prompt": "do a material thing",
        "transcript": [
            TaskforceTranscriptTurn(role="assistant", content=f"turn {i}")
            for i in range(3)
        ],
        "active_document_id": None,
        "files_touched": [],
        "commands_run": [],
        "duration_ms": 0,
        "harness": None,
    }
    base.update(overrides)
    return TaskforceObserveRequest(**base)  # type: ignore[arg-type]


# ---- helper -----------------------------------------------------------------


def test_daily_usd_cap_reads_setting(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TASKFORCE_OBSERVE_DAILY_USD_CAP", 0.25)
    assert observe._daily_usd_cap() == Decimal("0.25")


def test_daily_usd_cap_default_matches_legacy_constant(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TASKFORCE_OBSERVE_DAILY_USD_CAP", 1.00)
    assert observe._daily_usd_cap() == observe.DEFAULT_DAILY_USD_CAP == Decimal("1.00")


def test_daily_usd_cap_falls_back_on_negative(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TASKFORCE_OBSERVE_DAILY_USD_CAP", -5.0)
    assert observe._daily_usd_cap() == observe.DEFAULT_DAILY_USD_CAP


# ---- gate behavior ----------------------------------------------------------


def test_over_cap_skips_paid_summarizer(monkeypatch) -> None:
    # Paid enabled + managed key present, but today's spend already at the cap
    # → the gate must fall back to the free deterministic digest and never call
    # the haiku summarizer.
    monkeypatch.setenv("TASKFORCE_OBSERVE_SHADOW", "0")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(settings, "TASKFORCE_OBSERVE_DAILY_USD_CAP", 0.25)
    monkeypatch.setattr(
        observe, "_summarizer_cost_today", lambda session, *, actor: Decimal("0.25")
    )

    def _boom(*_args, **_kwargs):
        raise AssertionError("summarizer must not run once the daily cap is reached")

    monkeypatch.setattr(observe, "summarize", _boom)

    summary, used_paid = asyncio.run(
        observe._resolve_summary(
            None, actor=None, request=_request(), structured=False
        )
    )
    assert used_paid is False
    assert summary.usd_cost == Decimal(0)


def test_under_cap_runs_paid_summarizer(monkeypatch) -> None:
    monkeypatch.setenv("TASKFORCE_OBSERVE_SHADOW", "0")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(settings, "TASKFORCE_OBSERVE_DAILY_USD_CAP", 1.00)
    monkeypatch.setattr(
        observe, "_summarizer_cost_today", lambda session, *, actor: Decimal("0.10")
    )

    called: dict[str, bool] = {}

    async def _fake_summarize(*, transcript, prompt, api_key):  # noqa: ARG001
        called["ran"] = True
        return SummarizerResult(
            materiality_score=1.0,
            summary_points=["a point"],
            details_sections=[],
            files_touched=[],
            commands_of_interest=[],
            decisions=[],
            outcome=None,
            open_questions=[],
            raw_text="x",
            input_tokens=10,
            output_tokens=5,
            usd_cost=Decimal("0.01"),
            prompt_version=observe.PROMPT_VERSION,
        )

    monkeypatch.setattr(observe, "summarize", _fake_summarize)

    summary, used_paid = asyncio.run(
        observe._resolve_summary(
            None, actor=None, request=_request(), structured=False
        )
    )
    assert used_paid is True
    assert called.get("ran") is True
    assert summary.usd_cost == Decimal("0.01")
