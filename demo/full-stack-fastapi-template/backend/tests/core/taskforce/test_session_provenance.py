from app.core.taskforce.session_provenance import merge_session_client


def test_merge_prefers_cursor_over_claude_code_default() -> None:
    assert merge_session_client("cursor", "claude-code") == "cursor"


def test_merge_allows_cursor_to_replace_claude_code() -> None:
    assert merge_session_client("claude-code", "cursor") == "cursor"


def test_merge_keeps_codex_over_claude_code() -> None:
    assert merge_session_client("codex", "claude-code") == "codex"


def test_merge_sets_incoming_when_existing_missing() -> None:
    assert merge_session_client(None, "cursor") == "cursor"
