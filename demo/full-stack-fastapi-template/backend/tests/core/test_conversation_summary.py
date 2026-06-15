from app.core.taskforce.conversation_summary import summarize_opening_prompt


def test_summarize_opening_prompt_strips_polite_prefixes() -> None:
    assert (
        summarize_opening_prompt("Can you fix the checkout bug?")
        == "Fixing the checkout bug"
    )


def test_summarize_opening_prompt_uses_gerund_for_imperatives() -> None:
    assert (
        summarize_opening_prompt("Implement the fleet session defaults")
        == "Implementing the fleet session defaults"
    )


def test_summarize_opening_prompt_keeps_first_sentence_only() -> None:
    assert (
        summarize_opening_prompt("Wire automatic tax. Then add tests.")
        == "Wiring automatic tax"
    )
