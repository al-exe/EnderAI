"""Regression tests for Cursor transcript extraction jq."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

CURSOR_TRANSCRIPT_JQ = (
    Path(__file__).resolve().parents[6]
    / "scripts"
    / "taskforce-cursor-hooks"
    / "transcript-extract.jq"
)


def test_transcript_extract_jq_reads_cursor_role_format() -> None:
    lines = [
        {
            "role": "user",
            "message": {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "<user_query>\n"
                            "how many sibling agents are in session #1\n"
                            "</user_query>"
                        ),
                    }
                ]
            },
        },
        {
            "role": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Checking the live Taskforce fleet roster."}
                ]
            },
        },
    ]
    payload = "\n".join(json.dumps(line) for line in lines)
    result = subprocess.run(
        ["jq", "-sf", str(CURSOR_TRANSCRIPT_JQ)],
        input=payload,
        text=True,
        capture_output=True,
        check=True,
    )
    turns = json.loads(result.stdout)
    assert [turn["role"] for turn in turns] == ["user", "assistant"]
    assert "how many sibling agents" in turns[0]["content"]
    assert turns[1]["content"].startswith("Checking the live Taskforce")
