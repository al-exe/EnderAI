from __future__ import annotations

from app.core.agents.subagent_export import (
    ExportDocument,
    ExportSpecialist,
    render_claude_subagent,
    subagent_content_hash,
    subagent_filename,
)

_BILLING = ExportSpecialist(
    slug="billing-specialist",
    short_description="Stripe billing & webhooks.",
    routing_triggers=["stripe", "webhook", "stripe"],  # dupe is dropped
    negative_triggers=["refunds ui"],
    instructions=[
        "You own Stripe billing & webhooks.",
        "  ",  # blank is dropped
        "Prefer idempotent handlers; never trust unverified events.",
    ],
    model_hint="sonnet",
    permission_scope="readonly",
    documents=[
        ExportDocument(
            title="Webhook signature verification",
            details=(
                "Verify every event with STRIPE_WEBHOOK_SECRET before parsing; "
                "reject on skew > 5m."
            ),
            backlink="taskforce.tools/v2/library/abc",
            weight=0.9,
            is_pinned=True,
        )
    ],
)

_BILLING_GOLDEN = """\
---
name: billing-specialist
description: |-
  Stripe billing & webhooks.
  Use when: stripe, webhook.
  Do NOT use when: refunds ui.
model: sonnet
tools: Read, Grep, Glob, WebFetch
---
You own Stripe billing & webhooks.
Prefer idempotent handlers; never trust unverified events.

## Documents

### Webhook signature verification
Verify every event with STRIPE_WEBHOOK_SECRET before parsing; reject on skew > 5m.
↳ taskforce.tools/v2/library/abc
"""


def test_render_readonly_golden() -> None:
    assert render_claude_subagent(_BILLING) == _BILLING_GOLDEN


def test_render_full_scope_omits_tools_and_keeps_model() -> None:
    spec = ExportSpecialist(
        slug="refactor-agent",
        short_description="Big refactors.",
        model_hint="opus",
        permission_scope="full",
        instructions=["Move fast, keep tests green."],
    )
    rendered = render_claude_subagent(spec)

    assert "model: opus" in rendered
    assert "tools:" not in rendered  # full scope inherits all tools
    assert rendered.endswith("Move fast, keep tests green.\n")


def test_render_is_deterministic_and_hash_stable() -> None:
    first = render_claude_subagent(_BILLING)
    second = render_claude_subagent(_BILLING)
    assert first == second
    assert subagent_content_hash(first) == subagent_content_hash(second)

    other = render_claude_subagent(
        ExportSpecialist(slug="billing-specialist", short_description="changed")
    )
    assert subagent_content_hash(other) != subagent_content_hash(first)


def test_empty_specialist_still_valid_frontmatter() -> None:
    rendered = render_claude_subagent(ExportSpecialist(slug="lonely"))
    assert rendered.startswith("---\nname: lonely\n")
    assert "Taskforce specialist: lonely." in rendered
    assert "## Documents" not in rendered
    assert "model: inherit" in rendered


def test_documents_pruned_by_budget_keeping_pinned_first() -> None:
    documents = [
        ExportDocument(title="A", details="a" * 100, weight=0.1, is_pinned=True),
        ExportDocument(title="B", details="b" * 100, weight=0.9),
        ExportDocument(title="C", details="c" * 100, weight=0.5),
    ]
    spec = ExportSpecialist(slug="s", documents=documents)

    rendered = render_claude_subagent(spec, max_doc_chars=100, max_docs_chars=210)

    # Pinned A survives despite the lowest weight; the tail (C) is dropped.
    assert "### A" in rendered
    assert "### B" in rendered
    assert "### C" not in rendered


def test_long_details_truncated_to_doc_budget() -> None:
    spec = ExportSpecialist(
        slug="s",
        documents=[ExportDocument(title="Long", details="x" * 1000)],
    )
    rendered = render_claude_subagent(spec, max_doc_chars=50)
    body_line = next(
        line for line in rendered.splitlines() if line.startswith("x")
    )
    assert len(body_line) <= 50
    assert body_line.endswith("…")


def test_subagent_filename() -> None:
    assert subagent_filename("billing-specialist") == "billing-specialist.md"
