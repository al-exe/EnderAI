"""Haiku-driven session summarizer for the observe endpoint (TF-178).

Reads a redacted transcript, calls claude-haiku-4-5 with a fixed canonical
prompt, parses the structured JSON response, and returns it. The caller
(observe.py) decides whether to PATCH the active document with the delta.

This module is the only place we talk to the Anthropic SDK. The import is
lazy so the backend boot path doesn't load anthropic just to serve other
routes — same pattern as ``app.core.search.answer``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from app.core.taskforce.redaction import redact
from app.models import TaskforceTranscriptTurn

logger = logging.getLogger(__name__)

SUMMARIZER_MODEL = "claude-haiku-4-5"
PROMPT_VERSION = "2026-06-24.1"
SESSION_LABEL_MAX_LEN = 255

# Pricing snapshot we charge against the user when ``record_usage`` lands a
# ``tokens.consumed.taskforce_summarizer`` event. Falls back to a known-good
# price when ``model_pricing`` doesn't yet have a haiku row.
_HAIKU_INPUT_PER_MTOK = Decimal("0.80")
_HAIKU_OUTPUT_PER_MTOK = Decimal("4.00")

# Caller-supplied transcripts get truncated to keep the haiku call cheap.
MAX_TRANSCRIPT_CHARS = 60_000  # ~15k tokens of input — well inside haiku's window
MAX_OUTPUT_TOKENS = 1_200


@dataclass
class SummarizerResult:
    materiality_score: float
    summary_points: list[str]
    details_sections: list[dict[str, str]]
    files_touched: list[str]
    commands_of_interest: list[str]
    decisions: list[str]
    outcome: str | None
    open_questions: list[str]
    session_label: str | None = None
    raw_text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    usd_cost: Decimal = field(default_factory=lambda: Decimal(0))
    prompt_version: str = PROMPT_VERSION


def _load_prompt() -> str:
    path = Path(__file__).with_name("summarizer_prompt.md")
    return path.read_text(encoding="utf-8")


def _render_transcript(transcript: Sequence[TaskforceTranscriptTurn]) -> str:
    """Flatten the transcript into the format the prompt expects.

    Returns a single string with one redacted turn per line. Truncates
    from the head (oldest first) when the corpus would exceed the budget
    so the freshest context — the part most likely to encode the actual
    delta — survives.
    """

    lines: list[str] = []
    for turn in transcript:
        cleaned = redact((turn.content or "").strip())
        if not cleaned:
            continue
        lines.append(f"[{turn.role}] {cleaned}")

    joined = "\n".join(lines)
    if len(joined) <= MAX_TRANSCRIPT_CHARS:
        return joined
    # Trim from the head; keep the tail.
    excess = len(joined) - MAX_TRANSCRIPT_CHARS
    return "(transcript truncated)\n" + joined[excess:]


def _normalize_session_label(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    label = " ".join(value.split()).strip()
    if not label:
        return None
    if len(label) > SESSION_LABEL_MAX_LEN:
        label = label[:SESSION_LABEL_MAX_LEN].rstrip()
    return label


def _empty_result() -> SummarizerResult:
    return SummarizerResult(
        materiality_score=0.0,
        summary_points=[],
        details_sections=[],
        files_touched=[],
        commands_of_interest=[],
        decisions=[],
        outcome=None,
        open_questions=[],
        session_label=None,
    )


async def summarize(
    *,
    transcript: Sequence[TaskforceTranscriptTurn],
    prompt: str,
    api_key: str,
    model_id: str = SUMMARIZER_MODEL,
) -> SummarizerResult:
    """Call haiku, parse the JSON output. Returns a usable result on any
    failure (degraded — empty arrays + logged warning) so the route handler
    can keep going without crashing.

    ``api_key`` is the managed Anthropic key (the same one search uses).
    """

    if not transcript:
        return _empty_result()

    from anthropic import AsyncAnthropic  # lazy

    rendered = _render_transcript(transcript)
    system_prompt = _load_prompt()
    user_message = (
        f"User prompt that started this session:\n{prompt.strip() or '(none provided)'}"
        f"\n\nRedacted transcript:\n{rendered or '(empty)'}"
    )

    client = AsyncAnthropic(api_key=api_key)
    try:
        response = await client.messages.create(
            model=model_id,
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception:  # noqa: BLE001 — never propagate from the summarizer
        logger.exception("taskforce.summarizer.exception")
        return _empty_result()

    text = "".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    ).strip()
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    usd_cost = _price(input_tokens, output_tokens)

    parsed = _parse_json_output(text)
    if parsed is None:
        result = _empty_result()
    else:
        result = SummarizerResult(
            materiality_score=float(parsed.get("materiality_score") or 0.0),
            summary_points=list(parsed.get("summary_points") or [])[:6],
            details_sections=_normalize_sections(parsed.get("details_sections")),
            files_touched=list(parsed.get("files_touched") or []),
            commands_of_interest=list(parsed.get("commands_of_interest") or [])[:8],
            decisions=list(parsed.get("decisions") or [])[:4],
            outcome=parsed.get("outcome"),
            open_questions=list(parsed.get("open_questions") or [])[:4],
            session_label=_normalize_session_label(parsed.get("session_label")),
        )
    result.raw_text = text
    result.input_tokens = int(input_tokens)
    result.output_tokens = int(output_tokens)
    result.usd_cost = usd_cost
    return result


def _parse_json_output(text: str) -> dict[str, Any] | None:
    """Tolerate fenced JSON; reject anything that doesn't parse."""

    if not text:
        return None
    payload = text
    if "```" in payload:
        # Pull the largest fenced block.
        fences = [
            block.strip()
            for block in payload.split("```")
            if block.strip().startswith("{") and block.strip().endswith("}")
        ]
        if fences:
            payload = fences[0]
        else:
            # Sometimes models prefix the block with ```json\n…
            payload = payload.replace("```json", "```").split("```")[1].strip()
    try:
        return json.loads(payload)
    except Exception:  # noqa: BLE001
        logger.warning("taskforce.summarizer.parse_failed", extra={"output": text[:500]})
        return None


def _normalize_sections(value: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(value, list):
        return out
    for entry in value[:4]:
        if not isinstance(entry, dict):
            continue
        anchor = str(entry.get("anchor_id") or "").strip()
        markdown = str(entry.get("markdown") or "").strip()
        if not anchor or not markdown:
            continue
        out.append({"anchor_id": anchor, "markdown": markdown[:800]})
    return out


def _price(input_tokens: int, output_tokens: int) -> Decimal:
    return (
        (Decimal(max(input_tokens, 0)) / Decimal(1_000_000)) * _HAIKU_INPUT_PER_MTOK
        + (Decimal(max(output_tokens, 0)) / Decimal(1_000_000)) * _HAIKU_OUTPUT_PER_MTOK
    )
