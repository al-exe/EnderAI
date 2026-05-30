# Taskforce Demo Handoff — Testing Story, Agents/Specialists, Seed Data, and Updated Demo Beats

Last updated: 2026-05-24

This is a copy-pasteable product/implementation brief for Claude Code. It covers:

1. Modifications to the Stripe demo testing story so it stays credible.
2. The new **Agents** tab and what needs to be built on frontend/backend.
3. Seed data for five specialists, linked documents, fake invocations, and demo knowledge.
4. Updated demo beats for maximum visual clarity.

Product principle:

> **Documents are memory. Agents are reusable expertise. Metrics prove the expertise paid off.**

---

# 1. Testing story credibility for the Stripe demo

## Request

Modify the demo testing story so a viewer does not ask: "If you already had a prior Stripe double-charge incident and Taskforce docs about it, why did the test not already catch this issue?"

## Answer

The current story has a credibility gap if the seed doc says the team added a replay test after the prior incident, while the demo shows a failing replay test for what appears to be the same bug.

Make the demo bug a **new regression/variant in the plan-upgrade path**, not the exact same bug the old test should already have caught.

Use this story:

```text
We had a prior Stripe double-charge incident and captured the architectural decision:
inbound webhook dedupe must happen at the route boundary before fulfillment.

The old follow-up added baseline replay coverage, but it did not cover this newer
plan-upgrade fulfillment path / dispatch-order regression.

The demo branch recreates a realistic regression: the WAL helper exists, but this
route calls it after dispatch, so duplicate webhook retries still re-run fulfillment.

Taskforce finds the prior incident and decision. Jensen, the Billing Reliability
Specialist, brings in the relevant docs. Claude Code uses that context to add or
repair the targeted plan-upgrade replay regression test and move the WAL check
before dispatch.
```

Do **not** say:

```text
Tests did not exist.
```

Say:

```text
Baseline webhook replay coverage existed, but it did not cover this newer
plan-upgrade fulfillment path or the dispatch-order regression.
```

That is believable in real engineering: teams often have generic replay tests, but miss a specific event type, side effect, or newly-added route path.

## Required changes

### Rename the demo test

Replace:

```text
tests/api/routes/test_billing.py::test_webhook_replay_is_noop
```

with:

```text
tests/api/routes/test_billing.py::test_plan_upgrade_webhook_retry_short_circuits_before_dispatch
```

Alternative acceptable names:

```text
test_subscription_upgrade_replay_does_not_refire_fulfillment
test_plan_upgrade_webhook_retry_does_not_double_fulfill
test_customer_subscription_updated_replay_is_deduped_before_dispatch
```

Best choice:

```text
test_plan_upgrade_webhook_retry_short_circuits_before_dispatch
```

Why: it communicates the architectural bug — dedupe must happen before dispatch.

### Update the seeded incident doc

Change language like:

```text
Followup: added the WAL table (this doc) + replay test in
tests/api/routes/test_billing.py::test_webhook_replay_is_noop
```

to:

```text
Followup: added the WAL table (this doc) + baseline webhook replay
coverage for duplicate delivery. That coverage verified duplicate
events returned 200 and did not create a second WAL row, but it did
not assert every downstream fulfillment side effect for newer
plan-upgrade paths.
```

Or, if we want a concrete old test:

```text
Followup: added the WAL table (this doc) + baseline replay coverage in
tests/api/routes/test_billing.py::test_webhook_duplicate_delivery_returns_200.
That test covered duplicate delivery at the webhook boundary, but did not
cover the newer customer.subscription.updated plan-upgrade fulfillment path.
```

### Demo branch test behavior

Pre-fix:

```bash
pytest tests/api/routes/test_billing.py::test_plan_upgrade_webhook_retry_short_circuits_before_dispatch -q
# F
```

Failure reason:

```text
The second POST re-runs the plan-upgrade fulfillment side effect because
record_stripe_event_or_skip() is called after _dispatch_event().
```

Post-fix:

```bash
pytest tests/api/routes/test_billing.py::test_plan_upgrade_webhook_retry_short_circuits_before_dispatch -q
# .
# 1 passed
```

Recommended test semantics:

```text
Given a customer.subscription.updated / plan-upgrade webhook event
When the same Stripe event is delivered twice
Then the route should call record_stripe_event_or_skip before dispatch
And the second delivery should return 200 without calling the fulfillment path again
And only one fulfillment side effect should be observed
```

Implementation shape:

```python
async def test_plan_upgrade_webhook_retry_short_circuits_before_dispatch(...):
    # Arrange: build a Stripe customer.subscription.updated event for a plan upgrade.
    # Arrange: patch/mock the plan-upgrade fulfillment function or observe a test-side side effect.
    # Act: POST the same signed webhook payload twice.
    # Assert: first POST processes normally.
    # Assert: second POST returns 200/deduped.
    # Assert: fulfillment function/side effect ran exactly once.
```

Key assertion:

```python
assert fulfill_plan_upgrade.call_count == 1
```

or equivalent domain-side assertion:

```python
assert len(created_upgrade_records) == 1
assert len(created_invoices_or_entitlements) == 1
```

### Keep the code fix small

Expected Claude reasoning:

```text
The old incident doc says webhook dedupe belongs at the route boundary.
The current code has the right helper, but it is called after fulfillment.
That means duplicate delivery still re-runs the plan-upgrade side effect.

I’m going to move record_stripe_event_or_skip() before _dispatch_event()
and add or repair a targeted regression test for the plan-upgrade replay path.
```

Expected diff shape:

```diff
 @router.post("/stripe/webhook", response_model=Message)
 async def receive_stripe_webhook(...):
     event = verify_webhook_signature(payload, signature_header)
+
+    # Dedup at the route boundary, before any fulfillment runs.
+    if not await record_stripe_event_or_skip(session, event):
+        log.info(
+            "stripe.webhook.dedup_hit event_id=%s is_test_mode=%s",
+            event.id, not event.livemode,
+        )
+        return Message(message="Stripe webhook deduped")
+
     await _dispatch_event(event, session)
-    await record_stripe_event_or_skip(session, event)
     return Message(message="Stripe webhook processed")
```

### Update Beat 6 narration

Replace:

```text
The replay test passes now. The dedup happens at the route boundary before fulfillment.
```

With:

```text
The targeted plan-upgrade replay regression test passes now. The prior
incident already taught us the invariant: Stripe webhook dedupe belongs
at the route boundary before fulfillment. This branch had regressed that
ordering for the upgrade path, and the test now locks it down.
```

## Acceptance criteria

```text
1. Seeded incident doc no longer claims the exact same failing demo test already existed.
2. Old context is framed as "baseline replay coverage + architectural invariant."
3. Demo branch contains:
   test_plan_upgrade_webhook_retry_short_circuits_before_dispatch
4. Pre-fix: the test fails because duplicate delivery re-runs plan-upgrade fulfillment.
5. Post-fix: the test passes after moving record_stripe_event_or_skip()
   before _dispatch_event().
6. Demo narration explicitly says this is a new regression/variant in the
   plan-upgrade path, informed by a prior related incident.
```

---

# 2. New Agents tab / Specialist profiles

## Request

Design the new **Agents** tab. This page should act like an AI command center: a grid of reusable specialist profiles generated from Taskforce context and domain knowledge. For the demo, no automatic specialist creation is needed. Seed specialists manually.

The upgraded demo story:

```text
User asks Claude Code to fix the Stripe double-spend bug.

Taskforce says:
"Based on this ask, Jensen — Billing Reliability Specialist — is the best fit."

Jensen is linked to a specialist page.

Then Jensen brings in the relevant docs:
- Stripe webhook idempotency strategy
- Debugging Stripe webhook delivery flakes

Claude Code uses that context and continues the normal fix flow.
```

## Product model

Keep the sidebar label:

```text
Agents
```

But inside the page, each item is a **specialist**:

```text
Jensen
Billing Reliability Specialist
```

Concept:

```text
Agents are AI specialists built from your team’s documents, decisions,
and past requests. They route the right context into Claude Code, Cursor,
Codex, or other coding agents.
```

A specialist is not an autonomous worker. It is a reusable context and instruction profile.

Use:

```text
Taskforce routed this request to Jensen, your Billing Reliability Specialist.
Jensen is bringing in the most relevant prior knowledge for Claude Code.
```

Avoid:

```text
Jensen is taking over.
Jensen fixed the bug.
Jensen is coding now.
```

Use:

```text
Jensen supplied the specialist context.
Claude Code applied the fix.
```

## Frontend UX

### Sidebar

Add or activate:

```text
Agents
/v2/agents
```

Page header:

```text
Agents
AI specialists built from your documents, decisions, and past requests.
```

Subcopy:

```text
Taskforce routes each coding task to the right specialist, then brings the
specialist’s linked knowledge into your agent session.
```

### `/v2/agents` grid page

Each card:

```text
Jensen
Billing Reliability Specialist

Stripe webhooks · subscriptions · double charges

17 invocations
9 linked docs
42k tokens saved
Last used today

[View specialist]
```

