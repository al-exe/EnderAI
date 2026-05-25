"""Structural rediscovery-cost estimator (TF-177).

The Phase 3 savings model says: every document carries a cached estimate
of "how many tokens would it take an agent to redo this investigation
from scratch", and consultation savings = ``max(0, rediscovery_cost - summary_tokens_read)``.

This module computes the estimate from the doc's existing structure. The
formula is the §5.2 v1 from ``~/dev/docs/claude-mcp-brainstorm.md``:

    1500 * commands
  + 2500 * files inspected
  +  500 * decisions
  + 3000 * details sections
  + 1000 * summary points

Capped at 50,000 tokens per doc to keep gameability bounded.

V2Document doesn't carry explicit ``commands``/``files``/``decisions``
arrays — the MCP update handler folds those into details sections — so
we infer counts from regex patterns over the details markdown. This is
deliberately approximate; we'll re-tune coefficients quarterly from real
consult-vs-redo data.
"""

from __future__ import annotations

import re
from typing import Iterable

from app.models import V2Document, V2DocumentDetailsSection, V2DocumentParagraph

REDISCOVERY_COST_CAP = 50_000

# Coefficients per structural artifact. Round numbers on purpose — we'll
# regress them against measured "how much would it cost to redo this?"
# labels once consult data is flowing.
COEFFICIENTS = {
    "commands": 1_500,
    "files": 2_500,
    "decisions": 500,
    "details_sections": 3_000,
    "summary_points": 1_000,
}

# Heuristic patterns over details markdown. They're intentionally permissive
# so an evolving doc shape still produces a defensible estimate; precision
# matters less than not zeroing out for any non-trivial doc.

# Lines beginning with `$`/`>` (with optional indent) → command invocations.
_COMMAND_LINE = re.compile(r"(?m)^\s*[\$>]\s+\S")
# Fenced code blocks (```bash ... ``` or ```$ ... ```) count as commands too.
_FENCED_BLOCK = re.compile(r"```[^\n]*\n", flags=re.MULTILINE)
# Inline file references like `src/foo/bar.py` or `tests/api/test_x.py`.
_INLINE_FILE = re.compile(r"`([\w./\-]+\.[A-Za-z0-9]{1,6})`")
# Plain file paths that aren't inlined but include an extension and a slash.
_PATH_REFERENCE = re.compile(r"(?<![\w/])([\w\-]+/[\w\-/]+\.[A-Za-z0-9]{1,6})")
# Decision markers — case-insensitive verbs commonly used in investigation logs.
_DECISION_MARKER = re.compile(
    r"(?im)^\s*(?:[-*]\s+)?(?:decided?|chose|picked|opted|going with|sticking with|ruled out)\b"
)


def _iter_paragraph_text(paragraphs: Iterable[V2DocumentParagraph]) -> Iterable[str]:
    for paragraph in paragraphs or []:
        segments = (
            paragraph.get("segments")
            if isinstance(paragraph, dict)
            else getattr(paragraph, "segments", [])
        )
        for segment in segments or []:
            text = (
                segment.get("text")
                if isinstance(segment, dict)
                else getattr(segment, "text", "")
            )
            if text:
                yield text


def _iter_section_markdown(
    sections: Iterable[V2DocumentDetailsSection],
) -> Iterable[str]:
    for section in sections or []:
        markdown = (
            section.get("markdown")
            if isinstance(section, dict)
            else getattr(section, "markdown", "")
        )
        if markdown:
            yield markdown


def _count_commands(details_text: str) -> int:
    return len(_COMMAND_LINE.findall(details_text)) + len(
        _FENCED_BLOCK.findall(details_text)
    )


def _count_files(details_text: str, main_body_text: str) -> int:
    """Distinct file references across the doc body."""

    files: set[str] = set()
    for haystack in (details_text, main_body_text):
        if not haystack:
            continue
        files.update(_INLINE_FILE.findall(haystack))
        files.update(_PATH_REFERENCE.findall(haystack))
    return len(files)


def _count_decisions(details_text: str) -> int:
    return len(_DECISION_MARKER.findall(details_text))


def compute_rediscovery_cost(document: V2Document) -> int:
    """Return the cached ``rediscovery_cost_tokens`` value for a document.

    Pure: only reads ``main_body`` and ``details_markdown_sections``. Safe
    to call from a migration as well as the live update path.
    """

    main_body_text = "\n".join(_iter_paragraph_text(document.main_body or []))
    details_text = "\n".join(_iter_section_markdown(document.details_markdown_sections or []))

    summary_points = len(document.main_body or [])
    details_sections = len(document.details_markdown_sections or [])

    commands = _count_commands(details_text)
    files = _count_files(details_text, main_body_text)
    decisions = _count_decisions(details_text)

    cost = (
        COEFFICIENTS["commands"] * commands
        + COEFFICIENTS["files"] * files
        + COEFFICIENTS["decisions"] * decisions
        + COEFFICIENTS["details_sections"] * details_sections
        + COEFFICIENTS["summary_points"] * summary_points
    )
    return min(cost, REDISCOVERY_COST_CAP)
