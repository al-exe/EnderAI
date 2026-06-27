from app.core.taskforce.conversation_summary import (
    apply_conversation_summary_from_summary,
    resolve_session_label,
    summarize_opening_prompt,
)
from app.core.taskforce.summarizer import SummarizerResult
from app.models import TaskforceSessionArchive


def _summary(**kwargs: object) -> SummarizerResult:
    defaults = {
        "materiality_score": 1.0,
        "summary_points": [],
        "details_sections": [],
        "files_touched": [],
        "commands_of_interest": [],
        "decisions": [],
        "outcome": None,
        "open_questions": [],
    }
    defaults.update(kwargs)
    return SummarizerResult(**defaults)  # type: ignore[arg-type]


def test_summarize_opening_prompt_strips_polite_prefixes() -> None:
    assert (
        summarize_opening_prompt("Can you fix the checkout bug?")
        == "Fixing the checkout bug?"
    )


def test_summarize_opening_prompt_strips_greetings() -> None:
    assert (
        summarize_opening_prompt(
            "Hi, help me fix up the landing page so it's mobile friendly"
        )
        == "Fixing up the landing page so it's mobile friendly"
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


def test_summarize_opening_prompt_preserves_long_first_sentence_without_ellipsis() -> None:
    prompt = (
        "There's a handoff doc between cursor and you for the demo, "
        "what do I need to do before we walk through the checkout flow?"
    )
    label = summarize_opening_prompt(prompt)
    assert "…" not in label
    assert label.endswith("?")
    assert "checkout flow" in label


def test_resolve_session_label_prefers_haiku_session_label() -> None:
    summary = _summary(session_label="Mobile landing page for iPhone Pro sizes")
    assert (
        resolve_session_label(
            summary,
            prompt="Hi, help me fix up the landing page so it's mobile friendly",
        )
        == "Mobile landing page for iPhone Pro sizes"
    )


def test_apply_conversation_summary_upgrades_verbatim_heuristic() -> None:
    archive = TaskforceSessionArchive(
        session_id="sess-1",
        actor_id="00000000-0000-0000-0000-000000000001",
        organization_id="00000000-0000-0000-0000-000000000002",
        is_demo=False,
        conversation_summary=(
            "Hi, help me fix up the landing page so it's mobile friendly, "
            "optimized for iphone 15pro and iphone 17 pro dimensions"
        ),
    )
    summary = _summary(session_label="Mobile-friendly landing page for iPhone Pro")
    apply_conversation_summary_from_summary(
        archive,
        summary,
        prompt=archive.conversation_summary or "",
    )
    assert archive.conversation_summary == "Mobile-friendly landing page for iPhone Pro"


def test_apply_conversation_summary_upgrades_weak_greeting_label() -> None:
    archive = TaskforceSessionArchive(
        session_id="sess-1",
        actor_id="00000000-0000-0000-0000-000000000001",
        organization_id="00000000-0000-0000-0000-000000000002",
        is_demo=False,
        conversation_summary="Hi",
    )
    summary = _summary(
        summary_points=["Investigate why Codex session titles stay on greetings"]
    )
    apply_conversation_summary_from_summary(
        archive,
        summary,
        prompt="Investigate why Codex session titles stay on greetings",
    )
    assert (
        archive.conversation_summary
        == "Investigate why Codex session titles stay on greetings"
    )


def test_apply_conversation_summary_respects_user_display_name() -> None:
    archive = TaskforceSessionArchive(
        session_id="sess-1",
        actor_id="00000000-0000-0000-0000-000000000001",
        organization_id="00000000-0000-0000-0000-000000000002",
        is_demo=False,
        display_name="My custom name",
        conversation_summary="Old summary",
    )
    summary = _summary(session_label="Should not apply")
    apply_conversation_summary_from_summary(archive, summary, prompt="ignored")
    assert archive.conversation_summary == "Old summary"