Recommended card fields:

```text
name
role
short_description
domain_tags
linked_docs_count
invocations_count
tokens_saved
last_invoked_at
status
avatar / initials
```

Visual style:

```text
2–3 cards per row on desktop
1 card per row on mobile
Soft shadows / bordered cards
Clear CTA: "View specialist"
Small status pill: Active
```

### `/v2/agents/:slug` detail page

Example:

```text
/v2/agents/jensen
```

Sections:

```text
1. Overview
2. When this specialist is used
3. Instructions
4. Linked knowledge
5. Recent invocations
6. Metrics
```

Suggested layout:

```text
Top hero:
- Name
- Specialist role
- Description
- Status
- Last used
- Tokens saved

Left/main column:
- Instructions
- Linked knowledge
- Recent invocations

Right/sidebar:
- Stats
- Domain tags
- Routing signals
- Last updated
```

## Backend schema

Minimum viable models:

```python
class AgentSpecialist(SQLModel, table=True):
    __tablename__ = "agent_specialist"

    id: uuid.UUID
    owner_id: uuid.UUID | None
    organization_id: uuid.UUID | None

    slug: str
    name: str
    role: str
    short_description: str
    description: str

    status: str  # active | draft | archived
    visibility: str  # private | organization | demo

    domain_tags: list[str]  # JSON
    routing_triggers: list[str]  # JSON
    negative_triggers: list[str]  # JSON
    instructions: list[str]  # JSON

    created_from: str  # seeded | manual | generated
    is_demo: bool

    invocations_count: int
    linked_docs_count: int
    tokens_saved: int

    last_invoked_at: datetime | None
    created_at: datetime
    updated_at: datetime
```

```python
class AgentSpecialistDocumentLink(SQLModel, table=True):
    __tablename__ = "agent_specialist_document_link"

    id: uuid.UUID
    specialist_id: uuid.UUID
    document_id: uuid.UUID

    reason: str | None
    weight: float | None
    is_pinned: bool
    created_at: datetime
```

```python
class AgentSpecialistInvocation(SQLModel, table=True):
    __tablename__ = "agent_specialist_invocation"

    id: uuid.UUID
    specialist_id: uuid.UUID
    session_id: uuid.UUID | None
    user_id: uuid.UUID | None

    prompt: str
    repo: str | None
    branch: str | None
    agent_client: str | None  # claude_code | cursor | codex | other

    confidence: float | None
    outcome: str | None  # completed | skipped | failed | demo
    summary: str | None

    documents_consulted: list[uuid.UUID]  # JSON or join table
    tokens_saved: int
    usd_saved: Decimal | None

    is_demo: bool
    created_at: datetime
```

A join table is preferred over JSON for linked docs because linked knowledge should resolve to real V2 documents, respect ACL, support clickable links, and survive document title changes.

## Backend API

Routes:

```text
GET /api/v1/v2/agents
GET /api/v1/v2/agents/{slug}
POST /api/v1/v2/agents/route
POST /api/v1/v2/agents/{slug}/invocations
```

### `GET /api/v1/v2/agents`

Response:

```json
{
  "items": [
    {
      "id": "uuid",
      "slug": "jensen",
      "name": "Jensen",
      "role": "Billing Reliability Specialist",
      "short_description": "Stripe webhooks, subscriptions, and double-charge prevention.",
      "domain_tags": ["Stripe", "Billing", "Webhooks", "Reliability"],
      "status": "active",
      "linked_docs_count": 9,
      "invocations_count": 17,
      "tokens_saved": 42000,
      "last_invoked_at": "2026-05-24T12:00:00Z"
    }
  ]
}
```

### `GET /api/v1/v2/agents/{slug}`

Response shape:

```json
{
  "id": "uuid",
  "slug": "jensen",
  "name": "Jensen",
  "role": "Billing Reliability Specialist",
  "description": "Helps debug Stripe billing, subscription upgrades, webhook retries, idempotency, duplicate invoices, and customer double-charge incidents.",
  "domain_tags": ["Stripe", "Billing", "Webhooks", "Reliability"],
  "routing_triggers": ["stripe", "webhook", "subscription", "plan upgrade", "double charge"],
  "negative_triggers": ["pricing page copy", "frontend billing UI", "non-stripe payment provider"],
  "instructions": [
    "Check inbound webhook idempotency before changing fulfillment logic.",
    "Prefer route-boundary WAL dedupe for Stripe retries.",
    "Verify test/live mode separation using event.livemode.",
    "Add or update replay regression tests for billing bugs."
  ],
  "linked_knowledge": [
    {
      "document_id": "uuid",
      "title": "Stripe webhook idempotency strategy",
      "description": "Decision record for route-boundary WAL dedupe.",
      "anchor_id": "decision-wal-table",
      "href": "/v2/library/<uuid>#decision-wal-table",
      "reason": "Pinned decision record"
    }
  ],
  "recent_invocations": [
    {
      "id": "uuid",
      "prompt": "Stripe is double-charging some users on plan upgrades...",
      "summary": "Fixed webhook replay ordering regression in demo branch.",
      "session_id": "uuid",
      "repo": "taskforce-claude",
      "branch": "demo/stripe-double-charge",
      "documents_consulted_count": 2,
      "tokens_saved": 28432,
      "created_at": "2026-05-24T12:00:00Z"
    }
  ],
  "stats": {
    "invocations_count": 17,
    "linked_docs_count": 9,
    "tokens_saved": 42000,
    "usd_saved": "0.63"
  }
}
```

### `POST /api/v1/v2/agents/route`

Request:

```json
{
  "prompt": "Stripe is double-charging some users on plan upgrades...",
  "cwd": "/Users/alex/dev/taskforce-claude",
  "files": ["app/api/routes/billing.py", "app/core/stripe_billing.py"],
  "git_branch": "demo/stripe-double-charge"
}
```

Response:

```json
{
  "specialist": {
    "slug": "jensen",
    "name": "Jensen",
    "role": "Billing Reliability Specialist",
    "confidence": 0.91,
    "href": "/v2/agents/jensen"
  },
  "reasons": [
    "Strong match on Stripe, webhook retries, plan upgrades, and double-charge history.",
    "Jensen has 17 prior billing reliability invocations.",
    "Jensen is linked to Stripe webhook idempotency and billing incident knowledge."
  ],
  "linked_documents": [
    {
      "title": "Stripe webhook idempotency strategy",
      "document_id": "uuid",
      "anchor_id": "incident-2026-04-11",
      "confidence": 0.84,
      "href": "/v2/library/<uuid>#incident-2026-04-11",
      "preview": [
        "## Incident — 2026-04-11 double-charge",
        "30 customers on Pro upgrades got charged twice over a 90-minute",
        "window. Root cause: Stripe had an outage in us-west-2..."
      ]
    }
  ]
}
```

## MVP routing logic

No LLM router needed for demo. Use deterministic scoring:

```text
specialist_score =
  trigger_overlap * 0.45
  + linked_document_match_score * 0.35
  + recency / invocation boost * 0.10
  + file/path overlap * 0.10
```

For Jensen, triggers:

```text
stripe
billing
webhook
subscription
plan upgrade
double charge
duplicate invoice
idempotency
customer.subscription.updated
invoice.payment_succeeded
```

## `/tf` output integration

Change from:

```text
✓ Found 2 related documents in Taskforce
```

to:

```text
✓ Routed to Jensen — Billing Reliability Specialist
```

Then:

```text
Jensen is bringing in the most relevant knowledge:
```

Target output:

```text
🔎 Checking Taskforce for the right specialist…

✓ Routed to Jensen — Billing Reliability Specialist
   Confidence: high (0.91)
   [→ Open Jensen](https://www.taskforce.tools/v2/agents/jensen)

Why Jensen:
- Strong match on Stripe, webhook retries, plan upgrades, and double-charge history
- Jensen has handled 17 prior billing reliability requests
- Jensen is linked to Stripe webhook idempotency and billing incident knowledge

Jensen is bringing in the most relevant knowledge:

1. Stripe webhook idempotency strategy — confidence: high (0.84)
   [→ Open at incident-2026-04-11](https://www.taskforce.tools/v2/library/<uuid-a>#incident-2026-04-11)

   > ## Incident — 2026-04-11 double-charge
   > 30 customers on Pro upgrades got charged twice over a 90-minute
   > window. Root cause: Stripe had an outage in us-west-2, retried…

2. Debugging Stripe webhook delivery flakes — confidence: high (0.72)
   [→ Open at repro-with-stripe-cli](https://www.taskforce.tools/v2/library/<uuid-b>#repro-with-stripe-cli)

   > ## Reproducing webhook flakes
   > stripe events list --limit 10
   > stripe events resend evt_1OabcD2eZvKYlo2C0X8YzABC
```

## Frontend components

Recommended components:

```text
AgentsPage
AgentCard
AgentDetailPage
AgentHero
AgentInstructions
AgentLinkedKnowledge
AgentInvocations
AgentStatsCard
AgentRoutingSignals
```

