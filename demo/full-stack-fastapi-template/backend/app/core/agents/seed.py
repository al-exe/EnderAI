"""Manual demo seed helpers for TF-198.

These functions are intentionally not imported from app startup or migrations.
Run them only via the one-shot scripts in ``app.scripts`` when preparing the
Taskforce demo account.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlmodel import Session, col, select

from app.core.v2_documents import ensure_v2_documents_demo_seed
from app.models import (
    METRICS_EVENT_DOCUMENT_CONSULTED,
    METRICS_EVENT_DOCUMENT_CREATED,
    METRICS_EVENT_DOCUMENT_REUSED,
    METRICS_EVENT_TOKENS_CONSUMED,
    METRICS_EVENT_TOKENS_SAVED_CACHE,
    METRICS_EVENT_TOKENS_SAVED_REUSE,
    METRICS_EVENT_TOKENS_SAVED_SUMMARY_ONLY,
    AgentSpecialist,
    AgentSpecialistDocumentLink,
    MetricsEvent,
    User,
    V2Document,
)

MODEL_ID = "claude-opus-4-7"

# $/token rates for seeded usd_amount fields. Opus input uses the $15/MTok
# offset rate from the metrics math writeup (not the older list-price row).
_OPUS_INPUT_RATE = Decimal("0.000015")
_OPUS_OUTPUT_RATE = Decimal("0.000075")
_HAIKU_INPUT_RATE = Decimal("0.000001")
_HAIKU_OUTPUT_RATE = Decimal("0.000005")
_SONNET_INPUT_RATE = Decimal("0.000003")
_SONNET_OUTPUT_RATE = Decimal("0.000015")
_GPT5_INPUT_RATE = Decimal("0.0000025")
_GPT5_OUTPUT_RATE = Decimal("0.00001")

_RATES_BY_MODEL: dict[str, tuple[Decimal, Decimal]] = {
    "claude-opus-4-7": (_OPUS_INPUT_RATE, _OPUS_OUTPUT_RATE),
    "claude-haiku-4-7": (_HAIKU_INPUT_RATE, _HAIKU_OUTPUT_RATE),
    "claude-sonnet-4-7": (_SONNET_INPUT_RATE, _SONNET_OUTPUT_RATE),
    "gpt-5": (_GPT5_INPUT_RATE, _GPT5_OUTPUT_RATE),
}

# --- Demo metrics dashboard targets (7d window, prior 7d for deltas) --------
# See docs/taskforce-backend-architecture-overview.md §Discovery And Rediscovery.

_TOKENS_SAVED_7D = 847_200
_TOKENS_SAVED_PREV_7D = 612_100
_SAVED_CACHE_7D = 278_300
_SAVED_SUMMARY_7D = 468_900
_SAVED_REUSE_7D = 100_000
_AVOIDED_REDISCOVERY_7D = 1_410_000
_AVOIDED_REDISCOVERY_PREV_7D = 980_200
_REUSED_BEGIN_7D = 12
_CREATED_BEGIN_7D = 16
_REUSED_BEGIN_PREV_7D = 9
_CREATED_BEGIN_PREV_7D = 15
_DAILY_SAVED_7D = (62_000, 84_000, 118_000, 96_000, 174_000, 145_000, 105_000, 63_200)
_CONSUMED_BY_MODEL_7D: tuple[tuple[str, int, Decimal], ...] = (
    ("claude-opus-4-7", 128_400, Decimal("3.25")),
    ("claude-haiku-4-7", 163_800, Decimal("0.37")),
    ("claude-sonnet-4-7", 20_200, Decimal("0.19")),
)
_CONSUMED_BY_MODEL_PREV_7D: tuple[tuple[str, int, Decimal], ...] = (
    ("claude-opus-4-7", 96_200, Decimal("2.44")),
    ("claude-haiku-4-7", 122_900, Decimal("0.28")),
    ("claude-sonnet-4-7", 15_700, Decimal("0.14")),
)

DOCUMENT_SLUG_TITLES = {
    "stripe-webhook-idempotency-strategy": "Stripe webhook idempotency strategy",
    "debugging-stripe-webhook-flakes": (
        "Debugging Stripe webhook retries and double-fire fulfillment"
    ),
    "stripe-plan-upgrade-regression-coverage": (
        "Stripe plan upgrade webhook retries — regression test pattern"
    ),
    "search-indexer-drift-sweep-design": "Search indexer drift-sweep design",
    "pgvector-acl-retrieval-gotchas": "pgvector retrieval and ACL gotchas",
    "citation-anchor-fanout-playbook": "Citation anchor fanout playbook",
    "claude-code-taskforce-hook-setup": "Claude Code Taskforce hook setup",
    "hosted-mcp-session-lifecycle": "Hosted MCP session lifecycle",
    "agent-credential-rotation-playbook": "Agent credential rotation playbook",
    "taskforce-session-savings-math": "Taskforce session savings math",
    "metrics-event-rollup-architecture": "Metrics event rollup architecture",
    "demo-metrics-page-session-filter": "Demo metrics page session filter",
    "evidence-anchor-authoring-guide": "Evidence anchor authoring guide",
    "referenced-by-update-policy": "Referenced-by update policy",
    "document-reuse-vs-create-playbook": "Document reuse vs create playbook",
    "webhook-signature-clock-skew": "Webhook signature clock skew",
    "taskforce-discover-timeout-budget": "Taskforce discover timeout budget",
    "observe-structured-payload-shortcut": "Observe structured payload shortcut",
    "metrics-pricing-snapshot-semantics": "Metrics pricing snapshot semantics",
    "mcp-bearer-session-binding": "MCP bearer session binding",
    "v2-document-token-count-refresh": "V2 document token count refresh",
    "search-byok-vs-managed-embeddings": "Search BYOK vs managed embeddings",
    "stripe-checkout-metadata-contract": "Stripe checkout metadata contract",
}


SEEDED_SPECIALISTS: list[dict[str, Any]] = [
    {
        "slug": "jensen",
        "name": "Jensen",
        "role": "Billing Reliability Profile",
        "short_description": (
            "Stripe webhooks, subscriptions, retries, and double-charge prevention."
        ),
        "description": (
            "Jensen helps debug Stripe billing incidents, especially duplicate "
            "webhook fulfillment, plan upgrades, idempotency boundaries, and "
            "customer-visible charge regressions."
        ),
        "domain_tags": ["Stripe", "Billing", "Webhooks"],
        "routing_triggers": [
            "stripe",
            "billing",
            "webhook",
            "subscription",
            "plan upgrade",
            "double charge",
            "duplicate invoice",
            "idempotency",
            "customer.subscription.updated",
            "invoice.payment_succeeded",
        ],
        "negative_triggers": [
            "pricing page copy",
            "frontend billing layout",
            "non-stripe payment provider",
        ],
        "instructions": [
            "Start with route-boundary idempotency before handler internals.",
            "Check whether duplicate events short-circuit before fulfillment.",
            "Separate Stripe test-mode and live-mode evidence.",
            "Ask for side-effect assertions, not only HTTP 200 replay tests.",
            "Prefer pinned Stripe docs before broader billing docs.",
        ],
    },
    {
        "slug": "mira",
        "name": "Mira",
        "role": "Search Retrieval Profile",
        "short_description": (
            "Search indexing, embeddings, pgvector retrieval, ACLs, and citations."
        ),
        "description": (
            "Mira helps debug V2 document search, embedding drift, retrieval "
            "ACLs, chunk fanout, and citation anchors."
        ),
        "domain_tags": ["Search", "Embeddings", "Retrieval"],
        "routing_triggers": [
            "search",
            "retrieval",
            "embedding",
            "pgvector",
            "citation",
            "indexing",
            "source_item_embedding",
            "vector",
        ],
        "negative_triggers": ["billing webhook", "stripe charge"],
        "instructions": [
            "Confirm indexing drift before changing retrieval scoring.",
            "Check document ACL filters and embedding ACL denormalization.",
            "Keep citation hrefs pointed at canonical evidence anchors.",
            "Use source_item_embedding rows to debug missing chunks.",
            "Avoid re-embedding when an ACL-only fix is sufficient.",
        ],
    },
    {
        "slug": "orin",
        "name": "Orin",
        "role": "Agent Integration Profile",
        "short_description": (
            "MCP, Claude Code hooks, agent credentials, and session lifecycle."
        ),
        "description": (
            "Orin helps connect agents to Taskforce through hooks, hosted MCP, "
            "credential validation, session_start, and session_observe flows."
        ),
        "domain_tags": ["MCP", "Hooks", "Agent Auth"],
        "routing_triggers": [
            "mcp",
            "claude code",
            "hook",
            "userpromptsubmit",
            "posttooluse",
            "stop hook",
            "agent credential",
            "bearer",
            "session_start",
            "session_observe",
        ],
        "negative_triggers": ["stripe invoice", "metrics dashboard"],
        "instructions": [
            "Validate token kind and credential version before transport bugs.",
            "Keep UserPromptSubmit synchronous paths fast and timeout-bound.",
            "Separate hook failures from backend observe failures.",
            "Check Mcp-Session-Id binding when hosted MCP calls go missing.",
            "Prefer explicit lifecycle logs over silent hook retries.",
        ],
    },
    {
        "slug": "vega",
        "name": "Vega",
        "role": "Metrics Economics Profile",
        "short_description": (
            "Token savings, pricing snapshots, rollups, and session metrics."
        ),
        "description": (
            "Vega helps explain Taskforce savings math, avoided rediscovery "
            "tokens, model pricing snapshots, and metrics dashboard rollups."
        ),
        "domain_tags": ["Metrics", "Savings", "Pricing"],
        "routing_triggers": [
            "metrics",
            "savings",
            "tokens saved",
            "avoided rediscovery",
            "pricing",
            "model_pricing",
            "rollup",
            "session_savings",
            "dashboard",
        ],
        "negative_triggers": ["stripe webhook replay", "mcp token"],
        "instructions": [
            "Tie every savings figure back to consulted documents.",
            "Use pricing snapshots effective at event write time.",
            "Keep demo and live metrics isolated by is_demo.",
            "Explain gross, consult cost, and net saved tokens separately.",
            "Prefer session-scoped metrics when debugging demo numbers.",
        ],
    },
    {
        "slug": "nia",
        "name": "Nia",
        "role": "Knowledge Steward Profile",
        "short_description": (
            "Document quality, evidence anchors, referenced-by rows, and reuse."
        ),
        "description": (
            "Nia helps decide when to reuse or create Taskforce documents, how "
            "to author evidence anchors, and how to close the loop after reuse."
        ),
        "domain_tags": ["Knowledge", "Documents", "Evidence"],
        "routing_triggers": [
            "document",
            "knowledge",
            "anchor",
            "evidence",
            "referenced by",
            "summary",
            "decision record",
            "reusable context",
            "doc patch",
        ],
        "negative_triggers": ["stripe webhook", "pgvector index"],
        "instructions": [
            "Prefer patching existing docs when repo, files, and intent align.",
            "Use stable evidence anchors that describe click targets.",
            "Separate decisions, incidents, gotchas, and verification steps.",
            "Add referenced-by rows only for material reuse.",
            "Create a new document when conflicts make reuse misleading.",
        ],
    },
]

SPECIALIST_DOCUMENT_LINKS: dict[str, list[tuple[str, str, str]]] = {
    "jensen": [
        (
            "stripe-webhook-idempotency-strategy",
            "decision-wal-table",
            "Route-boundary idempotency decision record.",
        ),
        (
            "debugging-stripe-webhook-flakes",
            "repro-with-stripe-cli",
            "Operational playbook for webhook retries.",
        ),
        (
            "stripe-plan-upgrade-regression-coverage",
            "targeted-regression-test",
            "Regression pattern for plan-upgrade duplicate delivery.",
        ),
    ],
    "mira": [
        (
            "search-indexer-drift-sweep-design",
            "drift-sweep-loop",
            "Indexer drift detection design.",
        ),
        (
            "pgvector-acl-retrieval-gotchas",
            "acl-double-enforcement",
            "ACL-filtered retrieval debugging.",
        ),
        (
            "citation-anchor-fanout-playbook",
            "long-section-anchor-fanout",
            "Citation anchor fanout policy.",
        ),
    ],
    "orin": [
        (
            "claude-code-taskforce-hook-setup",
            "userpromptsubmit-flow",
            "Claude Code hook setup flow.",
        ),
        (
            "hosted-mcp-session-lifecycle",
            "streamable-http-session-map",
            "Hosted MCP session binding.",
        ),
        (
            "agent-credential-rotation-playbook",
            "revoke-rotate-debug",
            "Agent credential rotation checklist.",
        ),
    ],
    "vega": [
        (
            "taskforce-session-savings-math",
            "rediscovery-minus-consult",
            "Session savings formula.",
        ),
        (
            "metrics-event-rollup-architecture",
            "pricing-snapshot-at-write",
            "Metrics event and pricing architecture.",
        ),
        (
            "demo-metrics-page-session-filter",
            "session-id-query-param",
            "Session-scoped metrics demo link.",
        ),
    ],
    "nia": [
        (
            "evidence-anchor-authoring-guide",
            "anchor-naming-rules",
            "Evidence anchor naming rules.",
        ),
        (
            "referenced-by-update-policy",
            "close-the-loop",
            "Referenced-by update policy.",
        ),
        (
            "document-reuse-vs-create-playbook",
            "reuse-decision-criteria",
            "Reuse-vs-create decision criteria.",
        ),
    ],
}


@dataclass(frozen=True)
class AgentSeedResult:
    specialists_created: int
    documents_created: bool
    links_created: int


@dataclass(frozen=True)
class MetricsSeedResult:
    sessions_created: int
    events_created: int


def _document_by_slug(session: Session, user: User) -> dict[str, V2Document]:
    docs = session.exec(
        select(V2Document)
        .where(V2Document.owner_id == user.id)
        .where(V2Document.is_demo.is_(True))  # type: ignore[union-attr]
    ).all()
    by_title = {doc.title: doc for doc in docs}
    return {
        slug: by_title[title]
        for slug, title in DOCUMENT_SLUG_TITLES.items()
        if title in by_title
    }


def _delete_existing_seeded_specialists(session: Session) -> None:
    existing = list(
        session.exec(
            select(AgentSpecialist)
            .where(AgentSpecialist.created_from == "seeded")
            .where(AgentSpecialist.is_demo.is_(True))  # type: ignore[union-attr]
        ).all()
    )
    if not existing:
        return

    specialist_ids = [specialist.id for specialist in existing]
    links = session.exec(
        select(AgentSpecialistDocumentLink).where(
            col(AgentSpecialistDocumentLink.specialist_id).in_(specialist_ids)
        )
    ).all()
    for link in links:
        session.delete(link)
    session.flush()
    for specialist in existing:
        session.delete(specialist)
    session.flush()


def seed_agents(session: Session, user: User) -> AgentSeedResult:
    """Seed five demo specialists and their linked V2 knowledge for ``user``."""

    documents_created = ensure_v2_documents_demo_seed(session, user)
    session.flush()

    _delete_existing_seeded_specialists(session)

    specialists_by_slug: dict[str, AgentSpecialist] = {}
    for payload in SEEDED_SPECIALISTS:
        specialist = AgentSpecialist(
            owner_id=user.id,
            organization_id=None,
            slug=payload["slug"],
            name=payload["name"],
            role=payload["role"],
            short_description=payload["short_description"],
            description=payload["description"],
            status="active",
            visibility="demo",
            domain_tags=list(payload["domain_tags"]),
            routing_triggers=list(payload["routing_triggers"]),
            negative_triggers=list(payload["negative_triggers"]),
            instructions=list(payload["instructions"]),
            created_from="seeded",
            is_demo=True,
        )
        session.add(specialist)
        specialists_by_slug[payload["slug"]] = specialist
    session.flush()

    docs_by_slug = _document_by_slug(session, user)
    links_created = 0
    for specialist_slug, links in SPECIALIST_DOCUMENT_LINKS.items():
        specialist = specialists_by_slug[specialist_slug]
        for index, (doc_slug, anchor_id, reason) in enumerate(links):
            document = docs_by_slug.get(doc_slug)
            if document is None:
                continue
            session.add(
                AgentSpecialistDocumentLink(
                    specialist_id=specialist.id,
                    document_id=document.id,
                    anchor_id=anchor_id,
                    reason=reason,
                    weight=1.0 - (index * 0.05),
                    is_pinned=True,
                )
            )
            links_created += 1

    return AgentSeedResult(
        specialists_created=len(specialists_by_slug),
        documents_created=documents_created,
        links_created=links_created,
    )


def _event_dt(days_ago: int, hour: int) -> datetime:
    return datetime.now(timezone.utc).replace(
        hour=hour, minute=0, second=0, microsecond=0
    ) - timedelta(days=days_ago)


ALEX_DEMO_INVOCATIONS: list[dict[str, Any]] = [
    {
        "specialist_slug": "jensen",
        "documents": [
            "stripe-webhook-idempotency-strategy",
            "debugging-stripe-webhook-flakes",
            "stripe-plan-upgrade-regression-coverage",
        ],
        "prompt": (
            "Stripe is double-charging some users on plan upgrade — looks "
            "like webhook retries are fulfilled twice."
        ),
        "summary": "Routed to Jensen and reused Stripe idempotency docs.",
        "repo": "al-exe/EnderAI",
        "branch": "demo/stripe-double-charge",
        "tokens": 18400,
        "days_ago": 1,
    },
    {
        "specialist_slug": "jensen",
        "documents": [
            "stripe-webhook-idempotency-strategy",
            "debugging-stripe-webhook-flakes",
        ],
        "prompt": "Replay a Stripe webhook and prove duplicate delivery short-circuits.",
        "summary": "Checked WAL ordering and replay diagnostics.",
        "repo": "al-exe/EnderAI",
        "branch": "fix/stripe-webhook-replay",
        "tokens": 12600,
        "days_ago": 9,
    },
    {
        "specialist_slug": "jensen",
        "documents": [
            "stripe-plan-upgrade-regression-coverage",
            "stripe-webhook-idempotency-strategy",
        ],
        "prompt": "Add the plan-upgrade regression assertion for duplicate webhook delivery.",
        "summary": "Focused the test on downstream side effects.",
        "repo": "al-exe/EnderAI",
        "branch": "test/plan-upgrade-retry",
        "tokens": 9600,
        "days_ago": 27,
    },
    {
        "specialist_slug": "mira",
        "documents": [
            "search-indexer-drift-sweep-design",
            "pgvector-acl-retrieval-gotchas",
        ],
        "prompt": "Search misses updated V2 docs after a details edit.",
        "summary": "Traced stale index markers and ACL-filtered retrieval.",
        "repo": "al-exe/EnderAI",
        "branch": "fix/search-index-drift",
        "tokens": 11800,
        "days_ago": 4,
    },
    {
        "specialist_slug": "mira",
        "documents": [
            "citation-anchor-fanout-playbook",
            "search-indexer-drift-sweep-design",
        ],
        "prompt": "Citation links land on chunk ids instead of document anchors.",
        "summary": "Mapped fanout chunks back to canonical anchors.",
        "repo": "al-exe/EnderAI",
        "branch": "fix/citation-anchors",
        "tokens": 8700,
        "days_ago": 33,
    },
    {
        "specialist_slug": "orin",
        "documents": [
            "claude-code-taskforce-hook-setup",
            "hosted-mcp-session-lifecycle",
        ],
        "prompt": "Claude Code hook discovery works locally but hosted MCP drops observe.",
        "summary": "Separated hook auth from MCP session binding.",
        "repo": "al-exe/EnderAI",
        "branch": "debug/mcp-observe",
        "tokens": 13600,
        "days_ago": 6,
    },
    {
        "specialist_slug": "orin",
        "documents": [
            "agent-credential-rotation-playbook",
            "hosted-mcp-session-lifecycle",
        ],
        "prompt": "Rotated agent token still validates from an old shell.",
        "summary": "Checked credential version and stale local config.",
        "repo": "al-exe/EnderAI",
        "branch": "fix/agent-token-rotation",
        "tokens": 15400,
        "days_ago": 38,
    },
    {
        "specialist_slug": "vega",
        "documents": [
            "taskforce-session-savings-math",
            "metrics-event-rollup-architecture",
        ],
        "prompt": "Explain why session savings differs from the metrics dashboard.",
        "summary": "Matched session net savings to event rollups.",
        "repo": "al-exe/EnderAI",
        "branch": "fix/session-savings",
        "tokens": 9400,
        "days_ago": 12,
    },
    {
        "specialist_slug": "vega",
        "documents": [
            "demo-metrics-page-session-filter",
            "taskforce-session-savings-math",
        ],
        "prompt": "Make the demo savings link open a session-scoped metrics view.",
        "summary": "Used the session_id query param contract.",
        "repo": "al-exe/EnderAI-frontend",
        "branch": "feature/session-metrics-filter",
        "tokens": 11200,
        "days_ago": 24,
    },
    {
        "specialist_slug": "nia",
        "documents": ["evidence-anchor-authoring-guide", "referenced-by-update-policy"],
        "prompt": "Patch referenced-by entries into docs used by an agent session.",
        "summary": "Used stable anchors and closed the reuse loop.",
        "repo": "al-exe/EnderAI",
        "branch": "feature/reference-endpoint",
        "tokens": 14600,
        "days_ago": 16,
    },
    {
        "specialist_slug": "nia",
        "documents": [
            "document-reuse-vs-create-playbook",
            "evidence-anchor-authoring-guide",
        ],
        "prompt": "Decide whether this follow-up should patch an old doc or create a new one.",
        "summary": "Applied reuse criteria and avoided a misleading patch.",
        "repo": "al-exe/EnderAI",
        "branch": "docs/reuse-policy",
        "tokens": 12100,
        "days_ago": 31,
    },
    {
        "specialist_slug": "mira",
        "documents": [
            "pgvector-acl-retrieval-gotchas",
            "citation-anchor-fanout-playbook",
        ],
        "prompt": "Debug why demo search returns live docs in one retrieval path.",
        "summary": "Confirmed demo/live isolation across retrieval filters.",
        "repo": "al-exe/EnderAI",
        "branch": "fix/demo-search-isolation",
        "tokens": 10300,
        "days_ago": 41,
    },
]


def _usd_for_tokens(
    model_id: str, *, input_tokens: int, output_tokens: int = 0
) -> Decimal:
    input_rate, output_rate = _RATES_BY_MODEL.get(
        model_id, (_OPUS_INPUT_RATE, _OPUS_OUTPUT_RATE)
    )
    return (Decimal(input_tokens) * input_rate) + (Decimal(output_tokens) * output_rate)


def _split_saved_triple(total: int) -> tuple[int, int, int]:
    cache = int(total * _SAVED_CACHE_7D / _TOKENS_SAVED_7D)
    summary = int(total * _SAVED_SUMMARY_7D / _TOKENS_SAVED_7D)
    reuse = total - cache - summary
    return cache, summary, reuse


def _distribute(total: int, weights: list[int]) -> list[int]:
    if not weights:
        return []
    weight_sum = sum(weights)
    if weight_sum <= 0:
        even = total // len(weights)
        return [even] * len(weights)
    parts = [int(total * weight / weight_sum) for weight in weights]
    remainder = total - sum(parts)
    for index in range(remainder):
        parts[index % len(parts)] += 1
    return parts


def _all_demo_document_slugs() -> list[str]:
    return list(DOCUMENT_SLUG_TITLES.keys())


def _build_metrics_session_specs() -> list[dict[str, Any]]:
    """Synthetic sessions that hit the TF-198 demo metrics dashboard targets."""

    specs: list[dict[str, Any]] = []
    slugs = _all_demo_document_slugs()
    consult_7d = slugs[:23]
    consult_prev = slugs[:17]
    avoided_7d = _distribute(_AVOIDED_REDISCOVERY_7D, [1] * len(consult_7d))
    avoided_prev = _distribute(_AVOIDED_REDISCOVERY_PREV_7D, [1] * len(consult_prev))

    consult_index = 0
    for day_index, daily_saved in enumerate(_DAILY_SAVED_7D):
        days_ago = 7 - day_index
        cache, summary, reuse = _split_saved_triple(daily_saved)
        day_count = 3 if consult_index + 3 <= len(consult_7d) else len(consult_7d) - consult_index
        day_consults = consult_7d[consult_index : consult_index + day_count]
        day_avoided = avoided_7d[consult_index : consult_index + day_count]
        consult_index += day_count
        specs.append(
            {
                "days_ago": days_ago,
                "hour": 9 + (day_index % 5),
                "specialist_slug": "vega",
                "prompt": "Consult prior work for the active incident.",
                "summary": "Surfaced related V2 documents on discover.",
                "repo": "al-exe/EnderAI",
                "branch": "demo/metrics-seed",
                "consultations": [
                    {"slug": slug, "avoided_tokens": avoided}
                    for slug, avoided in zip(day_consults, day_avoided, strict=True)
                ],
                "cache_tokens": cache,
                "summary_only_tokens": summary,
                "reuse_tokens": reuse,
            }
        )

    prev_daily = int(_TOKENS_SAVED_PREV_7D / 7)
    prev_consult_index = 0
    for day_offset in range(7):
        days_ago = 8 + day_offset
        cache, summary, reuse = _split_saved_triple(prev_daily)
        remaining = len(consult_prev) - prev_consult_index
        if remaining <= 0:
            break
        day_count = min(3, remaining)
        day_consults = consult_prev[prev_consult_index : prev_consult_index + day_count]
        day_avoided = avoided_prev[prev_consult_index : prev_consult_index + day_count]
        prev_consult_index += day_count
        specs.append(
            {
                "days_ago": days_ago,
                "hour": 14,
                "specialist_slug": "mira",
                "prompt": "Follow up on indexed knowledge from last week.",
                "summary": "Reused prior consult summaries.",
                "repo": "al-exe/EnderAI",
                "branch": "demo/metrics-seed-prev",
                "consultations": [
                    {"slug": slug, "avoided_tokens": avoided}
                    for slug, avoided in zip(day_consults, day_avoided, strict=True)
                ],
                "cache_tokens": cache,
                "summary_only_tokens": summary,
                "reuse_tokens": reuse,
            }
        )

    anchor_slug = slugs[0]
    for offset in range(_REUSED_BEGIN_7D):
        specs.append(
            {
                "days_ago": offset % 8,
                "hour": 16,
                "specialist_slug": "nia",
                "prompt": "Reuse an existing V2 document on begin.",
                "summary": "Congruence engine chose reuse.",
                "repo": "al-exe/EnderAI",
                "branch": "demo/begin-reuse",
                "anchor_slug": anchor_slug,
                "begin_reused": True,
            }
        )
    for offset in range(_CREATED_BEGIN_7D):
        specs.append(
            {
                "days_ago": (offset + 1) % 8,
                "hour": 17,
                "specialist_slug": "nia",
                "prompt": "Create a fresh V2 document on begin.",
                "summary": "Congruence engine declined reuse.",
                "repo": "al-exe/EnderAI",
                "branch": "demo/begin-create",
                "anchor_slug": slugs[offset % len(slugs)],
                "begin_created": True,
            }
        )
    for offset in range(_REUSED_BEGIN_PREV_7D):
        specs.append(
            {
                "days_ago": 8 + (offset % 7),
                "hour": 11,
                "specialist_slug": "orin",
                "prompt": "Reuse on begin (prior week).",
                "summary": "Prior-window reuse decision.",
                "repo": "al-exe/EnderAI",
                "branch": "demo/begin-reuse-prev",
                "anchor_slug": anchor_slug,
                "begin_reused": True,
            }
        )
    for offset in range(_CREATED_BEGIN_PREV_7D):
        specs.append(
            {
                "days_ago": 9 + (offset % 6),
                "hour": 12,
                "specialist_slug": "orin",
                "prompt": "Create on begin (prior week).",
                "summary": "Prior-window create decision.",
                "repo": "al-exe/EnderAI",
                "branch": "demo/begin-create-prev",
                "anchor_slug": slugs[(offset + 3) % len(slugs)],
                "begin_created": True,
            }
        )

    consumed_anchor = slugs[0]
    for model_id, tokens, usd in _CONSUMED_BY_MODEL_7D:
        specs.append(
            {
                "days_ago": 3,
                "hour": 18,
                "specialist_slug": "vega",
                "prompt": "Taskforce-mediated turn (current week).",
                "summary": "Harness and summarizer usage.",
                "repo": "al-exe/EnderAI",
                "branch": "demo/consumed",
                "anchor_slug": consumed_anchor,
                "consumed": [{"model_id": model_id, "input_tokens": tokens, "usd": usd}],
            }
        )
    for model_id, tokens, usd in _CONSUMED_BY_MODEL_PREV_7D:
        specs.append(
            {
                "days_ago": 10,
                "hour": 18,
                "specialist_slug": "vega",
                "prompt": "Taskforce-mediated turn (prior week).",
                "summary": "Prior-window harness usage.",
                "repo": "al-exe/EnderAI",
                "branch": "demo/consumed-prev",
                "anchor_slug": consumed_anchor,
                "consumed": [{"model_id": model_id, "input_tokens": tokens, "usd": usd}],
            }
        )

    for index, invocation in enumerate(ALEX_DEMO_INVOCATIONS):
        if invocation["days_ago"] <= 14:
            continue
        specs.append(
            {
                "days_ago": invocation["days_ago"],
                "hour": 10 + (index % 6),
                "specialist_slug": invocation["specialist_slug"],
                "prompt": invocation["prompt"],
                "summary": invocation["summary"],
                "repo": invocation["repo"],
                "branch": invocation["branch"],
                "consultations": [
                    {
                        "slug": slug,
                        "avoided_tokens": max(4000, invocation["tokens"] // len(invocation["documents"])),
                    }
                    for slug in invocation["documents"]
                ],
                "cache_tokens": int(invocation["tokens"] * 0.25),
                "summary_only_tokens": int(invocation["tokens"] * 0.45),
                "reuse_tokens": int(invocation["tokens"] * 0.1) if index % 2 == 0 else 0,
                "begin_reused": index % 3 == 0,
                "begin_created": index in {4, 9},
            }
        )
    return specs


def _delete_existing_seeded_metrics(session: Session, user: User) -> None:
    events = session.exec(
        select(MetricsEvent)
        .where(MetricsEvent.user_id == user.id)
        .where(MetricsEvent.is_demo.is_(True))  # type: ignore[union-attr]
        .where(MetricsEvent.payload["seeded"].astext == "true")  # type: ignore[index]
    ).all()
    for event in events:
        session.delete(event)
    session.flush()


def seed_demo_metrics_for_user(session: Session, user: User) -> MetricsSeedResult:
    """Seed demo metrics_event rows tuned for the TF-198 dashboard targets."""

    seed_agents(session, user)
    session.flush()
    _delete_existing_seeded_metrics(session, user)

    docs_by_slug = _document_by_slug(session, user)
    session_specs = _build_metrics_session_specs()
    events_created = 0

    def _add(event: MetricsEvent) -> None:
        nonlocal events_created
        session.add(event)
        events_created += 1

    for index, spec in enumerate(session_specs):
        session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"tf-198-{user.id}-{index}"))
        base_occurred_at = _event_dt(spec["days_ago"], spec.get("hour", 10))
        model_id = MODEL_ID
        consultations: list[dict[str, Any]] = list(spec.get("consultations") or [])
        anchor_slug = spec.get("anchor_slug")
        if not anchor_slug and consultations:
            anchor_slug = consultations[0]["slug"]
        anchor_doc = docs_by_slug.get(anchor_slug) if anchor_slug else None
        if anchor_doc is None and consultations:
            continue
        if anchor_doc is None and not spec.get("consumed"):
            continue

        net_saved_tokens = sum(
            int(item.get("avoided_tokens") or 0) for item in consultations
        )
        base_payload: dict[str, Any] = {
            "seeded": True,
            "source": "tf-198-demo-agent-seed",
            "specialist_slug": spec["specialist_slug"],
            "session_id": session_id,
            "prompt": spec["prompt"],
            "summary": spec["summary"],
            "repo": spec["repo"],
            "branch": spec["branch"],
            "agent_client": "codex",
            "outcome": "completed",
            "documents_consulted_count": len(consultations),
            "net_saved_tokens": net_saved_tokens,
        }

        for doc_idx, consult in enumerate(consultations):
            document = docs_by_slug.get(consult["slug"])
            if document is None:
                continue
            avoided_tokens = int(consult["avoided_tokens"])
            doc_occurred_at = base_occurred_at + timedelta(minutes=5 * doc_idx)
            _add(
                MetricsEvent(
                    occurred_at=doc_occurred_at,
                    user_id=user.id,
                    organization_id=user.organization_id,
                    document_id=document.id,
                    kind=METRICS_EVENT_DOCUMENT_CONSULTED,
                    model_id=model_id,
                    input_tokens=avoided_tokens,
                    output_tokens=0,
                    usd_amount=_usd_for_tokens(model_id, input_tokens=avoided_tokens),
                    is_demo=True,
                    payload={
                        **base_payload,
                        "net_saved_tokens": avoided_tokens,
                    },
                )
            )

        savings_anchor = anchor_doc
        if savings_anchor is not None:
            cache_tokens = int(spec.get("cache_tokens") or 0)
            if cache_tokens > 0:
                _add(
                    MetricsEvent(
                        occurred_at=base_occurred_at + timedelta(minutes=20),
                        user_id=user.id,
                        organization_id=user.organization_id,
                        document_id=savings_anchor.id,
                        kind=METRICS_EVENT_TOKENS_SAVED_CACHE,
                        model_id=model_id,
                        input_tokens=cache_tokens,
                        cache_read_tokens=cache_tokens,
                        output_tokens=0,
                        usd_amount=_usd_for_tokens(model_id, input_tokens=cache_tokens),
                        is_demo=True,
                        payload=base_payload,
                    )
                )
            summary_only_tokens = int(spec.get("summary_only_tokens") or 0)
            if summary_only_tokens > 0:
                _add(
                    MetricsEvent(
                        occurred_at=base_occurred_at + timedelta(minutes=22),
                        user_id=user.id,
                        organization_id=user.organization_id,
                        document_id=savings_anchor.id,
                        kind=METRICS_EVENT_TOKENS_SAVED_SUMMARY_ONLY,
                        model_id=model_id,
                        input_tokens=summary_only_tokens,
                        output_tokens=0,
                        usd_amount=_usd_for_tokens(
                            model_id, input_tokens=summary_only_tokens
                        ),
                        is_demo=True,
                        payload={
                            **base_payload,
                            "details_tokens": summary_only_tokens + 1500,
                        },
                    )
                )
            reuse_tokens = int(spec.get("reuse_tokens") or 0)
            if reuse_tokens > 0:
                _add(
                    MetricsEvent(
                        occurred_at=base_occurred_at + timedelta(minutes=24),
                        user_id=user.id,
                        organization_id=user.organization_id,
                        document_id=savings_anchor.id,
                        kind=METRICS_EVENT_TOKENS_SAVED_REUSE,
                        model_id=model_id,
                        input_tokens=reuse_tokens,
                        output_tokens=0,
                        usd_amount=_usd_for_tokens(model_id, input_tokens=reuse_tokens),
                        is_demo=True,
                        payload=base_payload,
                    )
                )

        if spec.get("begin_reused") and anchor_doc is not None:
            _add(
                MetricsEvent(
                    occurred_at=base_occurred_at + timedelta(minutes=26),
                    user_id=user.id,
                    organization_id=user.organization_id,
                    document_id=anchor_doc.id,
                    kind=METRICS_EVENT_DOCUMENT_REUSED,
                    model_id=model_id,
                    input_tokens=0,
                    output_tokens=0,
                    usd_amount=None,
                    is_demo=True,
                    payload=base_payload,
                )
            )
        if spec.get("begin_created") and anchor_doc is not None:
            _add(
                MetricsEvent(
                    occurred_at=base_occurred_at + timedelta(minutes=28),
                    user_id=user.id,
                    organization_id=user.organization_id,
                    document_id=anchor_doc.id,
                    kind=METRICS_EVENT_DOCUMENT_CREATED,
                    model_id=model_id,
                    input_tokens=0,
                    output_tokens=0,
                    usd_amount=None,
                    is_demo=True,
                    payload=base_payload,
                )
            )

        for consumed_idx, consumed in enumerate(spec.get("consumed") or []):
            consumed_model = consumed["model_id"]
            consumed_tokens = int(consumed["input_tokens"])
            consumed_usd = consumed.get("usd")
            if consumed_usd is None:
                consumed_usd = _usd_for_tokens(
                    consumed_model, input_tokens=consumed_tokens
                )
            doc_id = anchor_doc.id if anchor_doc is not None else None
            _add(
                MetricsEvent(
                    occurred_at=base_occurred_at + timedelta(minutes=30 + consumed_idx),
                    user_id=user.id,
                    organization_id=user.organization_id,
                    document_id=doc_id,
                    kind=METRICS_EVENT_TOKENS_CONSUMED,
                    model_id=consumed_model,
                    input_tokens=consumed_tokens,
                    output_tokens=0,
                    usd_amount=consumed_usd,
                    is_demo=True,
                    payload=base_payload,
                )
            )

    return MetricsSeedResult(
        sessions_created=len(session_specs),
        events_created=events_created,
    )


def seed_demo_metrics_for_alex(
    session: Session, *, email: str = "alexlee4190@gmail.com"
) -> MetricsSeedResult:
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        raise ValueError(f"User {email} not found")
    return seed_demo_metrics_for_user(session, user)
