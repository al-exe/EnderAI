"""Unit tests for materiality + redaction (TF-178).

Both modules are pure; we test without a DB.
"""

from __future__ import annotations

import uuid

from app.core.taskforce.materiality import assess_materiality
from app.core.taskforce.redaction import redact
from app.models import (
    TaskforceCommandRun,
    TaskforceObserveRequest,
    TaskforceTranscriptTurn,
)


def _request(**overrides) -> TaskforceObserveRequest:
    base = dict(
        kind="final",
        prompt="anything",
        transcript=[],
        active_document_id=None,
        files_touched=[],
        commands_run=[],
        duration_ms=0,
        harness=None,
    )
    base.update(overrides)
    return TaskforceObserveRequest(**base)  # type: ignore[arg-type]


# ----- materiality ----------------------------------------------------------


def test_trivial_session_is_not_material() -> None:
    decision = assess_materiality(_request())
    assert decision.material is False
    assert "trivial" in decision.reason


def test_pinned_document_is_always_material() -> None:
    decision = assess_materiality(
        _request(active_document_id=uuid.uuid4()),
    )
    assert decision.material is True
    assert "pinned" in decision.reason


def test_many_turns_is_material() -> None:
    transcript = [
        TaskforceTranscriptTurn(role="assistant", content=f"turn {i}") for i in range(3)
    ]
    decision = assess_materiality(_request(transcript=transcript))
    assert decision.material is True
    assert "3 assistant" in decision.reason


def test_one_file_modified_is_material() -> None:
    decision = assess_materiality(_request(files_touched=["src/foo.py"]))
    assert decision.material is True
    assert "1 file" in decision.reason


def test_two_distinct_commands_is_material() -> None:
    commands = [
        TaskforceCommandRun(cmd="git status"),
        TaskforceCommandRun(cmd="git diff"),
        TaskforceCommandRun(cmd="git status"),  # dup, dedupes by first token
    ]
    decision = assess_materiality(_request(commands_run=commands))
    assert decision.material is True
    assert "2 distinct" in decision.reason


def test_one_command_alone_is_not_material() -> None:
    commands = [
        TaskforceCommandRun(cmd="git status"),
        TaskforceCommandRun(cmd="git status"),  # dup
    ]
    decision = assess_materiality(_request(commands_run=commands))
    assert decision.material is False


# ----- redaction ------------------------------------------------------------


def test_redact_env_var_assignment() -> None:
    assert "[REDACTED]" in redact("API_KEY=verysecretvalue1234")
    assert "[REDACTED]" in redact("password = hunter2hunter2")
    assert "[REDACTED]" in redact("secret: mysecrettoken")


def test_redact_authorization_header() -> None:
    assert "[REDACTED]" in redact("Authorization: Bearer eyJabcdefghijklmnopqrst.payload.sig")
    assert "[REDACTED]" in redact("authorization: token123abcdefghij")


def test_redact_anthropic_key_first() -> None:
    result = redact("sk-ant-veryverysecretsecretsecret")
    assert "[REDACTED-ANTHROPIC-KEY]" in result
    assert "[REDACTED-OPENAI-KEY]" not in result


def test_redact_openai_key_when_no_anthropic_prefix() -> None:
    result = redact("sk-veryverysecretsecretsecret")
    assert "[REDACTED-OPENAI-KEY]" in result


def test_redact_github_token() -> None:
    assert "[REDACTED-GITHUB-TOKEN]" in redact("ghp_abcdefghijklmnopqrstuvwxyz0123456789")


def test_redact_idempotent() -> None:
    once = redact("API_KEY=verysecretvalue1234")
    twice = redact(once)
    assert once == twice


def test_redact_passes_benign_text_through() -> None:
    text = "Refactored src/foo.py and updated docs/usage.md. No secrets here."
    assert redact(text) == text
