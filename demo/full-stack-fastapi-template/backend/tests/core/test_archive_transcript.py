"""Transcript normalization for Ledger session archives."""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.taskforce.archive import _normalized_events
from app.models import TaskforceCommandRun, TaskforceObserveRequest, TaskforceTranscriptTurn


def _request(
    *,
    transcript: list[TaskforceTranscriptTurn],
    commands_run: list[TaskforceCommandRun] | None = None,
    prompt: str = "",
) -> TaskforceObserveRequest:
    return TaskforceObserveRequest(
        kind="checkpoint",
        prompt=prompt,
        transcript=transcript,
        commands_run=commands_run or [],
    )


def test_normalized_events_skip_tool_results_and_empty_replies() -> None:
    now = datetime(2026, 6, 15, 7, 0, tzinfo=timezone.utc)
    events = _normalized_events(
        _request(
            transcript=[
                TaskforceTranscriptTurn(role="user", content="merge"),
                TaskforceTranscriptTurn(role="assistant", content=""),
                TaskforceTranscriptTurn(
                    role="tool",
                    content="Error: No tests found.",
                ),
                TaskforceTranscriptTurn(
                    role="assistant",
                    content="Vite serves fine — harness issue.",
                ),
            ]
        ),
        now=now,
    )

    assert [event["kind"] for event in events] == ["prompt", "reply"]
    assert events[0]["text"] == "merge"
    assert events[1]["text"] == "Vite serves fine — harness issue."


def test_normalized_events_attach_command_output() -> None:
    now = datetime(2026, 6, 15, 7, 0, tzinfo=timezone.utc)
    events = _normalized_events(
        _request(
            transcript=[
                TaskforceTranscriptTurn(role="user", content="run tests"),
                TaskforceTranscriptTurn(
                    role="assistant",
                    content="Running the fleet spec now.",
                ),
            ],
            commands_run=[
                TaskforceCommandRun(
                    cmd="npx playwright test tests/fleet.spec.ts",
                    exit_code=0,
                    output="7 passed (12.2s)",
                )
            ],
        ),
        now=now,
    )

    command = next(event for event in events if event["kind"] == "command")
    assert command["cmd"] == "npx playwright test tests/fleet.spec.ts"
    assert command["output"] == "7 passed (12.2s)"
