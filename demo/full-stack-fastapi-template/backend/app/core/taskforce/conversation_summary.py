"""One-line Sessions labels from the opening user prompt.

The Sessions roster shows a stable conversation label — not the rolling last
prompt. We capture it once when the session first speaks and never overwrite
it unless the user renames the session explicitly.
"""

from __future__ import annotations

import re

_MAX_LEN = 120

_PREFIX_PATTERNS = (
    r"^please\s+",
    r"^can you\s+",
    r"^could you\s+",
    r"^would you\s+",
    r"^i need you to\s+",
    r"^i want you to\s+",
    r"^help me\s+",
    r"^let's\s+",
    r"^lets\s+",
)

_IMPERATIVE_GERUNDS: dict[str, str] = {
    "add": "Adding",
    "build": "Building",
    "debug": "Debugging",
    "fix": "Fixing",
    "implement": "Implementing",
    "investigate": "Investigating",
    "refactor": "Refactoring",
    "update": "Updating",
    "wire": "Wiring",
    "wrap": "Wrapping",
    "write": "Writing",
}


def summarize_opening_prompt(prompt: str) -> str:
    """Turn the first user prompt into a short, stable session label."""

    text = " ".join(prompt.split()).strip()
    if not text:
        return ""

    lowered = text.lower()
    for pattern in _PREFIX_PATTERNS:
        if re.match(pattern, lowered):
            text = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()
            lowered = text.lower()
            break

    for separator in (". ", "? ", "! ", "\n"):
        if separator in text:
            text = text.split(separator, 1)[0].strip()
            break

    words = text.split()
    if words:
        first = words[0].lower().rstrip(".,!?")
        gerund = _IMPERATIVE_GERUNDS.get(first)
        if gerund:
            rest = " ".join(words[1:])
            text = f"{gerund} {rest}".strip() if rest else gerund

    if text:
        text = text[0].upper() + text[1:]

    text = text.rstrip(".,!?")
    if len(text) > _MAX_LEN:
        text = f"{text[: _MAX_LEN - 1].rstrip()}…"
    return text
