> ⚠️ **ARCHIVED 2026-06-21 — historical; NOT current product direction.**
> Superseded by [`../../taskforce-northstar.md`](../../taskforce-northstar.md). Retained for reference only. Future agents: do not treat this as current guidance.

# /tf Skill Demo Transcript — Stripe Double-Charge Fix

**Date:** 2026-05-25
**Branch:** `demo/stripe-double-charge`
**Repo:** `WORKTREE-demo-stripe/demo/full-stack-fastapi-template/backend`
**Session ID:** `a07ae73b-7b14-4a68-b34d-d336abbd9e67`
**Specialist:** Jensen — Billing Reliability Specialist
**Savings:** 50,359 tokens on Opus 4.7 high effort (~$0.25)

---

## User prompt

> /tf Stripe is double-charging some users on plan upgrades — looks like webhook retries are getting fulfilled twice. Can you fix it?

---

## Beat 1 — Announce + payload

```
🔎 Checking Taskforce for related prior work…

📨 Sending to Taskforce:
```

```json
{
  "prompt": "Stripe is double-charging some users on plan upgrades — looks like webhook retries are getting fulfilled twice. Can you fix it?",
  "cwd": "/home/alexlee/dev/taskforce-claude/WORKTREE-demo-stripe/demo/full-stack-fastapi-template/backend",
  "files": [],
  "git_branch": "demo/stripe-double-charge"
}
```

## Beat 2 — Discover call

```bash
~/.claude/skills/tf/tf-discover.sh \
  --prompt "Stripe is double-charging some users on plan upgrades — looks like webhook retries are getting fulfilled twice. Can you fix it?" \
  --cwd "$PWD" \
  --files "" \
  --git-branch "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
```

Response (abridged):

```json
{
  "ok": true,
  "session_id": "a07ae73b-7b14-4a68-b34d-d336abbd9e67",
  "matched_specialist": {
    "slug": "jensen",
    "name": "Jensen",
    "role": "Billing Reliability Specialist",
    "confidence": 0.4543,
    "band": "medium",
    "href": "https://www.taskforce.tools/v2/agents/jensen",
    "reasons": [
      "Strong match on routing triggers: 30% overlap with prompt",
      "Linked knowledge matches the request — top: \"Stripe webhook idempotency strategy\"",
      "Request files referenced in linked docs (100%)"
    ]
  },
  "matches": [
    {
      "document_id": "fd9e0222-1adb-492f-84d3-b8333ed6af9b",
      "title": "Stripe webhook idempotency strategy",
      "score": 0.341,
      "confidence_band": "medium",
      "matched_anchor_id": "decision-wal-table"
    },
    {
      "document_id": "a3eaa34a-73f5-460a-9829-5d9415edabb6",
      "title": "Stripe plan upgrade webhook retries — regression test pattern",
      "score": 0.3219,
      "confidence_band": "medium",
      "matched_anchor_id": "side-effect-assertion"
    }
  ]
}
```

## Beat 3 — Matched specialist

```
✓ Routed to Jensen — Billing Reliability Specialist
  Confidence: medium (0.4543)
  Why: Strong match on routing triggers: 30% overlap with prompt · Linked knowledge matches the request — top: "Stripe webhook idempotency strategy" · Request files referenced in linked docs (100%)
  [→ View specialist profile](https://www.taskforce.tools/v2/agents/jensen)
```

## Beat 4 — Document matches

