"""Sessions labels from the opening user prompt.

The Sessions roster shows a stable conversation label — not the rolling last
prompt. We capture it once when the session first speaks and never overwrite
it unless the user renames the session explicitly, or the haiku summarizer
returns a tighter ``session_label`` after the first material observe.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.core.taskforce.summarizer import SESSION_LABEL_MAX_LEN, SummarizerResult

if TYPE_CHECKING:
    from app.models import TaskforceSessionArchive

_PREFIX_PATTERNS = (
    r"^hi[,!]?\s+",
    r"^hey[,!]?\s+",
    r"^hello[,!]?\s+",
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

_DIGEST_PREFIXES = ("Ran: ", "Touched ")
_WEAK_OPENING_LABELS = {"hi", "hey", "hello"}


def _normalize_label(text: str) -> str:
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return ""
    if len(cleaned) > SESSION_LABEL_MAX_LEN:
        cleaned = cleaned[:SESSION_LABEL_MAX_LEN].rstrip()
    return cleaned


def summarize_opening_prompt(prompt: str) -> str:
    """Turn the first user prompt into a short, stable session label."""

    text = " ".join(prompt.split()).strip()
    if not text:
        return ""

    lowered = text.lower()
    stripped = True
    while stripped:
        stripped = False
        for pattern in _PREFIX_PATTERNS:
            if re.match(pattern, lowered):
                text = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()
                lowered = text.lower()
                stripped = True
                break

    for separator in (". ", "? ", "! ", ", and ", "\n"):
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

    return _normalize_label(text)


def _is_digest_line(text: str) -> bool:
    stripped = text.strip()
    return not stripped or stripped.startswith(_DIGEST_PREFIXES)


def resolve_session_label(
    summary: SummarizerResult,
    *,
    prompt: str = "",
) -> str:
    """Pick the best short roster label from a summarizer result."""

    if summary.session_label:
        return summary.session_label

    for point in summary.summary_points:
        candidate = _normalize_label(point.strip())
        if candidate and not _is_digest_line(candidate):
            return candidate

    return summarize_opening_prompt(prompt)


def _looks_like_verbatim_prompt(label: str, prompt: str) -> bool:
    if not label or not prompt:
        return False
    normalized_label = " ".join(label.split()).lower()
    normalized_prompt = " ".join(prompt.split()).lower()
    if normalized_label == normalized_prompt[: len(normalized_label)]:
        return True
    if len(label) > 200:
        return True
    return bool(re.match(r"^(hi|hey|hello)[,!]?\s", normalized_label))


def is_weak_opening_label(label: str | None) -> bool:
    """Whether the stored label is just a greeting placeholder."""

    if not label:
        return False
    normalized = " ".join(label.split()).strip().lower().rstrip(".,!?:;")
    return normalized in _WEAK_OPENING_LABELS


def apply_conversation_summary_from_summary(
    archive: TaskforceSessionArchive,
    summary: SummarizerResult,
    *,
    prompt: str = "",
) -> None:
    """Refresh ``conversation_summary`` when the summarizer has a better label.

    User-renamed sessions (``display_name`` set) are left alone. Haiku
    ``session_label`` values replace heuristic first-pass labels; otherwise we
    only fill in when nothing was captured yet.
    """

    if archive.display_name:
        return

    label = resolve_session_label(summary, prompt=prompt)
    if not label:
        return

    if archive.conversation_summary is None:
        archive.conversation_summary = label
        return

    if is_weak_opening_label(archive.conversation_summary) and not is_weak_opening_label(
        label
    ):
        archive.conversation_summary = label
        return

    if summary.session_label:
        archive.conversation_summary = label
        return

    if _looks_like_verbatim_prompt(archive.conversation_summary, prompt):
        archive.conversation_summary = label
