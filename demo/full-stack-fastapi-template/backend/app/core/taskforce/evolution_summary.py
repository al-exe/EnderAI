"""Shared summary snapshot types for offline evolution (T1/T2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

EVOLUTION_SUMMARY_KEY = "evolution_summary"


@dataclass(frozen=True)
class StoredEvolutionSummary:
    summary_points: list[str]
    details_sections: list[dict[str, str]]
    decisions: list[str]
    outcome: str | None
    materiality_score: float


def stored_summary_from_metadata(
    metadata: dict[str, Any] | None,
) -> StoredEvolutionSummary | None:
    raw = (metadata or {}).get(EVOLUTION_SUMMARY_KEY)
    if not isinstance(raw, dict):
        return None
    return StoredEvolutionSummary(
        summary_points=[
            str(point).strip()
            for point in raw.get("summary_points") or []
            if str(point).strip()
        ],
        details_sections=[
            section
            for section in raw.get("details_sections") or []
            if isinstance(section, dict)
        ],
        decisions=[
            str(item).strip()
            for item in raw.get("decisions") or []
            if str(item).strip()
        ],
        outcome=str(raw["outcome"]).strip() if raw.get("outcome") else None,
        materiality_score=float(raw.get("materiality_score") or 1.0),
    )


def summary_has_content(summary: StoredEvolutionSummary) -> bool:
    return bool(
        summary.summary_points
        or summary.details_sections
        or summary.decisions
        or summary.outcome
    )