API client methods:

```typescript
getAgents(): Promise<AgentSummary[]>
getAgent(slug: string): Promise<AgentDetail>
routeAgent(request: AgentRouteRequest): Promise<AgentRouteResponse>
```

## Completion update

After the session finishes:

```text
Recording this session…
✓ Jensen — added invocation
✓ Stripe webhook idempotency strategy — added Referenced by entry
✓ Debugging Stripe webhook delivery flakes — added Referenced by entry
```

Backend action:

```text
Create AgentSpecialistInvocation
Increment specialist.invocations_count
Increment specialist.tokens_saved by session net_saved_tokens
Set specialist.last_invoked_at = now
Optionally link consulted documents if not already linked
```

Avoid saying Jensen “learned” unless we actually mutate the specialist profile.

Better wording:

```text
Jensen recorded this invocation.
```

## Acceptance criteria

```text
1. Sidebar has an Agents tab pointing to /v2/agents.
2. /v2/agents shows a polished grid of seeded specialist cards.
3. Grid includes Jensen — Billing Reliability Specialist.
4. Clicking Jensen opens /v2/agents/jensen.
5. Jensen page shows description, instructions, linked knowledge, invocations, and stats.
6. Jensen linked knowledge includes the two Stripe demo docs.
7. /tf output links to Jensen's page.
8. /tf output first explains why Jensen was selected.
9. /tf output then shows which documents Jensen is bringing in.
10. Document links still deep-link to V2 library anchors.
11. At session end, the task can be recorded as a Jensen invocation.
12. No automatic specialist creation is required.
```


---

# 3. Seed data for first five specialists + demo documents

## Request

Create seed data for the first five specialists with varying subfields of engineering work. Link them all to documents and context. Create demo documents and fake data so the Agents tab and specialist detail pages look credible when clicked into.

No automatic specialist creation is needed for this demo. Everything can be seeded.

## Answer

Seed five specialists:

```text
Jensen — Billing Reliability Specialist
Mira — Search & Retrieval Specialist
Orin — Agent Infrastructure Specialist
Vega — Product Metrics Specialist
Nia — Knowledge Operations Specialist
```

They map to five visibly different engineering domains:

```text
Billing / payments
Search / retrieval / embeddings
Agent runtime / MCP / hooks
Metrics / ROI / pricing
Knowledge capture / documents / anchors
```

The seeded Agents tab should feel like a populated command center, not a Stripe-only prop.

## Seeded specialists overview

```yaml
specialists:
  - slug: jensen
    name: Jensen
    role: Billing Reliability Specialist
    short_description: Stripe webhooks, subscriptions, idempotency, and double-charge prevention.
    domain_tags: ["Stripe", "Billing", "Webhooks", "Reliability"]
    invocations_count: 17
    linked_docs_count: 9
    tokens_saved: 42000
    usd_saved: "0.63"
    last_invoked_at: "2026-05-24T16:12:00Z"

  - slug: mira
    name: Mira
    role: Search & Retrieval Specialist
    short_description: Embeddings, pgvector, indexing, ranking, citations, and search quality.
    domain_tags: ["Search", "Embeddings", "pgvector", "Retrieval"]
    invocations_count: 11
    linked_docs_count: 8
    tokens_saved: 36500
    usd_saved: "0.55"
    last_invoked_at: "2026-05-22T20:40:00Z"

  - slug: orin
    name: Orin
    role: Agent Infrastructure Specialist
    short_description: MCP bridge, Claude Code hooks, agent credentials, and session lifecycle.
    domain_tags: ["MCP", "Claude Code", "Hooks", "Agent Runtime"]
    invocations_count: 14
    linked_docs_count: 10
    tokens_saved: 51800
    usd_saved: "0.78"
    last_invoked_at: "2026-05-23T18:05:00Z"

  - slug: vega
    name: Vega
    role: Product Metrics Specialist
    short_description: Token savings, pricing snapshots, ROI dashboards, and metrics rollups.
    domain_tags: ["Metrics", "ROI", "Pricing", "Dashboards"]
    invocations_count: 9
    linked_docs_count: 7
    tokens_saved: 28400
    usd_saved: "0.43"
    last_invoked_at: "2026-05-21T15:22:00Z"

  - slug: nia
    name: Nia
    role: Knowledge Operations Specialist
    short_description: Document structure, evidence anchors, referenced-by updates, and reusable decisions.
    domain_tags: ["Documents", "Knowledge", "Anchors", "Summaries"]
    invocations_count: 19
    linked_docs_count: 13
    tokens_saved: 60200
    usd_saved: "0.90"
    last_invoked_at: "2026-05-24T14:30:00Z"
```

## Specialist detail seed data

### Jensen

```yaml
slug: jensen
name: Jensen
role: Billing Reliability Specialist
status: active
created_from: seeded
visibility: demo
description: |
  Helps debug Stripe billing, subscription upgrades, webhook retries,
  idempotency, duplicate invoices, and customer double-charge incidents.

when_to_use:
  - Stripe webhook failures
  - Plan upgrade fulfillment bugs
  - Duplicate invoices or double charges
  - Subscription state drift
  - Billing incident followups

when_not_to_use:
  - Pricing page copy
  - General frontend billing UI
  - Non-Stripe payment providers
  - Account settings UI bugs

routing_triggers:
  - stripe
  - billing
  - webhook
  - subscription
  - plan upgrade
  - double charge
  - duplicate invoice
  - idempotency
  - customer.subscription.updated
  - invoice.payment_succeeded

negative_triggers:
  - pricing page copy
  - frontend billing layout
  - non-stripe payment provider

instructions:
  - Check inbound webhook idempotency before changing fulfillment logic.
  - Prefer route-boundary WAL dedupe for Stripe retries.
  - Verify test/live mode separation using event.livemode.
  - Do not move dedupe into individual fulfillment handlers unless the prior decision record has been superseded.
  - Add or update replay regression tests for billing bugs.
```

Linked knowledge:

```yaml
linked_knowledge:
  - slug: stripe-webhook-idempotency-strategy
    anchor_id: decision-wal-table
    reason: Pinned decision record for route-boundary webhook WAL dedupe.
    weight: 1.0
  - slug: debugging-stripe-webhook-flakes
    anchor_id: repro-with-stripe-cli
    reason: Operational replay and duplicate-delivery playbook.
    weight: 0.95
  - slug: stripe-plan-upgrade-regression-coverage
    anchor_id: targeted-regression-test
    reason: Test strategy for plan-upgrade replay regressions.
    weight: 0.85
```

Recent invocations:

```yaml
recent_invocations:
  - prompt: "Stripe is double-charging some users on plan upgrades — looks like webhook retries are getting fulfilled twice. Can you fix it?"
    summary: "Routed to prior webhook idempotency decision and fixed WAL ordering for the plan-upgrade path."
    repo: taskforce-claude
    branch: demo/stripe-double-charge
    agent_client: claude_code
    documents_consulted_count: 2
    tokens_saved: 28432
    outcome: completed
    created_at: "2026-05-24T16:12:00Z"
  - prompt: "Investigate why test-mode Stripe replays are skipping live fulfillment in staging."
    summary: "Used the test/live mode gotcha doc to verify event.livemode scoping in the WAL."
    repo: taskforce-claude
    branch: billing/test-mode-replay
    agent_client: claude_code
    documents_consulted_count: 3
    tokens_saved: 9100
    outcome: completed
    created_at: "2026-04-25T19:44:00Z"
  - prompt: "Customers are seeing two invoices after upgrading from Free to Pro."
    summary: "Linked duplicate invoice investigation to webhook retry and subscription update handling."
    repo: taskforce-claude
    branch: incident/pro-upgrade-invoices
    agent_client: cursor
    documents_consulted_count: 4
    tokens_saved: 12400
    outcome: completed
    created_at: "2026-04-11T22:10:00Z"
```

### Mira

```yaml
slug: mira
name: Mira
role: Search & Retrieval Specialist
description: |
  Helps debug document search, embedding drift, pgvector retrieval quality,
  citation anchoring, indexing delays, and search answer relevance.
routing_triggers:
  - search
  - retrieval
  - embedding
  - pgvector
  - citation
  - indexing
  - source_item_embedding
  - vector
instructions:
  - Check indexing drift before changing retrieval ranking.
  - Verify ACL joins before assuming an embedding failure.
  - Preserve anchor links when splitting long details sections.
  - Prefer deterministic repro queries before tuning weights.
  - Keep citations inspectable and linked to V2 document anchors.
linked_knowledge:
  - search-indexer-drift-sweep-design#drift-sweep-loop
  - pgvector-acl-retrieval-gotchas#acl-double-enforcement
  - citation-anchor-fanout-playbook#long-section-anchor-fanout
recent_invocations:
  - prompt: "Search is returning an old version of a document after I edited the details section."
    summary: "Identified stale last_indexed_at marker and forced a drift-sweep reindex."
    tokens_saved: 11800
  - prompt: "Citations are linking to the summary instead of the exact details anchor."
    summary: "Used anchor fanout rules to repair citation link generation."
    tokens_saved: 8700
```

