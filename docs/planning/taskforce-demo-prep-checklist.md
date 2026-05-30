# Taskforce demo prep checklist

Last updated: 2026-05-24

Run-through to do **once** before filming. Steps marked **(already done)** are checked off but listed for context. Beat-by-beat filming spec lives in [`taskforce-demo-video-plan.md`](./taskforce-demo-video-plan.md) §4.

## 1. Prod-side seeds

Render Shell on the `EnderAI-backend` service (`cd /app/backend`):

- [x] **TF-191 — Stripe webhook seed docs.** Shipped via `app/core/v2_documents.py::DEMO_SEED`; auto-applied on demo-flag reads.
- [x] **TF-198 — Specialists.** `python -m app.scripts.seed_agents --email alexlee4190@gmail.com` → expect `specialists=5 documents_created=False links=15`. (already run 2026-05-24)
- [ ] **TF-198 — Alex demo invocation history (12 sessions, ~106 events).** `python -m app.scripts.seed_demo_metrics_alex --email alexlee4190@gmail.com` → expect `sessions=12 events=106`. Side-benefit: Jensen gets 3 recent invocations (1 / 9 / 27 days ago), which boosts `recency_boost` enough to clear the medium routing threshold during the demo. Events emitted per session: `document.consulted` + `document.reused` + `tokens.saved.summary_only` per doc, plus one `tokens.consumed` (model_id varies — opus/sonnet/gpt-5), one `tokens.saved.cache` (skipped on the 41d session), one `tokens.saved.reuse` for every other session, and one `document.created` for two sessions (keeps `reuse_rate` near 93% so it doesn't read as suspiciously perfect).

The metrics seed deletes any prior `seeded=true is_demo=true` rows for the user before reinserting, so it's safely idempotent.

Sanity-check on the Metrics page (Demo mode on, 30d window) after the seed runs:

- `Tokens Saved` ≈ 330K, `USD Offset` ≈ $5, `Reuse Rate` ≈ 93%.
- `Tokens Used` ≈ 115K, `USD Spent` ≈ $2.80.
- `Top models by tokens used` shows 3 rows (claude-opus-4-7, claude-sonnet-4-7, gpt-5).
- `Savings by source` shows non-zero bars for all three (cache / summary only / reuse on begin).
- `Tokens saved per day` trend chart has multiple non-zero days spread across the window.
- `Avoided Rediscovery` (behind `localStorage["taskforce.flags.savings_v2"] = "true"`) ≈ 372K / $2.88 — unchanged from the consulted-only seed.

## 2. Routing sanity — tighten Jensen if needed

After the metrics seed, run a live smoke against the demo prompt:

```bash
TASKFORCE_DEMO=1 ~/.claude/skills/tf/tf-discover.sh \
  --prompt "Stripe is double-charging some users on plan upgrades — looks like webhook retries are getting fulfilled twice. Can you fix it?" \
  --files "app/api/routes/billing.py,app/core/stripe_billing.py" \
  | jq .matched_specialist
```

- [ ] **`matched_specialist.slug == "jensen"`, band `medium` or `high`.** If null → Jensen still scores under 0.40; trim `routing_triggers` in `app/core/agents/seed.py::SEEDED_SPECIALISTS[jensen]` from 10 entries to ~5 high-signal phrases (`stripe`, `webhook`, `plan upgrade`, `double-charging`, `billing`), redeploy backend, re-run `seed_agents` (which inserts — would need wipe-and-reinsert path; ticket separately if it comes to this).

## 3. Frontend toggles + URL

- [ ] **Enable Demo mode** in the left sidebar (toggle id `demo-mode-toggle`). Without it, `/v2/agents` and `/v2/metrics` filter to non-demo rows and show nothing.
- [ ] **Hard-refresh** the Agents tab after toggling so the React Query cache picks up `demo:true`. Expect 5 specialists: Jensen, Mira, Nia, Orin, Vega.
- [ ] **Verify deep-link works:** click one document on the Agents page → lands on `/v2/library/<uuid>#<anchor>` scrolled to the anchor.

## 4. Demo branch

- [ ] **Check out `demo/stripe-double-charge`** in the repo Claude Code is recording against — that branch has the WAL-after-fulfillment bug + the failing regression test the demo fixes (TF-193).
- [ ] Confirm `pytest tests/api/test_billing_webhook_replay.py::test_plan_upgrade_webhook_retry_short_circuits_before_dispatch -q` **fails** on the demo branch pre-fix (1 failure; passes after the fix).

## 5. Recording-shell env

Export before launching Claude Code:

```bash
export TASKFORCE_HOOKS_DISABLED=1   # so /tf is the only Taskforce path on screen
export TASKFORCE_DEMO=1             # so /tf routes to seeded specialists + demo docs
export CLAUDE_MODEL=claude-opus-4-7 # match the savings line label
export CLAUDE_EFFORT=xhigh
```

- [ ] Confirm `echo $TASKFORCE_DEMO` returns `1` in the shell Claude Code is running in.

## 6. Skill installed locally

- [ ] `ls ~/.claude/skills/tf/` shows `SKILL.md` + 3 `*.sh` files. If missing: `bash ~/dev/EnderAI/scripts/taskforce-skill/install.sh`.
- [ ] `cat ~/.enderai_mcp_token | wc -c` is non-zero.
- [ ] Restart Claude Code after install so `/tf` is registered.

## 7. End-to-end dry run

In the recording-config shell, on `demo/stripe-double-charge`, with Demo mode on, run the full /tf flow once with the demo prompt. Verify on screen:

- [ ] Beat 1: 🔎 + 📨 payload block.
- [ ] Beat 3: `✓ Routed to Jensen — Billing Reliability Specialist` (THIS IS THE ONE THAT BREAKS — confirm before recording).
- [ ] Beat 4: 1+ doc cards with `>`-quoted 3-line previews. Click one — frontend opens scrolled to the anchor.
- [ ] Beat 6/7: `✓ Jensen — added invocation` + `✓ <doc> — added Referenced by entry` for each doc.
- [ ] Beat 8: `Finished. [Taskforce saved you N tokens on Opus 4.7 xhigh effort (~$X)](.../v2/metrics?session_id=…)`. Click — metrics page opens filtered to this session.

If any beat misfires, the issue almost always traces to: token missing, demo mode off, Render not redeployed, or specialist scoring under threshold.

## 8. Recording rig

- [ ] Browser zoomed to ~110% so deep-links + URLs are readable.
- [ ] Terminal font ≥ 16pt.
- [ ] Quit other Claude Code windows so the recording session has a clean transcript.
- [ ] One full take to validate audio + framing before the real take.

## Open follow-ups (not blocking demo)

- Routing weights / Jensen trigger list tuning — TF-196 follow-up.
- Frontend Agents tab should default to demo mode when the user has no live specialists yet, so the page isn't empty by default. Small UX polish.
- `seed_agents` is insert-only; needs a wipe-and-reinsert path if we want to iterate on trigger lists without manual DB cleanup.
