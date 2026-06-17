from app.core.taskforce.active_sessions import _agent_kind


def test_agent_kind_prefers_client_over_claude_model_id() -> None:
    assert _agent_kind("cursor", "claude-sonnet-4-6", None) == "cursor"


def test_agent_kind_uses_harness_label_when_client_missing() -> None:
    assert _agent_kind(None, "claude-sonnet-4-6", "cursor") == "cursor"
    assert _agent_kind(None, "claude-opus-4-8", "claude-code") == "claude"


def test_agent_kind_does_not_infer_claude_from_model_id_alone() -> None:
    assert _agent_kind(None, "claude-sonnet-4-6", None) == "other"


def test_agent_kind_infers_codex_from_openai_model_id() -> None:
    assert _agent_kind(None, "gpt-5.4", None) == "codex"