### Orin

```yaml
slug: orin
name: Orin
role: Agent Infrastructure Specialist
description: |
  Helps debug the MCP bridge, Claude Code hooks, agent credential validation,
  local setup, session lifecycle, and Taskforce agent runtime behavior.
routing_triggers:
  - mcp
  - claude code
  - hook
  - userpromptsubmit
  - posttooluse
  - stop hook
  - agent credential
  - bearer
  - session_start
  - session_observe
instructions:
  - Confirm whether the user is on hook-driven or MCP-only path first.
  - Check bearer token validation before debugging downstream APIs.
  - Keep hook latency under the synchronous prompt budget.
  - Separate connection setup failures from discovery/scoring failures.
  - Prefer inspectable setup snippets for Claude Code, Cursor, and Codex.
linked_knowledge:
  - claude-code-taskforce-hook-setup#userpromptsubmit-flow
  - hosted-mcp-session-lifecycle#streamable-http-session-map
  - agent-credential-rotation-playbook#revoke-rotate-debug
recent_invocations:
  - prompt: "Claude Code stopped showing the Taskforce preamble after I rotated my token."
    summary: "Traced the issue to an old bearer token in the local hook config."
    tokens_saved: 13600
  - prompt: "Codex can call MCP but session_observe never patches docs."
    summary: "Explained shadow-mode behavior and verified structured payload shortcut."
    tokens_saved: 15400
```

### Vega

```yaml
slug: vega
name: Vega
role: Product Metrics Specialist
description: |
  Helps debug token savings, pricing snapshots, session metrics, ROI dashboards,
  document consulted events, and metrics rollups.
routing_triggers:
  - metrics
  - savings
  - tokens saved
  - avoided rediscovery
  - pricing
  - model_pricing
  - rollup
  - session_savings
  - dashboard
instructions:
  - Explain token savings using rediscovery cost minus consultation cost.
  - Verify model pricing snapshot before comparing USD values.
  - Distinguish session metrics from aggregate dashboard metrics.
  - Keep savings math inspectable and reproducible.
  - Avoid fabricating large ROI numbers; derive them from document structure.
linked_knowledge:
  - taskforce-session-savings-math#rediscovery-minus-consult
  - metrics-event-rollup-architecture#pricing-snapshot-at-write
  - demo-metrics-page-session-filter#session-id-query-param
recent_invocations:
  - prompt: "Why does the metrics page show a different number than the /tf savings line?"
    summary: "Separated session-scoped savings from aggregate metrics and added session_id filter copy."
    tokens_saved: 9400
  - prompt: "Make the demo savings number defensible instead of looking made up."
    summary: "Derived avoided rediscovery from seeded doc structure and pricing snapshot."
    tokens_saved: 11200
```

### Nia

```yaml
slug: nia
name: Nia
role: Knowledge Operations Specialist
description: |
  Helps structure Taskforce documents, evidence anchors, summaries,
  referenced-by updates, reusable decision records, and knowledge hygiene.
routing_triggers:
  - document
  - knowledge
  - anchor
  - evidence
  - referenced by
  - summary
  - decision record
  - reusable context
  - doc patch
instructions:
  - Prefer specific anchor IDs over generic document links.
  - Capture decisions and ruled-out alternatives, not just outcomes.
  - Keep summaries short enough for prompt-time retrieval.
  - Add referenced-by entries after meaningful reuse.
  - Avoid creating duplicate docs when a related active doc should be patched.
linked_knowledge:
  - evidence-anchor-authoring-guide#anchor-naming-rules
  - referenced-by-update-policy#close-the-loop
  - document-reuse-vs-create-playbook#reuse-decision-criteria
recent_invocations:
  - prompt: "The Stripe demo docs feel too generic. Make the seeded content inspectable and believable."
    summary: "Expanded decision records, incident details, CLI verification, and evidence anchors."
    tokens_saved: 14600
  - prompt: "Referenced-by entries are not being appended after a Taskforce session."
    summary: "Clarified close-the-loop policy and patched final observation copy."
    tokens_saved: 12100
```

## Demo documents to seed

Each specialist should have at least 2–3 linked documents that are clickable and credible. Jensen’s Stripe docs are the demo-critical documents and should be the most detailed. The other documents can be shorter but should look real if clicked.

Use whatever existing V2 document seed helper is available. If needed, paste these into a `DEMO_SPECIALIST_DOCS` catalog and hydrate them as V2 documents.

### Jensen document A — `stripe-webhook-idempotency-strategy`

