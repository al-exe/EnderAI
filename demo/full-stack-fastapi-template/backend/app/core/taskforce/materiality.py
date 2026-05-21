"""Deterministic materiality check (TF-178 / §4.3).

Runs before the summarizer is invoked. Cheap; pure. If a session has no
material activity we skip the LLM call entirely — that's the cost
short-circuit that keeps the per-user daily cost bounded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.models import (
    TaskforceCommandRun,
    TaskforceObserveRequest,
    TaskforceTranscriptTurn,
)


@dataclass(frozen=True)
class MaterialityDecision:
    material: bool
    reason: str


def assess_materiality(request: TaskforceObserveRequest) -> MaterialityDecision:
    """Return whether the session is worth summarizing.

    A session is material if **any** of:
      * ≥ 3 assistant/tool turns in the transcript
      * ≥ 1 file modified
      * ≥ 2 distinct shell commands
      * the agent explicitly pinned a document via ``active_document_id``
    """

    if request.active_document_id is not None:
        return MaterialityDecision(
            material=True, reason="agent pinned an active document"
        )

    tool_turns = _count_assistant_turns(request.transcript)
    if tool_turns >= 3:
        return MaterialityDecision(
            material=True,
            reason=f"{tool_turns} assistant/tool turns in transcript",
        )

    if request.files_touched:
        return MaterialityDecision(
            material=True,
            reason=f"{len(request.files_touched)} file(s) modified",
        )

    distinct_commands = _distinct_commands(request.commands_run)
    if distinct_commands >= 2:
        return MaterialityDecision(
            material=True,
            reason=f"{distinct_commands} distinct shell commands",
        )

    return MaterialityDecision(material=False, reason="trivial session")


def _count_assistant_turns(transcript: Sequence[TaskforceTranscriptTurn]) -> int:
    return sum(1 for turn in transcript if turn.role in {"assistant", "tool"})


def _distinct_commands(commands: Sequence[TaskforceCommandRun]) -> int:
    seen: set[str] = set()
    for command in commands:
        token = command.cmd.strip().split(maxsplit=1)
        if token:
            seen.add(token[0])
    return len(seen)
