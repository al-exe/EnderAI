# ⚠️ demo/stripe-double-charge — intentionally broken

This branch is **the recording target for the Taskforce demo video**. It is
**not** intended to merge to `main` — the code on this branch is deliberately
broken so the recorded fix has a real bug to fix.

## What's broken (on purpose)

`app/api/routes/billing.py::receive_stripe_webhook` calls
`record_stripe_event_or_skip(session, event)` **after** `_dispatch_event(...)`
instead of before. That means duplicate Stripe webhook retries (which happen
during Stripe outage recovery) re-run the plan-upgrade fulfillment side effect
before the WAL row catches up — exactly the production bug pattern we want to
demo Taskforce solving.

The regression test that proves the bug exists is:

```
tests/api/test_billing_webhook_replay.py::test_plan_upgrade_webhook_retry_short_circuits_before_dispatch
```

On this branch (pre-fix) the test **FAILS** because the mocked
`_handle_subscription_event` runs twice on the second delivery. After the
demo's recorded fix (move the WAL call ahead of dispatch + add an early
return), the test **PASSES**.

## What the demo records

1. User invokes `/tf` in Claude Code with the prompt:
   > Stripe is double-charging some users on plan upgrades — looks like
   > webhook retries are getting fulfilled twice. Can you fix it?
2. Taskforce surfaces three seeded docs (Stripe webhook idempotency strategy,
   debugging playbook, plan-upgrade regression coverage).
3. Claude reads the prior decision record, identifies the misplaced WAL
   call, applies the ~6-line fix, runs the regression test, watches it go
   green.
4. Skill records the session as a Jensen invocation and shows the savings.

Filming plan: `~/dev/docs/taskforce-demo-video-plan.md`.
Bug-shape decision: TF-193 in the MISC column on Jira.

## DO NOT MERGE TO MAIN

The migration `app/alembic/versions/c4d8e7f1a2b3_add_stripe_webhook_wal.py`,
the `StripeWebhookEvent` SQLModel in `app/models.py`, the
`record_stripe_event_or_skip` helper in `app/core/stripe_billing.py`, and
the broken handler wiring in `app/api/routes/billing.py` are scaffolding
for the demo recording. If any of this needs to ship to prod, do it as a
separate PR off `main` with the WAL call placed BEFORE dispatch from day
one.

## Maintenance

When `main` churns substantially, rebase this branch:

```bash
git checkout demo/stripe-double-charge
git fetch origin
git rebase origin/main
# resolve conflicts, keeping the WAL-after-fulfillment placement
pytest tests/api/test_billing_webhook_replay.py -q  # should FAIL
git push --force-with-lease
```

Re-test before re-recording.