```yaml
slug: stripe-webhook-idempotency-strategy
title: "Stripe webhook idempotency strategy"
description: "How we dedupe Stripe webhook retries so plan upgrades don't double-fulfill. Decision record + WAL table design."
human_summary: |
  Stripe retries webhook delivery on non-2xx responses and can redeliver
  events during service recovery. After the 2026-04-11 Pro upgrade
  double-charge incident, we captured the invariant: inbound Stripe
  events must be deduped at the route boundary before fulfillment.
ai_generated_summary: |
  Inbound Stripe webhooks are deduped via a stripe_webhook_event WAL
  table keyed on event_id and is_test_mode. billing.py checks the WAL
  before dispatching to handlers; duplicates return 200 OK without
  re-running fulfillment. Baseline replay coverage exists, but newer
  event-specific fulfillment paths still need targeted regression tests.
collaborators: ["alex", "codex"]
main_body:
  - text: "Stripe may redeliver webhook events. Inbound handlers must be idempotent at the route boundary."
    evidence_anchor_id: "decision-wal-table"
  - text: "The stripe_webhook_event WAL must be written before fulfillment dispatch, not after."
    evidence_anchor_id: "decision-wal-table"
  - text: "Baseline replay tests cover duplicate delivery, but event-specific side effects need targeted regression coverage."
    evidence_anchor_id: "targeted-regression-test"
  - text: "Test-mode and live-mode events must be scoped separately via event.livemode / is_test_mode."
    evidence_anchor_id: "gotcha-test-vs-live"
details_markdown_sections:
  - anchor_id: "decision-wal-table"
    markdown: |
      ## Decision — WAL table at the route boundary

      **Chose:** dedicated `stripe_webhook_event` WAL table, checked
      in `app/api/routes/billing.py` BEFORE dispatching to any handler.

      **Why:** fulfillment handlers are not uniformly idempotent. Some
      webhook types, such as `customer.subscription.updated`, do not have
      a natural unique side-effect key across all upgrade paths.

      **Ruled out:**
      - In-handler dedupe with `ON CONFLICT DO NOTHING` on fulfillment rows.
      - Redis SETNX with TTL in the payment critical path.
      - Trusting Stripe's `Idempotency-Key` header, which applies to
        outbound Stripe API calls, not inbound webhooks.

      **Files:**
      - `app/api/routes/billing.py`
      - `app/core/stripe_billing.py`
      - `app/models.py`
      - `app/alembic/versions/*stripe_webhook_wal*.py`

  - anchor_id: "incident-2026-04-11"
    markdown: |
      ## Incident — 2026-04-11 double-charge

      30 customers on Pro upgrades got charged twice over a 90-minute
      window. Root cause: Stripe aggressively retried webhook delivery
      during recovery, and our upgrade flow ran twice for the same event.

      **Symptoms:**
      - Duplicate invoices for the same `subscription_id`
      - Sentry spike on `stripe.upgrade.duplicate_invoice`
      - Customer-facing: two charges in the same billing cycle

      **Resolution:**
      - Hotfix: voided duplicate invoices and refunded affected charges
      - Followup: added the WAL table plus baseline webhook replay coverage

      **Important nuance:** the baseline replay test verified duplicate
      delivery at the webhook boundary, but did not assert every newer
      downstream fulfillment side effect. The demo branch regression is a
      specific plan-upgrade ordering bug: the WAL exists, but is called
      after dispatch.

  - anchor_id: "targeted-regression-test"
    markdown: |
      ## Test guidance — plan-upgrade replay regression

      Baseline replay coverage is not enough for billing changes. For
      plan upgrades, the regression test must assert that a duplicate
      `customer.subscription.updated` event does not re-fire fulfillment.

      Preferred test name:

      ```text
      test_plan_upgrade_webhook_retry_short_circuits_before_dispatch
      ```

      The test should:
      1. POST the same signed Stripe plan-upgrade webhook twice.
      2. Assert both responses are successful.
      3. Assert the plan-upgrade fulfillment side effect ran exactly once.
      4. Assert duplicate delivery returns before `_dispatch_event()`.

  - anchor_id: "gotcha-test-vs-live"
    markdown: |
      ## Gotcha — test mode vs live mode events

      Stripe webhooks fire in both live and test mode. We scope WAL rows
      by `(event_id, is_test_mode)` so test-mode replays cannot collide
      with live fulfillment.

      Use `event.livemode` from the payload, not log text or event id
      prefixes, when deciding whether the event is test or live.
```

### Jensen document B — `debugging-stripe-webhook-flakes`

```yaml
slug: debugging-stripe-webhook-flakes
title: "Debugging Stripe webhook delivery flakes"
description: "Playbook for replaying webhooks, reading the WAL, and diagnosing duplicate delivery."
human_summary: |
  Operational playbook for Stripe webhook flakes. Covers replaying events
  with the Stripe CLI, reading stripe_webhook_event, interpreting dedup
  hits, checking test/live mode, and distinguishing duplicate delivery
  from non-idempotent fulfillment.
ai_generated_summary: |
  Use Stripe CLI event replay to reproduce delivery flakes. Check the WAL
  for `(event_id, is_test_mode)`, confirm the route short-circuits before
  dispatch, and inspect event.livemode when logs are ambiguous.
collaborators: ["alex"]
main_body:
  - text: "If Stripe double-fires a webhook, first check whether the WAL short-circuits before fulfillment dispatch."
    evidence_anchor_id: "repro-with-stripe-cli"
  - text: "A dedup hit should return 200 without re-running the fulfillment path."
    evidence_anchor_id: "dedup-hit-log"
  - text: "Test-mode events look similar to live events in logs; check event.livemode."
    evidence_anchor_id: "test-mode-trap"
details_markdown_sections:
  - anchor_id: "repro-with-stripe-cli"
    markdown: |
      ## Reproducing webhook flakes

      ```bash
      stripe events list --limit 10
      stripe events resend evt_1OabcD2eZvKYlo2C0X8YzABC
      heroku logs -t -a enderai-backend | grep stripe.webhook
      ```

      Expected duplicate behavior: the second delivery returns 200 and
      logs a dedup hit before any fulfillment handler runs.

  - anchor_id: "dedup-hit-log"
    markdown: |
      ## Expected duplicate log line

      ```text
      stripe.webhook.dedup_hit event_id=evt_1OabcD2eZvKYlo2C0X8YzABC
        is_test_mode=False processed_at_age_seconds=3.2
      ```

      If the fulfillment log appears after this line on duplicate
      delivery, the route is not short-circuiting correctly.

  - anchor_id: "test-mode-trap"
    markdown: |
      ## Test mode vs live mode

      Always inspect `event.livemode`. Test-mode events can be replayed
      from local machines and should never suppress live fulfillment.
```

### Jensen document C — `stripe-plan-upgrade-regression-coverage`

```yaml
slug: stripe-plan-upgrade-regression-coverage
title: "Plan upgrade webhook regression coverage"
description: "Test strategy for Stripe plan-upgrade side effects under webhook replay."
human_summary: |
  Guide for writing billing replay tests that assert downstream side
  effects, not just successful HTTP responses. Created after we realized
  baseline webhook replay tests can miss event-specific fulfillment paths.
ai_generated_summary: |
  For plan upgrades, duplicate `customer.subscription.updated` delivery
  must not re-run entitlement or invoice side effects. The regression
  test should patch the fulfillment path or assert persisted side effects
  ran exactly once.
collaborators: ["alex", "claude"]
main_body:
  - text: "Billing replay tests should assert fulfillment side effects ran once, not just that the route returned 200."
    evidence_anchor_id: "side-effect-assertion"
  - text: "Plan-upgrade paths are high-risk because subscription updates can trigger entitlement, invoice, and tier changes."
    evidence_anchor_id: "plan-upgrade-risk"
details_markdown_sections:
  - anchor_id: "side-effect-assertion"
    markdown: |
      ## Side-effect assertion

      A passing duplicate replay test should prove the handler did not
      re-run the expensive or customer-visible side effect.

      Acceptable assertions:
      - fulfillment function called once
      - entitlement row written once
      - invoice adjustment created once
      - tier transition recorded once

  - anchor_id: "plan-upgrade-risk"
    markdown: |
      ## Why plan upgrades need targeted coverage

      `customer.subscription.updated` can represent many state changes.
      A generic webhook replay test may pass while a newly-added upgrade
      branch still re-fires fulfillment. Always include a test that uses
      the exact event shape for the upgrade path.
```


## Non-Stripe demo documents

These do not need to be as long as Jensen’s docs, but they should look credible if the demoer clicks around the Agents tab.

```yaml
documents:
  - slug: search-indexer-drift-sweep-design
    title: "Search indexer drift-sweep design"
    specialist: mira
    description: "How the V2 document indexer detects stale embeddings and refreshes source_item_embedding rows."
    human_summary: |
      The search indexer runs as an async task in the FastAPI process. It
      detects documents whose index markers are missing, stale, or on an old
      index version, then rebuilds summary and details chunks for embedding.
    ai_generated_summary: |
      Drift is detected from last_indexed_at, updated_at, and index_version.
      DocumentSource emits one summary chunk plus details-anchor chunks.
    main_body:
      - text: "The drift sweep is the source of truth for deciding when a V2 document needs re-indexing."
        evidence_anchor_id: "drift-sweep-loop"
      - text: "Long details sections fan out into multiple chunks but keep their parent anchor link."
        evidence_anchor_id: "chunking-anchor-contract"
    details_markdown_sections:
      - anchor_id: "drift-sweep-loop"
        markdown: |
          ## Drift sweep loop

          The indexer selects documents where `last_indexed_at` is null,
          older than `updated_at`, or where `index_version` no longer
          matches the current document indexer version.
      - anchor_id: "chunking-anchor-contract"
        markdown: |
          ## Chunking and anchor contract

          Each document emits a synthetic summary chunk plus one or more
          details chunks. If a details section is long, it may fan out into
          `anchor#1`, `anchor#2`, etc., but the UI should still link back
          to the original details anchor.

  - slug: pgvector-acl-retrieval-gotchas
    title: "pgvector retrieval and ACL gotchas"
    specialist: mira
    description: "Why a relevant document can be missing from search results and how to debug ACL-filtered retrieval."
    human_summary: |
      Search retrieval joins embeddings back to V2 documents and applies
      the same ACL filter as document reads. A good embedding hit can
      disappear if ownership, organization, share, or demo flags do not match.
    ai_generated_summary: |
      Debug search misses by checking embedding existence, document ACL,
      organization visibility, explicit shares, and demo isolation.
    main_body:
      - text: "ACL is double-enforced: embeddings carry denormalized access fields, but retrieval also joins back to V2Document."
        evidence_anchor_id: "acl-double-enforcement"
    details_markdown_sections:
      - anchor_id: "acl-double-enforcement"
        markdown: |
          ## ACL double enforcement

          Retrieval filters candidate embeddings, then joins back to
          V2Document and applies document ACL. This means ACL changes take
          effect without re-embedding the document.
      - anchor_id: "demo-isolation"
        markdown: |
          ## Demo isolation

          Demo documents and live user documents should be isolated in both
          document reads and search retrieval.

  - slug: citation-anchor-fanout-playbook
    title: "Citation anchor fanout playbook"
    specialist: mira
    description: "How to preserve inspectable citations when details sections are split into multiple chunks."
    human_summary: |
      Search citations must remain inspectable even when long details
      sections are split for embeddings. Chunks can fan out internally,
      but the user should land on the canonical evidence anchor.
    ai_generated_summary: |
      Preserve source transparency by mapping chunk-level hits back to
      document detail anchors. Avoid sending users to opaque chunk ids.
    main_body:
      - text: "Citation links should land on canonical details anchors, not internal chunk ids."
        evidence_anchor_id: "long-section-anchor-fanout"
    details_markdown_sections:
      - anchor_id: "long-section-anchor-fanout"
        markdown: |
          ## Long-section anchor fanout

          If a details section exceeds the chunk size, the indexer may
          create several embedding chunks. The user-facing citation should
          still point to the parent details anchor.

  - slug: claude-code-taskforce-hook-setup
    title: "Claude Code Taskforce hook setup"
    specialist: orin
    description: "How Claude Code hooks call Taskforce before and after an agent session."
    human_summary: |
      Claude Code can call Taskforce through local hooks. UserPromptSubmit
      runs discovery synchronously before Claude sees the prompt. PostToolUse
      and Stop can send checkpoints and final observations.
    ai_generated_summary: |
      Hook setup depends on a valid agent bearer token, local scripts, and
      endpoint reachability. Keep UserPromptSubmit fast because it is on the
      prompt path.
    main_body:
      - text: "UserPromptSubmit calls /v2/taskforce/discover before Claude sees the prompt."
        evidence_anchor_id: "userpromptsubmit-flow"
      - text: "Stop hook sends the final observation for material sessions."
        evidence_anchor_id: "stop-observe-flow"
    details_markdown_sections:
      - anchor_id: "userpromptsubmit-flow"
        markdown: |
          ## UserPromptSubmit flow

          The hook captures prompt, cwd, recent files, and branch. It calls
          Taskforce discovery with a short timeout and prepends related
          context before Claude Code processes the user's request.
      - anchor_id: "stop-observe-flow"
        markdown: |
          ## Stop observe flow

          At session end, the hook sends a final observation. Material
          sessions can record usage, update documents, and append
          referenced-by entries.

  - slug: hosted-mcp-session-lifecycle
    title: "Hosted MCP session lifecycle"
    specialist: orin
    description: "How the MCP bridge validates agent tokens, binds sessions, and forwards Taskforce tool calls."
    human_summary: |
      The hosted MCP bridge is a protocol adapter. It validates the incoming
      bearer token, binds the backend token to an MCP session, and forwards
      tools through authenticated backend requests.
    ai_generated_summary: |
      MCP sessions are keyed by Mcp-Session-Id and carry a token reference.
      The bridge is not a source of truth; it forwards to FastAPI.
    main_body:
      - text: "The MCP bridge validates agent credentials before forwarding backend calls."
        evidence_anchor_id: "streamable-http-session-map"
    details_markdown_sections:
      - anchor_id: "streamable-http-session-map"
        markdown: |
          ## Streamable HTTP session map

          Each MCP request carries authorization. After validation, the
          server stores transport, server, and token reference under the MCP
          session id so subsequent tool calls can forward with the right bearer.
      - anchor_id: "taskforce-mcp-tools"
        markdown: |
          ## Taskforce MCP tools

          Hookless clients can call `taskforce_session_start`,
          `taskforce_session_observe`, `taskforce_session_log`, and
          `taskforce_discover`.

  - slug: agent-credential-rotation-playbook
    title: "Agent credential rotation playbook"
    specialist: orin
    description: "How to safely rotate, revoke, and debug Taskforce agent credentials."
    human_summary: |
      Agent credentials are backend JWTs bound to a credential id and token
      version. Rotating or revoking invalidates old tokens and may require
      updating local MCP or hook config.
    ai_generated_summary: |
      Debug token failures by checking credential version, revoked_at, local
      config, and whether the token kind is agent_mcp.
    main_body:
      - text: "Revoked or rotated credentials should fail validation even if the JWT has not expired."
        evidence_anchor_id: "revoke-rotate-debug"
    details_markdown_sections:
      - anchor_id: "revoke-rotate-debug"
        markdown: |
          ## Revoke and rotate debugging

          Check:
          - credential exists
          - token version matches
          - revoked_at is null
          - token_kind is `agent_mcp`
          - local hook or MCP config uses the latest token

  - slug: taskforce-session-savings-math
    title: "Taskforce session savings math"
    specialist: vega
    description: "How session-level avoided rediscovery tokens and USD savings are calculated."
    human_summary: |
      Session savings are derived from consulted documents. For each
      document, net saved tokens equal rediscovery_cost_tokens minus the
      summary/context tokens actually read.
    ai_generated_summary: |
      Avoided rediscovery is a structural estimate cached on documents and
      reduced by consultation cost. The demo should show the same number in
      chat and on the session-scoped metrics page.
    main_body:
      - text: "Session savings equal rediscovery cost minus consultation cost for consulted documents."
        evidence_anchor_id: "rediscovery-minus-consult"
    details_markdown_sections:
      - anchor_id: "rediscovery-minus-consult"
        markdown: |
          ## Rediscovery minus consultation

          ```text
          net_saved_tokens = max(0, rediscovery_cost_tokens - consult_token_cost)
          ```
      - anchor_id: "pricing-snapshot"
        markdown: |
          ## Pricing snapshot

          The USD calculation should use the model pricing row that was
          effective when the event was recorded.

  - slug: metrics-event-rollup-architecture
    title: "Metrics event rollup architecture"
    specialist: vega
    description: "Event-sourced metric recording, pricing snapshots, and daily rollups."
    human_summary: |
      Metrics are stored as append-only events. A registry defines public
      metric names, daily rollups materialize aggregates, and composed
      metrics are calculated on read.
    ai_generated_summary: |
      Write raw metric events first, snapshot pricing at write time, and
      roll up by day, user, org, and demo flag.
    main_body:
      - text: "Pricing is snapshotted at write time so historical USD totals remain stable."
        evidence_anchor_id: "pricing-snapshot-at-write"
    details_markdown_sections:
      - anchor_id: "pricing-snapshot-at-write"
        markdown: |
          ## Pricing snapshot at write

          Each metrics event stores a reference to the pricing row used to
          compute USD.
      - anchor_id: "demo-live-isolation"
        markdown: |
          ## Demo and live isolation

          Rollups include `is_demo` in their key so seeded demo activity
          never pollutes live user metrics.

  - slug: demo-metrics-page-session-filter
    title: "Demo metrics page session filter"
    specialist: vega
    description: "How the demo links from a completed Taskforce session into a scoped metrics view."
    human_summary: |
      The demo savings line should link to a metrics page scoped by
      session_id. The page should show documents consulted, estimated
      rediscovery cost, consultation cost, net tokens saved, and USD saved.
    ai_generated_summary: |
      Use `/v2/metrics?session_id=<uuid>` for the video. Show a banner
      that the page is filtered to one session, with a link back to all metrics.
    main_body:
      - text: "The metrics page should make the chat savings number inspectable."
        evidence_anchor_id: "session-id-query-param"
    details_markdown_sections:
      - anchor_id: "session-id-query-param"
        markdown: |
          ## Session id query param

          The video should link to:

          ```text
          /v2/metrics?session_id=<session_id>
          ```

  - slug: evidence-anchor-authoring-guide
    title: "Evidence anchor authoring guide"
    specialist: nia
    description: "How to write Taskforce details sections that agents can cite and users can inspect."
    human_summary: |
      Good Taskforce documents use specific anchors for decisions,
      incidents, gotchas, and verification steps. Agents should link to
      anchors, not just whole documents.
    ai_generated_summary: |
      Use stable, human-readable anchor ids. Keep decision sections separate
      from incident sections and verification steps.
    main_body:
      - text: "Anchor names should be stable and explain what the user will see when clicked."
        evidence_anchor_id: "anchor-naming-rules"
    details_markdown_sections:
      - anchor_id: "anchor-naming-rules"
        markdown: |
          ## Anchor naming rules

          Prefer IDs like:
          - `decision-wal-table`
          - `incident-2026-04-11`
          - `gotcha-test-vs-live`
          - `verifying-the-fix`

  - slug: referenced-by-update-policy
    title: "Referenced-by update policy"
    specialist: nia
    description: "When Taskforce should append usage back to a document after an agent session."
    human_summary: |
      Referenced-by entries close the loop after reuse. They show that a
      document was not just stored but actively helped solve later work.
    ai_generated_summary: |
      Add referenced-by entries after material sessions that consulted a
      doc and used it to make a decision, fix, or test.
    main_body:
      - text: "Referenced-by entries make reuse visible and strengthen future routing signals."
        evidence_anchor_id: "close-the-loop"
    details_markdown_sections:
      - anchor_id: "close-the-loop"
        markdown: |
          ## Close the loop

          After a material session uses a document, append:
          - session title or prompt summary
          - date
          - files touched
          - outcome
          - token savings if available

  - slug: document-reuse-vs-create-playbook
    title: "Document reuse vs create playbook"
    specialist: nia
    description: "How Taskforce decides whether to patch an existing document or create a new one."
    human_summary: |
      Reusing the right document preserves continuity. Creating a new
      document is better when there are conflicting tenants, repos,
      outcomes, or a fundamentally different problem.
    ai_generated_summary: |
      Prefer reuse when title, file, symbol, and intent signals align
      without conflicts. Create a new document when terminal-state, repo,
      tenant, or error-family conflicts fire.
    main_body:
      - text: "Reuse decisions should consider both positive signals and conflicts."
        evidence_anchor_id: "reuse-decision-criteria"
    details_markdown_sections:
      - anchor_id: "reuse-decision-criteria"
        markdown: |
          ## Reuse decision criteria

          Reuse when:
          - same repo
          - same domain
          - overlapping files or symbols
          - no tenant conflict
          - no terminal-state conflict
      - anchor_id: "terminal-state-conflict"
        markdown: |
          ## Terminal-state conflict

          A document with an outcome, finish marker, or resolved incident
          should not be patched by unrelated future work.
```

## Specialist-to-document seed mapping

```yaml
agent_document_links:
  jensen:
    - stripe-webhook-idempotency-strategy#decision-wal-table
    - debugging-stripe-webhook-flakes#repro-with-stripe-cli
    - stripe-plan-upgrade-regression-coverage#targeted-regression-test

  mira:
    - search-indexer-drift-sweep-design#drift-sweep-loop
    - pgvector-acl-retrieval-gotchas#acl-double-enforcement
    - citation-anchor-fanout-playbook#long-section-anchor-fanout

  orin:
    - claude-code-taskforce-hook-setup#userpromptsubmit-flow
    - hosted-mcp-session-lifecycle#streamable-http-session-map
    - agent-credential-rotation-playbook#revoke-rotate-debug

  vega:
    - taskforce-session-savings-math#rediscovery-minus-consult
    - metrics-event-rollup-architecture#pricing-snapshot-at-write
    - demo-metrics-page-session-filter#session-id-query-param

  nia:
    - evidence-anchor-authoring-guide#anchor-naming-rules
    - referenced-by-update-policy#close-the-loop
    - document-reuse-vs-create-playbook#reuse-decision-criteria
```

## Demo seed implementation notes

```text
1. Seed all 15 documents as V2 documents for the demo user or demo org.
2. Seed all 5 specialists.
3. Link specialists to their pinned documents via join table.
4. Seed recent invocations as fake historical rows.
5. For Jensen, make the first or most recent invocation the Stripe demo session.
6. Make /v2/agents show all five specialists.
7. Make /v2/agents/jensen click through to Jensen’s page.
8. Make Jensen’s linked knowledge deep-link to the Stripe docs.
9. Keep demo and live data isolated with is_demo=true.
```

## Seed acceptance criteria

```text
1. Agents grid contains five seeded specialists: Jensen, Mira, Orin, Vega, Nia.
2. Each specialist has a distinct engineering domain.
3. Each detail page has description, routing triggers, instructions,
   linked knowledge, invocations, and stats.
4. Jensen links to the two Stripe demo docs plus the plan-upgrade regression doc.
5. All linked knowledge entries are clickable and resolve to seeded V2 documents.
6. Each seeded doc has at least one useful details anchor.
7. The Stripe docs are rich enough to support the main demo if clicked.
8. The non-Stripe docs are credible enough that the Agents grid feels real.
9. Seed operation is idempotent by slug.
10. No automatic specialist creation is required.
```


---

# 4. Updated demo beats for visual pleasure and understandability

## Request

Update the demo beats to incorporate the Agents tab and Jensen routing story, while preserving the original Stripe fix flow. Maximize visual pleasure and understandability.

The viewer should see:

```text
1. Agents tab with seeded specialists.
2. Jensen, the Billing Reliability Specialist.
3. /tf routes the prompt to Jensen and links to Jensen’s page.
4. Jensen explains which documents he is bringing in.
5. Those documents are linked and inspectable.
6. Claude Code fixes the bug.
7. The targeted test passes.
8. Jensen records the invocation.
9. Metrics shows savings.
```

## Answer

The upgraded demo should have a clearer hierarchy:

```text
Task → Specialist → Knowledge → Fix → Test → Invocation → Metrics
```

Old demo story:

```text
Taskforce found 2 documents and Claude fixed the bug.
```

New demo story:

```text
Taskforce routed the task to the right specialist, the specialist brought in
the right prior knowledge, and Claude Code used that context to fix the bug
correctly.
```

## Target length

Recommended target: 100–120 seconds.

Do not go much beyond two minutes. The Agents tab adds clarity but can also add time. Keep the clicks crisp.

## Beat 0 — Preflight / setup, off camera

Before recording:

```bash
cd ~/dev/taskforce-claude
git checkout demo/stripe-double-charge
export TASKFORCE_HOOKS_DISABLED=1
```

Demo account should have:

```text
5 seeded specialists
15 seeded documents
Jensen linked to Stripe docs
Taskforce skill installed
Claude Code open with desired model/effort
Browser already logged into Taskforce
```

Recommended browser tabs open before recording:

```text
Tab 1: /v2/agents
Tab 2: Claude Code / terminal
Tab 3: optional metrics page or blank
```

## Beat 1 — Agents command center

Screen: browser at `/v2/agents`.

Narration:

```text
This is the Agents tab. Taskforce builds AI specialists from our team’s
documents, decisions, and past requests.
```

Show five cards:

```text
Jensen — Billing Reliability Specialist
Mira — Search & Retrieval Specialist
Orin — Agent Infrastructure Specialist
Vega — Product Metrics Specialist
Nia — Knowledge Operations Specialist
```

Important visual details:

```text
Cards should have names, roles, tags, invocation counts, linked doc counts,
tokens saved, and "View specialist" buttons.
```

Purpose: establish that Agents is a real product surface, not a hidden prompt trick.

Approx time: 6–8 seconds.

## Beat 2 — Click Jensen

Click:

```text
Jensen — Billing Reliability Specialist
```

URL:

```text
/v2/agents/jensen
```

Show:

```text
Description:
Helps debug Stripe billing, subscription upgrades, webhook retries,
idempotency, duplicate invoices, and customer double-charge incidents.

Instructions:
- Check inbound webhook idempotency before changing fulfillment logic.
- Prefer route-boundary WAL dedupe for Stripe retries.
- Verify test/live mode separation using event.livemode.
- Add or update replay regression tests for billing bugs.

Linked knowledge:
- Stripe webhook idempotency strategy
- Debugging Stripe webhook delivery flakes
- Plan upgrade webhook regression coverage

Recent invocations:
- Stripe double-charge demo branch
- Test/live webhook WAL collision
- Subscription upgrade invoice duplication
```

Narration:

```text
For billing work, Taskforce has Jensen. Jensen is not a separate coder;
it is the specialist context profile built from prior billing incidents,
decisions, and fixes.
```

Important: say “specialist context profile” or “specialist,” not “autonomous agent.”

Approx time: 8–10 seconds.

## Beat 3 — Start the Claude Code task

Switch to Claude Code.

User types:

```text
/tf

Stripe is double-charging some users on plan upgrades —
looks like webhook retries are getting fulfilled twice.
Can you fix it?
```

Visual goal: viewer sees a natural engineering request, not a file-path prompt.

Do not include:

```text
The fix is in billing.py.
```

Approx time: 5 seconds.

## Beat 4 — Taskforce routes to Jensen

Taskforce output:

```text
🔎 Checking Taskforce for the right specialist…

✓ Routed to Jensen — Billing Reliability Specialist
   Confidence: high (0.91)
   [→ Open Jensen](https://www.taskforce.tools/v2/agents/jensen)

Why Jensen:
- Strong match on Stripe, webhook retries, plan upgrades, and double-charge history
- Jensen has handled 17 prior billing reliability requests
- Jensen is linked to Stripe webhook idempotency and billing incident knowledge
```

Visual goal: the product now feels like expert routing, not just search.

Optional click: click “Open Jensen” briefly if the demoer wants to prove it is real. Since Jensen was already shown in Beat 2, this click is optional.

Narration:

```text
Taskforce routes the request to Jensen because the ask matches Stripe,
webhook retries, plan upgrades, and prior double-charge work.
```

Approx time: 8–10 seconds.

## Beat 5 — Jensen brings in knowledge

Taskforce output continues:

```text
Jensen is bringing in the most relevant knowledge:

1. Stripe webhook idempotency strategy — confidence: high (0.84)
   [→ Open at incident-2026-04-11](https://www.taskforce.tools/v2/library/<uuid-a>#incident-2026-04-11)

   > ## Incident — 2026-04-11 double-charge
   > 30 customers on Pro upgrades got charged twice over a 90-minute
   > window. Root cause: Stripe retried webhook delivery…

2. Debugging Stripe webhook delivery flakes — confidence: high (0.72)
   [→ Open at repro-with-stripe-cli](https://www.taskforce.tools/v2/library/<uuid-b>#repro-with-stripe-cli)

   > ## Reproducing webhook flakes
   > stripe events list --limit 10
   > stripe events resend evt_1OabcD2eZvKYlo2C0X8YzABC
```

Required click: click the first doc link.

Browser opens:

```text
/v2/library/<uuid-a>#incident-2026-04-11
```

Show:

```text
Incident — 2026-04-11 double-charge
Decision — WAL table at the route boundary
Test guidance — plan-upgrade replay regression
```

Narration:

```text
Jensen is not hiding the source. These are the actual prior decisions and
incident notes being brought into Claude Code.
```

Then switch back to Claude Code.

Approx time: 12–15 seconds.

## Beat 6 — Claude Code identifies the bug

Claude Code response should say something like:

```text
Reading app/api/routes/billing.py and app/core/stripe_billing.py.

The prior decision says Stripe webhook dedupe belongs at the route boundary,
before fulfillment. In this branch, record_stripe_event_or_skip() exists,
but it runs after _dispatch_event(). That means a duplicate retry can still
run the plan-upgrade fulfillment path.

I’m going to move the WAL check before dispatch and make the duplicate path
return before fulfillment.
```

Visual goal: show that Taskforce context changed the reasoning. It is not just “add idempotency somewhere.”

Narration:

```text
The key is not just knowing Stripe retries webhooks. The key is knowing our
team’s prior decision: dedupe at the route boundary before fulfillment.
```

Approx time: 12–18 seconds.

## Beat 7 — Visible code diff

Claude applies the edit. Keep the diff small and screen-friendly.

Expected visual diff:

```diff
 @router.post("/stripe/webhook", response_model=Message)
 async def receive_stripe_webhook(...):
     event = verify_webhook_signature(payload, signature_header)
+
+    # Dedup at the route boundary, before any fulfillment runs. The
+    # _dispatch_event handlers are not individually idempotent — the
+    # WAL is the only thing preventing double-fulfillment.
+    if not await record_stripe_event_or_skip(session, event):
+        log.info(
+            "stripe.webhook.dedup_hit event_id=%s is_test_mode=%s",
+            event.id, not event.livemode,
+        )
+        return Message(message="Stripe webhook deduped")
+
     await _dispatch_event(event, session)
-    await record_stripe_event_or_skip(session, event)
     return Message(message="Stripe webhook processed")
```

Visual goal: a small, obvious, satisfying backend fix.

Approx time: 10–15 seconds.

## Beat 8 — Targeted test passes

Run:

```bash
pytest tests/api/routes/test_billing.py::test_plan_upgrade_webhook_retry_short_circuits_before_dispatch -q
```

Expected:

```text
.                                                                       [100%]
1 passed in 1.42s
```

Claude narration:

```text
The targeted plan-upgrade replay regression test passes now. The prior
incident taught us the invariant: Stripe webhook dedupe belongs at the
route boundary before fulfillment. This branch had regressed that ordering
for the upgrade path, and the test now locks it down.
```

Visual goal: answer “did it really fix something?” without undermining credibility.

Approx time: 5–8 seconds.

## Beat 9 — Jensen records the invocation

Taskforce output:

```text
Recording this session…

✓ Jensen — added invocation
✓ Stripe webhook idempotency strategy — added Referenced by entry
✓ Debugging Stripe webhook delivery flakes — added Referenced by entry
```

Optional browser click: go back to `/v2/agents/jensen`.

Show Jensen page now has a recent invocation:

```text
Stripe double-charge demo branch
2 docs consulted · 28.4k tokens saved · Completed just now
```

Narration:

```text
Taskforce records the session back to Jensen, so the next billing issue starts
with even more context.
```

Important wording: use “records the invocation,” not “Jensen learned,” unless instructions or linked docs actually mutate.

Approx time: 6–8 seconds.

## Beat 10 — Metrics money shot

Taskforce output:

```text
Done.

[Taskforce saved you 28.4k tokens on Opus 4.7 xhigh effort (~$0.38 USD) →](https://www.taskforce.tools/v2/metrics?session_id=<uuid>)
```

Click metrics link.

Metrics page should show:

```text
Showing savings for this session

Specialist: Jensen — Billing Reliability Specialist
Documents consulted: 2
Estimated rediscovery cost: 31,500 tokens
Actual consultation cost: 3,068 tokens
Net tokens saved: 28,432
USD saved: $0.38–$0.43
```

Narration:

```text
And because Taskforce knows which specialist and documents were reused, it
can show the avoided rediscovery cost for this exact session.
```

Approx time: 8–10 seconds.

## Final beat order summary

```text
1. Agents grid: five specialists
2. Jensen page: Billing Reliability Specialist
3. Claude Code prompt
4. Taskforce routes to Jensen
5. Jensen brings in linked docs
6. Click doc anchor to inspect prior incident/decision
7. Claude identifies route-boundary WAL ordering bug
8. Claude applies small diff
9. Targeted plan-upgrade replay test passes
10. Jensen records invocation
11. Metrics page shows session savings
```

## What to cut if the video runs long

Cut in this order:

```text
1. Optional second click back to Jensen after invocation
2. Full doc page click; keep only the link preview
3. Agents grid linger time
4. Metrics details; keep only the savings line
```

Do **not** cut:

```text
Taskforce routes to Jensen
Jensen brings in docs
Code diff
Test pass
```

Those are the core proof points.

## Updated `/tf` output script

Use this as the target output for the demo:

```text
🔎 Checking Taskforce for the right specialist…

✓ Routed to Jensen — Billing Reliability Specialist
   Confidence: high (0.91)
   [→ Open Jensen](https://www.taskforce.tools/v2/agents/jensen)

Why Jensen:
- Strong match on Stripe, webhook retries, plan upgrades, and double-charge history
- Jensen has handled 17 prior billing reliability requests
- Jensen is linked to Stripe webhook idempotency and billing incident knowledge

Jensen is bringing in the most relevant knowledge:

1. Stripe webhook idempotency strategy — confidence: high (0.84)
   [→ Open at incident-2026-04-11](https://www.taskforce.tools/v2/library/<uuid-a>#incident-2026-04-11)

   > ## Incident — 2026-04-11 double-charge
   > 30 customers on Pro upgrades got charged twice over a 90-minute
   > window. Root cause: Stripe retried webhook delivery…

2. Debugging Stripe webhook delivery flakes — confidence: high (0.72)
   [→ Open at repro-with-stripe-cli](https://www.taskforce.tools/v2/library/<uuid-b>#repro-with-stripe-cli)

   > ## Reproducing webhook flakes
   > stripe events list --limit 10
   > stripe events resend evt_1OabcD2eZvKYlo2C0X8YzABC

Reading the relevant code now…
```

## Updated completion output script

```text
The targeted plan-upgrade replay regression test passes.

Recording this session…

✓ Jensen — added invocation
✓ Stripe webhook idempotency strategy — added Referenced by entry
✓ Debugging Stripe webhook delivery flakes — added Referenced by entry

Done.

[Taskforce saved you 28.4k tokens on Opus 4.7 xhigh effort (~$0.38 USD) →](https://www.taskforce.tools/v2/metrics?session_id=<uuid>)
```

## Key product-language rules

Use:

```text
Routed to Jensen
Billing Reliability Specialist
Jensen is bringing in knowledge
Jensen supplied the specialist context
Claude Code applied the fix
Jensen recorded this invocation
```

Avoid:

```text
Jensen took over
Jensen fixed the bug
Jensen is coding
Jensen learned this automatically
```

Unless we have actually implemented autonomous execution or automatic profile mutation.

## Visual design recommendations for the Agents tab

### Agents grid

Use cards with:

```text
Large name
Role subtitle
3–4 domain chips
Short description
Stats row
Last used
View specialist button
```

Example:

```text
Jensen
Billing Reliability Specialist

Stripe webhooks, subscriptions, idempotency, and double-charge prevention.

Stripe  Billing  Webhooks  Reliability

17 invocations · 9 linked docs · 42k tokens saved
Last used today

[View specialist]
```

### Jensen detail page

Top hero:

```text
Jensen
Billing Reliability Specialist
Active

Helps debug Stripe billing, subscription upgrades, webhook retries,
idempotency, duplicate invoices, and customer double-charge incidents.
```

Right stats rail:

```text
17 invocations
9 linked docs
42k tokens saved
Last used today
```

Main sections:

```text
Instructions
Linked knowledge
Recent invocations
Routing signals
```

Linked knowledge cards should have:

```text
Document title
Short description
Anchor link
Reason linked
```

Recent invocation cards should have:

```text
Prompt summary
Repo / branch
Docs consulted
Tokens saved
Outcome
Date
```

## Demo acceptance criteria

```text
1. Viewer sees Agents tab before coding begins.
2. Viewer sees Jensen’s specialist page before coding begins.
3. /tf output links to Jensen.
4. /tf output explains why Jensen was selected.
5. /tf output then lists the documents Jensen is bringing in.
6. Document links are clickable and deep-link to useful anchors.
7. Claude’s reasoning references the prior decision: route-boundary dedupe.
8. Code diff is small and visible.
9. Test name is specific to the plan-upgrade regression.
10. Completion records the invocation back to Jensen.
11. Metrics link shows session savings.
```

## Final demo positioning

The demo should land this message:

```text
Taskforce does not just search documents.

It builds reusable AI specialists from your team’s prior work,
routes new requests to the right specialist,
shows the exact knowledge being brought in,
and records the outcome so the specialist gets more useful over time.
```

---

# Implementation checklist for Claude Code

```text
Testing story
- Rename demo regression test to test_plan_upgrade_webhook_retry_short_circuits_before_dispatch.
- Update seeded Stripe incident doc to mention baseline replay coverage, not the exact demo test.
- Ensure pre-fix branch fails targeted test and post-fix branch passes.

Agents backend
- Add AgentSpecialist model.
- Add AgentSpecialistDocumentLink model.
- Add AgentSpecialistInvocation model.
- Add GET /api/v1/v2/agents.
- Add GET /api/v1/v2/agents/{slug}.
- Add POST /api/v1/v2/agents/route.
- Optional: add POST /api/v1/v2/agents/{slug}/invocations.
- Seed 5 specialists and 15 docs idempotently.
- Keep demo data isolated with is_demo=true.

Agents frontend
- Add /v2/agents route.
- Add /v2/agents/:slug route.
- Build AgentsPage grid.
- Build AgentDetailPage.
- Link Jensen card to /v2/agents/jensen.
- Link agent knowledge cards to /v2/library/<doc_id>#<anchor_id>.
- Add loading, error, and empty states.

Taskforce demo output
- Update /tf output to route to Jensen first.
- Then show Jensen-selected documents with deep links and previews.
- Completion output records Jensen invocation and referenced-by entries.

Demo polish
- Open Agents tab first.
- Click Jensen.
- Run /tf.
- Click doc anchor.
- Show code diff.
- Show targeted test pass.
- Show Jensen invocation recorded.
- Show metrics savings.
```
