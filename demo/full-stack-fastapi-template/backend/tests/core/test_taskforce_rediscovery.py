"""Unit tests for the rediscovery-cost formula (TF-177).

The formula is structural (counts commands, files, decisions, details
sections, summary points). These tests pin the coefficients so any
future tuning is intentional + visible in code review.
"""

from __future__ import annotations

import uuid

from app.core.taskforce.rediscovery import (
    COEFFICIENTS,
    REDISCOVERY_COST_CAP,
    compute_rediscovery_cost,
)
from app.models import V2Document


def _doc(
    *,
    main_body: list | None = None,
    details_markdown_sections: list | None = None,
) -> V2Document:
    return V2Document(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        title="t",
        description="",
        human_summary="",
        ai_generated_summary="",
        main_body=main_body or [],
        details_file_name="",
        details_markdown_sections=details_markdown_sections or [],
    )


def test_empty_doc_costs_zero() -> None:
    assert compute_rediscovery_cost(_doc()) == 0


def test_summary_points_contribute() -> None:
    doc = _doc(
        main_body=[
            {"segments": [{"text": "first point"}]},
            {"segments": [{"text": "second point"}]},
        ]
    )
    assert compute_rediscovery_cost(doc) == 2 * COEFFICIENTS["summary_points"]


def test_details_sections_contribute() -> None:
    doc = _doc(
        details_markdown_sections=[
            {"anchor_id": "a", "markdown": "background prose without artifacts"},
            {"anchor_id": "b", "markdown": "more prose"},
        ]
    )
    expected = 2 * COEFFICIENTS["details_sections"]
    assert compute_rediscovery_cost(doc) == expected


def test_commands_in_details_contribute() -> None:
    md = (
        "# Notes\n"
        "$ ls -la\n"
        "$ grep foo bar\n"
        "> some other invocation\n"
    )
    doc = _doc(
        details_markdown_sections=[{"anchor_id": "investigation", "markdown": md}],
    )
    # 3 command lines + 1 section + 0 file mentions
    expected = (
        3 * COEFFICIENTS["commands"]
        + 1 * COEFFICIENTS["details_sections"]
    )
    assert compute_rediscovery_cost(doc) == expected


def test_fenced_code_blocks_count_as_commands() -> None:
    md = (
        "Some prose.\n"
        "```bash\nls -la\n```\n"
        "More prose.\n"
        "```python\nprint('hi')\n```\n"
    )
    doc = _doc(
        details_markdown_sections=[{"anchor_id": "investigation", "markdown": md}],
    )
    expected = (
        2 * COEFFICIENTS["commands"]
        + 1 * COEFFICIENTS["details_sections"]
    )
    assert compute_rediscovery_cost(doc) == expected


def test_file_references_contribute_dedupe() -> None:
    md = (
        "Touched `src/foo.py` and `tests/api/test_x.py`.\n"
        "Also touched src/foo.py again (dup, should dedupe).\n"
    )
    doc = _doc(
        details_markdown_sections=[{"anchor_id": "files", "markdown": md}],
    )
    # 2 distinct files + 1 section, no commands.
    expected = (
        2 * COEFFICIENTS["files"]
        + 1 * COEFFICIENTS["details_sections"]
    )
    assert compute_rediscovery_cost(doc) == expected


def test_decision_markers_contribute() -> None:
    md = (
        "- Decided to ship the formula as-is\n"
        "- Picked option B over option A\n"
        "- Going with regex-based extraction\n"
    )
    doc = _doc(
        details_markdown_sections=[{"anchor_id": "decisions", "markdown": md}],
    )
    expected = (
        3 * COEFFICIENTS["decisions"]
        + 1 * COEFFICIENTS["details_sections"]
    )
    assert compute_rediscovery_cost(doc) == expected


def test_cap_at_50k_tokens() -> None:
    # 50 sections × 3000 = 150,000 well above the cap.
    doc = _doc(
        details_markdown_sections=[
            {"anchor_id": f"s{i}", "markdown": "x"} for i in range(50)
        ],
    )
    assert compute_rediscovery_cost(doc) == REDISCOVERY_COST_CAP


def test_realistic_doc_produces_plausible_estimate() -> None:
    md = (
        "## Findings\n"
        "Ran `git status` then\n"
        "$ rg --files-with-matches token src/\n"
        "Inspected `src/core/metrics.py` and `tests/test_metrics.py`.\n"
        "Decided to add a new event kind rather than overload existing.\n"
    )
    doc = _doc(
        main_body=[
            {"segments": [{"text": "we added a new event kind"}]},
            {"segments": [{"text": "metric registry updated"}]},
        ],
        details_markdown_sections=[
            {"anchor_id": "investigation", "markdown": md},
            {"anchor_id": "outcome", "markdown": "Shipped in PR #X."},
        ],
    )
    cost = compute_rediscovery_cost(doc)
    # Sanity: well above 0, well below cap.
    assert 5_000 < cost < REDISCOVERY_COST_CAP
