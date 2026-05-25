"""Best-effort secrets redaction for ingested transcripts (TF-178 / §4.6).

This is intentionally a deny-list — we catch the 90% case (env vars,
auth headers, JWTs, common provider key formats) and document the
residual leak surface in CLAUDE.md. We never claim to redact everything.

Each pattern replaces the matched secret with ``[REDACTED]``. Replacement
preserves structural context (the env-var name, the header key) so the
summarizer can still reason about *what* was redacted without leaking
*which* secret.
"""

from __future__ import annotations

import re
from typing import Iterable

# Match common secret-bearing patterns. Each entry is (pattern, replacement_fmt).
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # `KEY=value` style env-var-ish assignment when KEY mentions secret keywords.
    (
        re.compile(
            r"(?i)\b((?:api[_-]?key|password|secret|token|access[_-]?key|client[_-]?secret|bearer))\s*[:=]\s*([^\s,;\"']+)"
        ),
        r"\1=[REDACTED]",
    ),
    # `Authorization: Bearer …` headers (case-insensitive).
    (
        re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+"),
        r"\1[REDACTED]",
    ),
    # `Authorization: …` headers without a Bearer prefix.
    (
        re.compile(r"(?i)(authorization\s*[:=]\s*)[^\s,;\"']+"),
        r"\1[REDACTED]",
    ),
    # JWTs (three dot-separated base64url segments).
    (
        re.compile(r"\beyJ[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b"),
        "[REDACTED-JWT]",
    ),
    # Anthropic-style `sk-ant-…` keys — listed before the OpenAI one so the
    # `sk-ant-` prefix wins ordering.
    (
        re.compile(r"\bsk-ant-[a-zA-Z0-9_\-]{20,}\b"),
        "[REDACTED-ANTHROPIC-KEY]",
    ),
    # OpenAI-style `sk-…` API keys (excludes the `sk-ant-` prefix).
    (
        re.compile(r"\bsk-(?!ant-)[a-zA-Z0-9_\-]{20,}\b"),
        "[REDACTED-OPENAI-KEY]",
    ),
    # Slack tokens `xox[a-z]-…`.
    (
        re.compile(r"\bxox[a-z]-[a-zA-Z0-9-]{10,}\b"),
        "[REDACTED-SLACK-TOKEN]",
    ),
    # GitHub PATs `ghp_…` and friends.
    (
        re.compile(r"\bgh[pousr]_[a-zA-Z0-9]{30,}\b"),
        "[REDACTED-GITHUB-TOKEN]",
    ),
    # AWS-style access key ids.
    (
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "[REDACTED-AWS-KEY]",
    ),
)


def redact(text: str) -> str:
    """Apply all patterns. Idempotent; safe to call multiple times."""

    if not text:
        return text
    redacted = text
    for pattern, replacement in _PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_lines(lines: Iterable[str]) -> list[str]:
    return [redact(line) for line in lines]
