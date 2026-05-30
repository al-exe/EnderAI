# Taskforce demo video — task, prompt, seed plan

Last updated: 2026-05-24

Companion to: [taskforce-tf-skill-demo-plan.md](taskforce-tf-skill-demo-plan.md) (the build plan) and Jira epic [TF-183](https://alexlee4190.atlassian.net/browse/TF-183).

This doc picks the demo task, writes the exact prompt, specs the two seed docs in full, and walks the filming beat-by-beat. Hand this to whoever implements [TF-191](https://alexlee4190.atlassian.net/browse/TF-191) (demo seed) and records the video.

## 0. Production decisions (locked 2026-05-24)

| # | Decision | Implication |
|---|---|---|
| Recording target | `demo/stripe-double-charge` branch (NOT main) — prod code has no idempotency machinery at all; we pre-build a half-broken implementation so the fix is a clean ~6-line move | New ticket [TF-193](https://alexlee4190.atlassian.net/browse/TF-193) preps the branch |
| Recording style | Live single-take with real Claude run | Skill output must be deterministic (beats 1-4, 7-8); beat 5 is Claude's natural response — system prompt + seed lock-in have to make the high-confidence pull reliable |
| Anchor injection | Visible 3-line preview in chat, full content into Claude's context | Skill renders a `>` quote block of the first 3 lines of each matched anchor's markdown before Claude responds |
| Model display | Hardcoded `Opus 4.7 xhigh` + pinned `pricing_model_id=claude-opus-4-7` | TF-190 (auto-detect) becomes post-demo polish, no longer demo-blocking |

## 1. The task we're demoing — Stripe webhook double-fulfillment

**Why this task:**

| Criterion | Why Stripe webhook idempotency fits |
|---|---|
| Engineering task | Backend bug fix touching real auth/payment code |
| Medium niche | Not "implement quicksort" (generic) and not "fix our CRDT merge" (too niche) — every B2B SaaS engineer has dealt with this |
| Understandable to a large audience | "Stripe sometimes retries webhooks, you have to dedupe them" — one sentence and the viewer gets it |
| Convincing reuse story | The seeded context (idempotency key strategy, prior incident, the WAL table design, the gotcha about test vs live events) is exactly the kind of decision history that's painful to rebuild from a cold start — perfect Taskforce content |
| Real in the codebase | `app/core/stripe_billing.py` and `app/api/routes/billing.py` already exist; the fix lands in actual product code, not a contrived sandbox |
| Visible diff | The fix is ~15 lines in one file, fits on screen |

**Why NOT some alternatives we considered:**
- *Search indexer race condition* — real bug per `app/core/search/indexing.py`'s own comment, but "Postgres advisory lock in an asyncio sweep loop" needs too much setup to land for non-backend viewers
- *Pagination off-by-one* — too generic, viewer thinks "ok and?"
- *Date/timezone bug* — relatable but the fix tends to be one-line, less satisfying on screen
- *Original "signal_creation page" task* — too codebase-specific; viewer can't picture what "signal_creation" is

## 2. The exact prompt the user types

```text
Stripe is double-charging some users on plan upgrades — looks like webhook retries are getting fulfilled twice. Can you fix it?
```

Why this exact wording:

- **"Stripe"** + **"webhook"** + **"double"** — high overlap with seed doc titles and bodies → scorer fires `high` band on both docs.
- **"plan upgrades"** — domain-specific enough to feel real, but doesn't tell the agent the fix.
- **"can you fix it"** — open-ended ask. Forces the agent to use the seeded context to know *where* to fix it.
- No file paths in the prompt — proves the doc viewer link's `matched_anchor_id` is doing real work.
- Cwd will resolve to the backend repo (whatever the user `cd`'d into before launching Claude Code), so the file-substring scorer signal also fires once the docs mention the right files.

**Don't include** "the fix is in billing.py" — that would let the agent succeed without reading the docs.

## 3. The two seed documents — full content

These get seeded into the demo account's library by [TF-191](https://alexlee4190.atlassian.net/browse/TF-191). Whoever implements that ticket should paste these into `app/core/v2_documents.py`'s seed catalog verbatim.

### Doc A — `stripe-webhook-idempotency-strategy`

```yaml
title: "Stripe webhook idempotency strategy"
description: "How we dedupe Stripe webhook retries so plan upgrades don't double-fulfill. Decision record + the WAL table design."
human_summary: |
  Stripe retries webhook delivery on any non-2xx response for up to 3 days,
  and even on 2xx it can re-deliver an event during outages. Our handler in
  billing.py was idempotent at the Stripe-side (using event.id as the
  idempotency key on outbound calls), but the inbound side trusted that
  each event would be delivered once. After the 2026-04-11 incident where
  ~30 customers got double-charged on Pro upgrades, we added an explicit
  WAL table that records every event.id we've processed and short-circuits
  duplicates at the route boundary.
ai_generated_summary: |
  Inbound Stripe webhooks deduped via a stripe_webhook_event WAL table
  keyed on (event_id, processed_at). billing.py route checks the WAL
  before dispatching to handlers; duplicates return 200 OK without
  re-running the fulfillment path. Test-mode events use a separate
  WAL row so dev/prod don't collide.
collaborators: ["alex", "codex"]

main_body:
  - segments:
      - text: "Stripe will redeliver any webhook that doesn't 2xx within 8 seconds, and may redeliver a 2xx'd event during their outages. Inbound handlers must be idempotent."
        evidence_anchor_id: "decision-wal-table"
  - segments:
      - text: "We use a dedicated stripe_webhook_event WAL table keyed on event_id, written at the START of webhook handling before any fulfillment runs."
        evidence_anchor_id: "decision-wal-table"
  - segments:
      - text: "Test-mode and live-mode events share the same Stripe-side namespace but are scoped separately in our WAL via the is_test_mode column — added after the 2026-04-25 dev/prod collision."
        evidence_anchor_id: "gotcha-test-vs-live"
  - segments:
      - text: "The fulfillment path itself is NOT idempotent — the WAL is the only thing preventing double-billing. Don't move dedupe logic into the handlers."
        evidence_anchor_id: "decision-wal-table"

details_file_name: "stripe-webhook-idempotency.details.md"
details_markdown_sections:
  - anchor_id: "decision-wal-table"
    markdown: |
      ## Decision — WAL table at the route boundary

      **Chose:** dedicated `stripe_webhook_event` WAL table, checked
      in `app/api/routes/billing.py` BEFORE dispatching to any handler.

      **Ruled out:**
      - In-handler dedupe with `ON CONFLICT DO NOTHING` on the
        fulfillment table — works for `invoice.payment_succeeded` but not
        for `customer.subscription.updated` where there's no natural
        unique key on the side effect.
      - Redis SETNX with TTL — adds an external dependency to the
        critical path of payment processing. Hard pass.
      - Trusting Stripe's `Idempotency-Key` header — that's for OUTBOUND
        requests we make to Stripe, not inbound webhooks from them.

      **Files:**
      - `app/api/routes/billing.py:142` — webhook entry point, calls
        `record_stripe_event_or_skip()` first
      - `app/core/stripe_billing.py:88` — `record_stripe_event_or_skip()`
        helper, returns `True` if this is the first time we've seen it
      - `app/models.py:1234` — `StripeWebhookEvent` SQLModel
      - `app/alembic/versions/b7c9e2a4f1d3_add_stripe_webhook_wal.py` — migration

  - anchor_id: "incident-2026-04-11"
    markdown: |
      ## Incident — 2026-04-11 double-charge

      30 customers on Pro upgrades got charged twice over a 90-minute
      window. Root cause: Stripe had an outage in `us-west-2`, retried
      webhook delivery aggressively when their side recovered, and our
      handler ran the upgrade flow twice for every event.

      **Symptoms:**
      - Sentry alert spike on `stripe.upgrade.duplicate_invoice`
      - Stripe dashboard showed 2× invoices for the same `subscription_id`
      - Customer-facing: two charges in the same Stripe billing cycle

      **Resolution:**
      - Hotfix: manually voided dup invoices, refunded charges
      - Followup: added the WAL table (this doc) + replay test in
        `tests/api/routes/test_billing.py::test_webhook_replay_is_noop`

  - anchor_id: "gotcha-test-vs-live"
    markdown: |
      ## Gotcha — test mode vs live mode events

      Stripe's `event.id` namespace is global per account, but in *test
      mode* it's a separate sandbox. We initially deduped on `event.id`
      alone, which meant a dev replaying a test-mode webhook with the
      same event.id as a real prod event would short-circuit fulfillment
      on prod.

      **Fix:** added `is_test_mode` column to the WAL, primary key is
      now `(event_id, is_test_mode)`. The `event.livemode` field tells
      us which one — see `_normalize_event_payload()` in
      `app/core/stripe_billing.py:115`.

  - anchor_id: "verifying-the-fix"
    markdown: |
      ## How to verify

      ```bash
      # Replay an arbitrary event from the Stripe dashboard via CLI:
      stripe events resend evt_1OabcD2eZvKYlo2C0X8YzABC

      # Then check the WAL:
      psql $DATABASE_URL -c \
        "SELECT event_id, is_test_mode, processed_at, status
         FROM stripe_webhook_event
         WHERE event_id = 'evt_1OabcD2eZvKYlo2C0X8YzABC';"
      ```

      Expected: exactly one row, status='ok'. A second `stripe events
      resend` of the same id should return 200 from our endpoint
      without writing a new row.
```

### Doc B — `debugging-stripe-webhook-flakes`

```yaml
title: "Debugging Stripe webhook delivery flakes"
description: "Playbook for when webhooks act weird: replay commands, the dedup window, the test-mode trap."
human_summary: |
  Operational playbook companion to the idempotency design doc.
  Covers: how to replay events with the Stripe CLI, how to read the
  stripe_webhook_event WAL, the 5-minute dedup window we chose, and
  the test-mode trap that bit us in April.
ai_generated_summary: |
  Use 'stripe events resend' to replay; check stripe_webhook_event
  WAL for duplicates. Dedup is keyed on (event_id, is_test_mode).
  5-minute processed_at window prevents thrash from same-second
  retries. Common failures: missing STRIPE_WEBHOOK_SECRET in env,
  test-mode events leaking into prod from a bad ENV vat, signature
  verification failing on payload re-serialization.
collaborators: ["alex"]

main_body:
  - segments:
      - text: "If Stripe is double-firing a webhook, first check the stripe_webhook_event WAL — if there's only one row for that event_id, the dedup ISN'T the problem; you have a separate bug."
        evidence_anchor_id: "repro-with-stripe-cli"
  - segments:
      - text: "The 5-minute processed_at window in the WAL is what prevents thrash when Stripe retries the same event within seconds during recovery from their outages."
        evidence_anchor_id: "decision-5min-window"
  - segments:
      - text: "Test-mode events look identical to live events in Sentry logs — always check event.livemode in the payload, not just the event.id."
        evidence_anchor_id: "test-mode-trap"

details_file_name: "debugging-stripe-webhooks.details.md"
details_markdown_sections:
  - anchor_id: "repro-with-stripe-cli"
    markdown: |
      ## Reproducing webhook flakes

      ```bash
      # 1. Get a recent event to replay
      stripe events list --limit 10

      # 2. Resend it
      stripe events resend evt_1OabcD2eZvKYlo2C0X8YzABC

      # 3. Tail backend logs
      heroku logs -t -a enderai-backend | grep stripe.webhook
      ```

      Expected log line on a duplicate:

      ```
      stripe.webhook.dedup_hit event_id=evt_1OabcD2eZvKYlo2C0X8YzABC
        is_test_mode=False processed_at_age_seconds=3.2
      ```

  - anchor_id: "decision-5min-window"
    markdown: |
      ## Decision — 5-minute dedup window

      The `record_stripe_event_or_skip()` helper rejects an event as a
      duplicate if a row exists for `(event_id, is_test_mode)` with
      `processed_at` within the last 5 minutes. Beyond 5 minutes we
      allow re-processing — that's our escape hatch for the case where
      the WAL got committed but the handler crashed before completing
      fulfillment.

      **Chose 5 min because:**
      - Stripe's own retry backoff is < 5 min for the first 3 retries
      - Long enough that any legitimate "same event again" is a retry,
        not a different state change
      - Short enough that operator-driven `stripe events resend` for
        debugging works on a re-run after a fix

  - anchor_id: "test-mode-trap"
    markdown: |
      ## Test mode vs live mode

      Stripe webhooks fire in both modes. In Sentry they look identical
      unless you're squinting at the `livemode` field. The April 2026
      incident root cause was a dev resending a test-mode event whose
      event_id happened to match a real prod event — the WAL had been
      keyed on event_id alone and the prod fulfillment short-circuited.

      Always:
      - Filter Sentry by `tags.stripe_livemode:true` for prod-only view
      - Use `--api-key sk_test_...` explicitly on the CLI when replaying
        test events
      - Check `event.livemode` in handler logs, never just `event.id`
```

**Why these two docs and not one big one:** the scoring engine bands score per-document; having two `high`-band matches makes a stronger demo than one. They also model the realistic split (design decision doc + operational playbook) that's natural for any real codebase.

## 4. Filming script — beat by beat

Approximate timings assume normal terminal scrollback speed.

### Beat 1 — Setup (off-camera)

Before recording:
- `cd ~/dev/taskforce-claude` (cwd that resolves to the backend repo for file-substring signals)
- `export TASKFORCE_HOOKS_DISABLED=1` (so /tf is the only path, not the silent hook)
- Demo account has the two seed docs from §3 above + has been used recently (so recency signal contributes)
- Claude Code launched with Opus 4.7, xhigh effort

### Beat 2 — User types the prompt *(~5s on screen)*

User types in Claude Code:

```text
> /tf

Stripe is double-charging some users on plan upgrades —
looks like webhook retries are getting fulfilled twice.
Can you fix it?
```

### Beat 3 — Claude announces + shows payload *(~5s)*

Claude responds (this is the skill prompt's job). Every line starting from Taskforce is prefixed with a signature emoji so the viewer instantly sees where TF is adding work — never confused with Claude's own narration.

```text
🔎 Checking Taskforce for related prior work…

📨 Sending to Taskforce:
{
  "prompt": "Stripe is double-charging some users on plan upgrades — looks like webhook retries are getting fulfilled twice. Can you fix it?",
  "cwd": "/Users/alex/dev/taskforce-claude",
  "files": ["app/api/routes/billing.py", "app/core/stripe_billing.py"],
  "git_branch": "main"
}
```

*(files extracted from open editor tabs / recently modified — TF-176 hook already does this; the skill reuses the same extraction)*

### Beat 4 — Matches returned, deep-linked + previews *(~12s on screen so viewer can read titles + previews)*

```text
✓ Found 2 related documents in Taskforce:

1. **Stripe webhook idempotency strategy** — confidence: high (0.84)
   [→ Open at incident-2026-04-11](https://www.taskforce.tools/v2/library/<uuid-a>#incident-2026-04-11)
   Matched on: title overlap "Stripe webhook", file overlap on
   billing.py + stripe_billing.py, body mentions "double-charge".

   > ## Incident — 2026-04-11 double-charge
   > 30 customers on Pro upgrades got charged twice over a 90-minute
   > window. Root cause: Stripe had an outage in us-west-2, retried…

2. **Debugging Stripe webhook delivery flakes** — confidence: high (0.72)
   [→ Open at repro-with-stripe-cli](https://www.taskforce.tools/v2/library/<uuid-b>#repro-with-stripe-cli)
   Matched on: title overlap "webhook", body overlap on "retry" +
   "duplicate".

   > ## Reproducing webhook flakes
   > ```bash
   > # 1. Get a recent event to replay
   > stripe events list --limit 10
```

The 3-line preview blocks are rendered by the skill from `GET /v2/documents/{id}` — first 3 non-blank lines of the matched anchor's markdown, with a `>` quote prefix. Full anchor content is passed to Claude's context invisibly; the preview is purely for the viewer.

The director should pause here and **click one of the links** on camera, jumping to `www.taskforce.tools/v2/library/<uuid>#incident-2026-04-11`. The doc viewer loads scrolled to that section — proves the deep-link is real, viewer sees the seeded content is substantive.

Then back to Claude Code.

### Beat 5 — Auto-injection + the work *(~25s, mostly streaming)*

This beat is Claude's natural response, not skill output. The director can re-take if Claude goes off-script. Expected shape (won't be word-for-word):

```text
Reading: app/api/routes/billing.py — receive_stripe_webhook handler
Reading: app/core/stripe_billing.py — record_stripe_event_or_skip helper

Based on the prior decision in "Stripe webhook idempotency strategy"
(decision-wal-table), the dedup check has to short-circuit BEFORE
fulfillment runs. Looking at billing.py… the WAL write happens AFTER
_dispatch_event, so every retry re-fulfills before the WAL catches
up. That's the bug.

The fix is to move the WAL call ahead of dispatch and early-return on
duplicate.
```

Then Claude makes the edit. The actual diff on the demo branch (small + visible):

```diff
@@ app/api/routes/billing.py @@
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

6-line change (3 added, 1 moved, the early return). Clean on camera.

### Beat 6 — Tests + verification *(~5s)*

The demo branch ships with this test (added by TF-193). On the branch pre-fix it FAILS (second POST re-fulfills); after the fix it PASSES:

```text
$ pytest tests/api/routes/test_billing.py::test_webhook_replay_is_noop -q
.                                                                       [100%]
1 passed in 1.42s
```

Claude narrates briefly:

```text
The replay test passes now. The dedup happens at the route boundary
before fulfillment, matching the design from "Stripe webhook
idempotency strategy."
```

### Beat 7 — "Referenced by" gets appended *(~3s)*

Brief mention in chat:

```text
Recording this session in the referenced docs…
✓ Stripe webhook idempotency strategy — added Referenced by entry
✓ Debugging Stripe webhook delivery flakes — added Referenced by entry
```

If the viewer clicks back to the doc tab from beat 4, they see a new entry under "Referenced by:" — proof Taskforce closed the loop.

### Beat 8 — Savings line *(~5s, with link click)*

The skill hardcodes the model display (`Opus 4.7 xhigh`) and passes `pricing_model_id=claude-opus-4-7` to `/session-savings`, so the number is reproducible across takes regardless of what model is actually running. (TF-190 auto-detect is post-demo polish.)

```text
Done.

[Taskforce saved you 28.4k tokens on Opus 4.7 xhigh
effort (~$0.38 USD) →](https://www.taskforce.tools/v2/metrics?session_id=<uuid>)
```

The director clicks the link. Browser opens the metrics page, scoped to this session via TF-192's `?session_id=<uuid>` filter, showing:
- Documents consulted: 2
- Net tokens saved: 28,432
- USD saved: $0.38
- Estimated rediscovery cost (what you would have spent re-deriving): 31,500 tokens
- Actual consultation cost: 3,068 tokens (the summary tokens read)

End of recording.

## 5. The savings math (so the number is defensible)

We don't want a made-up number. Here's how to land at ~$0.38:

| Component | Tokens | Notes |
|---|---|---|
| Doc A — `rediscovery_cost_tokens` | 18,500 | Computed by `compute_rediscovery_cost()`: 4 details sections × 3000 + 12 file refs × 2500 + 3 commands × 1500 + 4 decisions × 500 + 4 summary points × 1000 = 18,500 (capped at 50k) |
| Doc B — `rediscovery_cost_tokens` | 13,000 | 3 details × 3000 + 6 files × 2500 + 2 commands × 1500 (some overlap with A) |
| Doc A — `consult_token_cost` (summary read) | 1,768 | summary chars / 4 |
| Doc B — `consult_token_cost` | 1,300 | summary chars / 4 |
| **net_saved_tokens** | **28,432** | (18,500 − 1,768) + (13,000 − 1,300) |
| **usd_saved @ Opus 4.7 input rate ($15/MTok)** | **$0.43** | 28,432 × 15 / 1,000,000 |

If the on-screen number says "~$0.38" or "~$0.42" it's within rounding. The point is: the math is real, derived from doc structure the viewer can inspect via the deep links. Don't fabricate.

If we want the number to feel BIGGER on screen, we can:
- Add a 3rd details section to each doc (each section ≈ 3k more rediscovery tokens)
- Show "in this session" alongside a "this week" aggregate that's a multiple higher

## 6. The metrics page link

The savings line links to:

```
https://www.taskforce.tools/v2/metrics?session_id=<the-session-id>
```

**What's needed to make the link land usefully:**

The metrics page (`/v2/metrics`) currently shows user-aggregate metrics, not per-session. For the demo to land cleanly, either:

- **Option A (recommended for the video):** add a `?session_id=<uuid>` query param that filters the metrics view to events from that session. This is a small frontend addition — the `GET /v2/taskforce/session-savings` endpoint (TF-187) already returns the right shape. Add it as a banner above the existing dashboard: "Showing savings for session <id> — view all".
- **Option B (cheaper):** link to the unfiltered `/v2/metrics` page. The savings number in the chat is the session-specific number; the dashboard shows the user's aggregate. Caption in the video can paper over the gap.

**Recommend (A) — it's ~30 min of FE work**, makes the demo land much harder. File a follow-up Jira ticket (or extend [TF-187](https://alexlee4190.atlassian.net/browse/TF-187) scope).

## 7. Why this demo will be convincing

Three reasons, in order of importance:

1. **The seeded content is substantive.** A viewer who clicks through to the doc viewer sees real engineering content — a real incident postmortem, a real "ruled out X because Y" decision record, a real CLI playbook. Not lorem ipsum. The Taskforce value prop ("we capture decisions so the next person doesn't redo the investigation") is *directly visible*.

2. **The agent's edit is non-obvious without the context.** The bug is "the WAL check is at the wrong layer." Without the prior design doc telling the agent that the WAL is the only thing preventing double-fulfillment and must be at the route boundary, the agent would plausibly add idempotency to the *handler* — which would fix the symptom but break the architectural invariant. The doc context makes the agent get it right the first time.

3. **The savings number is derived, not asserted.** Viewers who pause the video and add up the rediscovery costs themselves will get the same number. Engineers smell BS demos; this one has a defensible derivation.

## 8. Filming gotchas / cheat sheet

| Risk | Mitigation |
|---|---|
| The skill takes 4+ seconds to respond and the viewer loses attention | Pre-warm the backend before recording (a no-op API call) so the first `/tf` doesn't cold-start |
| Hook fires alongside `/tf` and produces a duplicate preamble | Confirm `TASKFORCE_HOOKS_DISABLED=1` is set in the recording shell |
| Anchor link goes to a 404 because matched_anchor_id is missing | TF-184 must be merged + deployed before filming; verify with a manual `curl` to `/discover` |
| Doc viewer loads but doesn't auto-scroll to the anchor | TF-185 must be merged + deployed; test by manually pasting `https://www.taskforce.tools/v2/library/<id>#decision-wal-table` and confirming the scroll |
| Savings number doesn't match the on-screen math | Run the math against the actual seeded doc tokens before recording; tweak markdown length if needed |
| Stripe code in the repo doesn't actually have the bug we're "fixing" | RESOLVED: TF-193 pre-builds the `demo/stripe-double-charge` branch with the WAL-after-fulfillment bug. Director must check out that branch (NOT main) before recording. |
| Beat 5 is Claude's free-form response — wording will vary between takes | Pre-warm with 2-3 dry runs to confirm the system prompt + seed combo reliably produces a sensible diff. If Claude wanders, re-take. Temperature 0 if available. |
| Recording goes long, viewer attention drops | Target 75–90s total. Cut beat 6 (test run) if running long. |

## 9. Action items spawned by this plan

| Owner | Action | Maps to |
|---|---|---|
| TF-193 implementer | Build the `demo/stripe-double-charge` branch with WAL-after-fulfillment bug + repro test | [TF-193](https://alexlee4190.atlassian.net/browse/TF-193) |
| TF-191 implementer | Use §3 doc content verbatim when seeding the demo catalog. Re-tune any line-number references after TF-193 ships. | [TF-191](https://alexlee4190.atlassian.net/browse/TF-191) |
| TF-188 (skill) implementer | Use §4 beat-by-beat output as the skill's expected behavior spec. Render 3-line `>` previews after each match. Hardcode model display + pass `pricing_model_id=claude-opus-4-7`. | [TF-188](https://alexlee4190.atlassian.net/browse/TF-188) |
| TF-192 implementer | `?session_id=<uuid>` filter on `/v2/metrics` so the savings link lands on a session-scoped view | [TF-192](https://alexlee4190.atlassian.net/browse/TF-192) |
| TF-190 (model detect) | Deferred — post-demo polish; not on the demo-critical path | [TF-190](https://alexlee4190.atlassian.net/browse/TF-190) |
| Director | Check out `demo/stripe-double-charge` branch (NOT main) before recording. Verify `TASKFORCE_HOOKS_DISABLED=1` + cwd. Run §5 math before publishing. | filming day |

## 10. Codex swarm prompt (5 least-central tickets)

These five are small, well-spec'd, and either have workarounds or are post-demo polish — perfect for Codex to pick up cold while the harder/more central tickets (TF-184, TF-187, TF-188, TF-191, TF-193) stay on the main path.

Paste this verbatim into a fresh Codex session:

```text
Hi — picking up 5 small Taskforce tickets in MISC column on
https://alexlee4190.atlassian.net (project TF). Each ships as a
single PR to main and auto-deploys to live production on merge.
The demo video records against live prod, so all of these need
to land + deploy before filming.

For each ticket: read the description in Jira, follow the file
list, implement, open PR to main, merge once CI passes, comment
on the Jira ticket with the PR URL.

Execution order (independent tickets first, blocked ones later):

1. TF-189 — Hooks: honor TASKFORCE_HOOKS_DISABLED env var
   Repo: al-exe/EnderAI
   Files: scripts/taskforce-hooks/{user-prompt-submit,post-tool-use,stop}.sh
          + scripts/taskforce-hooks/README.md
   Add an early-exit at the top of each script (after the jq/curl
   deps check, before main logic) that reads the env var and exits 0
   with a log line. Spec in ticket.
   Branch: feature/tf-189-hooks-disabled-env
   ~10 min. Independent of all others.

2. TF-185 — Frontend: scroll V2 doc viewer to URL hash on load
   Repo: al-exe/EnderAI-frontend
   File: src/routes/v2/library.$documentId.tsx
   Add a useEffect that watches the loaded document and reads
   window.location.hash; if non-empty AND the hash matches an
   existing details_markdown_sections[].anchor_id, call the
   existing showEvidence(hash) helper. Guard with a ref to fire
   once per (doc, hash) pair. Spec in ticket.
   Branch: feature/tf-185-doc-viewer-hash-scroll
   ~20 min. Independent.

3. TF-186 — Backend: POST /v2/taskforce/reference endpoint
   Repo: al-exe/EnderAI
   Files: backend/app/api/routes/taskforce.py (new route),
          backend/app/models.py (request/response models),
          backend/app/tests/api/routes/test_taskforce.py (new tests).
   For each document_id in the request body, locate the existing
   details_markdown_sections entry with anchor_id="referenced-by"
   (create if absent), append a markdown row with session_id +
   timestamp + truncated user_prompt, cap at 200 entries (drop
   oldest). Persist via apply_v2_document_update so token-count
   refresh runs. Spec in ticket.
   Branch: feature/tf-186-reference-endpoint
   ~1-2 hr. Independent.

4. TF-192 — Frontend: filter /v2/metrics by session_id query param
   Repo: al-exe/EnderAI-frontend
   Files: src/routes/v2/metrics.tsx, possibly a new
          src/api/v2Taskforce.ts for typed clients.
   When ?session_id=<uuid> is in the URL, show a banner above the
   dashboard ("Showing savings for session <short> — view all") and
   replace the headline cards with values from
   GET /v2/taskforce/session-savings?session_id=<uuid>&pricing_model_id=claude-opus-4-7.
   Also show the session-log list as a small table beneath. Without
   the param, page renders unchanged. Spec in ticket.
   Branch: feature/tf-192-metrics-session-filter
   Soft dep on TF-187 (the backend endpoint, on my plate). If TF-187
   isn't merged when you start, scaffold the FE against the contract
   in the TF-187 ticket; the page can ship and the cards just show
   loading/zero until TF-187 lands.
   ~1-2 hr.

5. TF-190 — Skill: auto-detect agent model + effort (POST-DEMO POLISH)
   Repo: al-exe/EnderAI
   Files: scripts/taskforce-skill/tf-savings.sh + SKILL.md.
   Replace hardcoded "claude-opus-4-7" with $CLAUDE_MODEL env read,
   falling back to claude-opus-4-7 when unset. Same for effort
   string from $CLAUDE_EFFORT. Spec in ticket. Post-demo polish, so
   ship LAST.
   Branch: feature/tf-190-skill-model-detect
   Blocked by TF-188 (the skill must exist first — that's on my
   plate). If TF-188 isn't merged when you reach this one, leave it
   pending and ping me to take it back.
   ~30 min once unblocked.

PR conventions for both repos:
- Branch off main, PR to main, squash merge.
- PR title format: "TF-NNN: <short description>" matching ticket summary.
- Run lint + tests locally before pushing (npx biome check /
  npx tsc --noEmit / pytest tests/...).
- Don't skip pre-commit hooks; if a hook fails, fix the underlying
  issue and re-commit as a new commit (never --amend after hook
  failure).
- Memory note: edits to pyproject.toml require `uv lock` in the
  same PR; edits to package.json require `npm install` updating
  package-lock.json in the same PR. None of these 5 tickets should
  touch dep files — flag it if your impl needs a new dep.
- No direct pushes to main.

How deploys work (so you know when each ticket is "live"):
- al-exe/EnderAI main → Render auto-deploys backend (~5 min).
  Render dashboard service is "EnderAI-backend".
- al-exe/EnderAI-frontend main → GitHub Pages workflow
  (.github/workflows/deploy-frontend-pages.yml) deploys to
  https://www.taskforce.tools (~2 min after green CI).
- No staging environment — features go straight to production.
- TF-193 is the ONE ticket that does NOT merge to main (long-lived
  demo branch). It's not on your plate.

After each merge:
- Wait for the auto-deploy to finish (Render dashboard / Actions tab).
- Smoke-test the deployed endpoint or page.
- Comment on the Jira ticket with "PR <url> merged + deployed".

If anything in the ticket spec is ambiguous, comment on the Jira
ticket asking for clarification rather than guessing. The full
demo video plan lives at ~/dev/docs/taskforce-demo-video-plan.md
if you want broader context.

Skip TF-184, TF-187, TF-188, TF-191, TF-193 — those are on my plate.
```

After Codex finishes:
- 5 PRs merged across the two repos
- Combined with the 5 I'll take (TF-184, TF-187, TF-188, TF-191, TF-193) the demo is feature-complete
- Run the §8 filming gotcha pre-flight checklist before recording
