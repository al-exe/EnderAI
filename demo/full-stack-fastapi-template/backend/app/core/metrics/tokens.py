"""Token-count helpers for Taskforce metrics.

The metrics engine needs cheap, deterministic token counts for V2 documents
so the reuse-on-begin savings source (plan §2.2) can estimate
``bootstrap_tokens`` per reused doc without re-tokenizing on every read.

Phase 2 intentionally does *not* pull in ``anthropic`` or ``tiktoken`` as
runtime deps — the heuristic below is good enough for relative comparisons
within the engine, and we'd rather defer the dep until a metric actually
needs precise model-specific counts (plan §11 Open Question 7).

If/when we adopt a real tokenizer, ``count_tokens`` is the only call site
to swap.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# ~4 characters per token is the canonical ballpark for English / code under
# the Claude tokenizers. The exact number drifts with each model release;
# the metric here is intentionally rounded so it doesn't promise precision
# we can't keep.
_CHARS_PER_TOKEN = 4


def count_tokens(text: str) -> int:
    """Return an estimated token count for ``text``.

    Deterministic: ``len(text) // _CHARS_PER_TOKEN``. Never returns a
    negative value. Empty / whitespace-only strings count as 0 tokens.
    """

    if not text:
        return 0
    return max(0, len(text) // _CHARS_PER_TOKEN)


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def count_paragraph_tokens(paragraphs: Iterable[Any]) -> int:
    """Sum estimated tokens across the V2Document ``main_body`` shape.

    Each paragraph is ``{"segments": [{"text": ..., ...}, ...]}``. Anchor
    ids and structural keys contribute nothing — only ``text`` payload.
    """

    total = 0
    for paragraph in paragraphs:
        segments = _field(paragraph, "segments") or []
        for segment in segments:
            value = _field(segment, "text")
            if isinstance(value, str):
                total += count_tokens(value)
    return total


def count_details_sections_tokens(sections: Iterable[Any]) -> int:
    """Sum estimated tokens across the V2Document ``details_markdown_sections``.

    Each section is ``{"anchor_id": ..., "markdown": ...}``. Only the
    markdown body contributes.
    """

    total = 0
    for section in sections:
        markdown = _field(section, "markdown")
        if isinstance(markdown, str):
            total += count_tokens(markdown)
    return total
