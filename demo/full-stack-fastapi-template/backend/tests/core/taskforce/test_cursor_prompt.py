"""Tests for Cursor prompt normalization."""

from app.core.taskforce.cursor_prompt import clean_cursor_user_prompt


def test_strips_user_query_wrapper() -> None:
    assert (
        clean_cursor_user_prompt("<user_query>\nmerge\n</user_query>")
        == "merge"
    )


def test_keeps_plain_prompts() -> None:
    assert (
        clean_cursor_user_prompt("check your hooks, are they working?")
        == "check your hooks, are they working?"
    )


def test_extracts_tail_from_fleet_ui_paste() -> None:
    pasted = """<user_query>
This rename fleet is ugly please fix
awaiting prompt · now
View in Ledger
Activity
now
Awaiting user prompt
08:16 PMprompt
ok, so its should work rightn ow?
08:13 PMprompt
merge 

Looks good!
</user_query>"""
    assert clean_cursor_user_prompt(pasted) == "Looks good!"


def test_extracts_issue_report_from_activity_paste() -> None:
    pasted = """Activity
3m
Awaiting user prompt
08:17 PMprompt
This rename fleet is ugly please fix awaiting prompt · now View in Ledger

Something might have fucked up. the text is incorrect on this last one"""
    assert (
        clean_cursor_user_prompt(pasted)
        == "Something might have fucked up. the text is incorrect on this last one"
    )
