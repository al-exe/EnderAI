"""Normalize Cursor hook / transcript user text for Sessions activity."""

from __future__ import annotations

import re

_USER_QUERY_RE = re.compile(
    r"^<user_query>\s*|\s*</user_query>\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_FLEET_UI_MARKERS = (
    "View in Ledger",
    "Awaiting user prompt",
    "Running in this terminal",
    "Activity capture is paused",
)
_ACTIVITY_LINE_RE = re.compile(
    r"^(?:\d{1,2}:\d{2}\s*(?:AM|PM))?(?:prompt|command|reply)?$",
    re.IGNORECASE,
)


def clean_cursor_user_prompt(text: str) -> str:
    """Strip Cursor wrappers and Sessions UI paste noise from a user prompt."""

    cleaned = _USER_QUERY_RE.sub("", text or "").strip()
    if not cleaned:
        return ""

    if not any(marker in cleaned for marker in _FLEET_UI_MARKERS):
        return cleaned

    blocks = [block.strip() for block in re.split(r"\n\s*\n", cleaned) if block.strip()]
    if blocks:
        tail = blocks[-1]
        if (
            tail
            and len(tail) <= 400
            and not any(marker in tail for marker in _FLEET_UI_MARKERS)
            and not _looks_like_activity_scrape(tail)
        ):
            return tail

    for line in reversed(cleaned.splitlines()):
        candidate = line.strip()
        if not candidate or any(marker in candidate for marker in _FLEET_UI_MARKERS):
            continue
        if _looks_like_activity_scrape(candidate):
            continue
        return candidate

    return cleaned


def _looks_like_activity_scrape(line: str) -> bool:
    lowered = line.lower()
    if _ACTIVITY_LINE_RE.match(line):
        return True
    if lowered.endswith("prompt") and len(line) <= 24:
        return True
    if lowered.startswith("$ ") or lowered.startswith("pmcommand"):
        return True
    return False