**1. Stripe webhook idempotency strategy** — confidence: medium (0.34)
[→ Open at decision-wal-table](https://www.taskforce.tools/v2/library/fd9e0222-1adb-492f-84d3-b8333ed6af9b#decision-wal-table)
Matched on: Title tokens overlap on 'stripe', 'webhook', Files referenced: app/api/routes/billing.py, app/core/stripe_billing.py, app/models.py

> ## Decision — WAL table at the route boundary
> **Chose:** dedicated `stripe_webhook_event` WAL table, checked in `app/api/routes/billing.py` BEFORE dispatching to any handler.
> **Why:** fulfillment handlers are not uniformly idempotent. Some webhook types, such as `customer.subscription.updated`, do not have a natural unique side-effect key across all upgrade paths.

**2. Stripe plan upgrade webhook retries — regression test pattern** — confidence: medium (0.32)
[→ Open at side-effect-assertion](https://www.taskforce.tools/v2/library/a3eaa34a-73f5-460a-9829-5d9415edabb6#side-effect-assertion)
Matched on: Title tokens overlap on 'plan', 'retries', 'stripe', 'webhook', Files referenced: app/api/routes/billing.py, app/core/stripe_billing.py

> ## Side-effect assertion
> A passing duplicate replay test should prove the handler in `app/api/routes/billing.py` did not re-run the expensive or customer-visible side effect, even when Stripe webhook retries fire twice for the same `customer.subscription.updated` plan upgrade event.
> Acceptable assertions for the regression test in `app/tests/api/routes/test_billing.py`:

## Beat 5 — Investigation and fix

### Located the bug

`app/api/routes/billing.py:310` — the webhook handler `receive_stripe_webhook` calls `record_stripe_event_or_skip` **after** the dispatch block. The demo branch comment (`TF-193`) makes the intent explicit:

```python
# ⚠️ DEMO BRANCH (TF-193): the WAL call is intentionally placed
# AFTER fulfillment dispatch. This is the bug the demo video
# records the fix for — duplicate webhook retries re-run the
# plan-upgrade fulfillment side effect before the WAL catches up.
# The fix moves `record_stripe_event_or_skip(...)` and an
# early-return for duplicates ABOVE the dispatch block.
```

Concurrent retries both pass the dispatch block before either writes the WAL row, so fulfillment runs twice.

### Verified WAL function contract

`app/core/stripe_billing.py:170` — `record_stripe_event_or_skip` returns:
- `True` — first time we have seen this event_id; fulfillment should run.
- `False` — duplicate; the caller MUST NOT re-run fulfillment.

Keyed on `(event_id, is_test_mode)` so test-mode replays don't collide with live.

### Applied fix

Moved the WAL call above the dispatch block with an early-return on duplicate. Final shape of `receive_stripe_webhook`:

```python
event = verify_webhook_signature(payload, signature_header)
event_type = event.get("type")
data = event.get("data")
event_object = data.get("object") if isinstance(data, dict) else None
if not isinstance(event_type, str) or not isinstance(event_object, dict):
    raise HTTPException(status_code=400, detail="Invalid Stripe webhook event")

if not record_stripe_event_or_skip(session, event):
    session.commit()
    return Message(message="Stripe webhook already processed")

if event_type == "checkout.session.completed":
    _handle_checkout_session_completed(session, event_object)
elif event_type in {
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}:
    _handle_subscription_event(session, event_object)
elif event_type == "invoice.paid":
    _handle_invoice_event(session, event_object, status_value="active")
elif event_type == "invoice.payment_failed":
    _handle_invoice_event(session, event_object, status_value="past_due")

session.commit()
return Message(message="Stripe webhook processed")
```

### Verified

- `tests/api/test_billing_webhook_replay.py::test_plan_upgrade_webhook_retry_short_circuits_before_dispatch` → **pass**
- Full `tests/api/routes/test_billing.py`: 7 pass / 2 fail / 1 error. Both failures and the error are **pre-existing test isolation flakes** (DB rows from one test leaking into the next — `stripe_subscription_id="sub_existing"` UniqueViolation). Confirmed by `git stash`-ing the fix and re-running: baseline showed 4 pass / 5 fail / 1 error. The fix improves the suite, not the other way around.

Tests were run against the `tf184-pg` Docker container (Postgres on `127.0.0.1:55432`).

## Beat 6 — Record reference

```bash
~/.claude/skills/tf/tf-reference.sh \
  --session-id "a07ae73b-7b14-4a68-b34d-d336abbd9e67" \
  --document-ids "fd9e0222-1adb-492f-84d3-b8333ed6af9b,a3eaa34a-73f5-460a-9829-5d9415edabb6" \
  --user-prompt "Stripe is double-charging some users on plan upgrades — looks like webhook retries are getting fulfilled twice. Can you fix it?"
```

Response:

```json
{"ok":true,"updated_document_ids":[],"skipped_document_ids":["fd9e0222-1adb-492f-84d3-b8333ed6af9b","a3eaa34a-73f5-460a-9829-5d9415edabb6"]}
```

Both documents reported as inaccessible to this caller — they were not updated server-side. Specialist invocation was recorded by the discover-time routing.

## Beat 7 — Reference confirmations rendered

```
Recording this session in the referenced docs…
✓ Jensen — added invocation
(skipped 2 inaccessible doc(s))
```

## Beat 8 — Savings

```bash
~/.claude/skills/tf/tf-savings.sh --session-id "a07ae73b-7b14-4a68-b34d-d336abbd9e67"
```

Response:

```json
{
  "ok": true,
  "session_id": "a07ae73b-7b14-4a68-b34d-d336abbd9e67",
  "net_saved_tokens": 50359,
  "usd_saved": "0.251795",
  "doc_count": 2,
  "pricing_model_id": "claude-opus-4-7",
  "model_display": "Opus 4.7",
  "effort_label": "high",
  "metrics_url": "https://www.taskforce.tools/v2/metrics?session_id=a07ae73b-7b14-4a68-b34d-d336abbd9e67"
}
```

Final line rendered to user:

> Finished. [Taskforce saved you 50,359 tokens on Opus 4.7 high effort (~$0.25)](https://www.taskforce.tools/v2/metrics?session_id=a07ae73b-7b14-4a68-b34d-d336abbd9e67)

---

## Notes for the demo recording

- First `/tf` invocation was interrupted by the user before Beat 2 completed; the second invocation produced a fresh `session_id` and ran cleanly through all beats. Only the second session is referenced in metrics.
- Discover initially returned `matched_specialist: null, matches: []` on the first run (likely an embedding/index timing artifact) and returned the full Jensen + 2-doc match set on the immediate retry. Worth noting for the demo — the gap was a few seconds.
- Both matched documents came back as `skipped_document_ids` in the reference call (inaccessible to the caller). Worth investigating whether demo tenant ACLs need to grant the demo identity read+write on the seeded Stripe docs so the "Referenced by" entries actually land for the recording.
- The pre-existing test isolation flakes in `tests/api/routes/test_billing.py` (UniqueViolation on `sub_existing`) are unrelated to TF-193 but will be visible if the demo runs the full file. Recommend running only the targeted replay test on camera, or fixing the fixture teardown first.
