# Taskforce demo cuts — 1-minute & 3-minute

*Created 2026-06-02. The two show-off cuts of the **north-star** story (cross-vendor + cross-person reuse, counted in the ledger), built on what now exists: the TF-204 empty-cell proof writes a **real** `document.consulted` row (`produced_by_client=codex` → `consumed_by_client=claude-code`). Companions: [`taskforce-north-star-and-proof-plan.md`](./taskforce-north-star-and-proof-plan.md), [`taskforce-empty-cell-build-design.md`](./taskforce-empty-cell-build-design.md), [`taskforce-empty-cell-proof-runbook.md`](./taskforce-empty-cell-proof-runbook.md), and the older single-tool [`taskforce-demo-video-plan.md`](./taskforce-demo-video-plan.md) (whose `/tf` skill output + savings line these reuse).*

---

## 0. What these are / why this framing

The old video (`taskforce-demo-video-plan.md`) proves Taskforce makes **one agent in one tool** start warm. Good adoption story; **it does not show the moat.** The moat is the line in the north star:

> *AGENTS.md captures what you **write down**. Taskforce captures what your agents **figure out** — and carries it **across people and tools**.*

So both cuts below are built on the **cross-boundary reuse event** (the "empty cell"): knowledge **Alice's** agent figured out in **Codex** is surfaced and reused by **Bob's** agent in **Claude Code**, warm, with provenance, and counted as one auditable row in the ledger. That row is the number no single vendor can structurally produce.

| Cut | What it proves | Primary audience | The "wow" |
|---|---|---|---|
| **1-minute** | The carryover is real *and* counted — felt by the dev, proven in the ledger | VC / cold viewer, top-of-funnel | One teammate's *Codex* decision lands warm in another teammate's *Claude Code* — then the single ledger row that proves it |
| **3-minute** | The whole loop across all three seams (moment · person · vendor) | Design partner / technical buyer / deeper VC | You watch the knowledge get **produced** in one tool and **reused** in another, then see it **priced** in the ledger |

Both reuse the existing Stripe refund-webhook scenario, the `/tf` skill output style, and the TF-204 seed/runbook — nothing new has to be invented to film, only **C3's drill-down view** has to be live (see §4).

---

## 1. Shared scenario + assets (reused, not rebuilt)

From the proof runbook — these are **real rows in a live DB**, not a mock:

| Asset | Value | Source |
|---|---|---|
| Org | `Acme` | `seed_empty_cell_scenario` |
| Person A (producer) | **Alice** · `alice@acme.example` · tool = **Codex** | runbook |
| Person B (consumer) | **Bob** · `bob@acme.example` · tool = **Claude Code** | runbook |
| The knowledge | "Stripe **refund** webhook idempotency guardrail" — *dedupe at the route boundary; the WAL is the only thing preventing double-fulfillment; do **not** push dedupe into the handlers* | Doc A content in `taskforce-demo-video-plan.md` §3 |
| Profile | **Payments** specialist (seeded today; pinned to Alice's *real* doc) | C5 / TF-198 |
| The proof row | `document.consulted` · `produced_by_client=codex` · `consumed_by_client=claude-code` · `specialist_slug=payments` · `net_saved_tokens>0` | TF-204 |

**The transfer (not a copy):** Alice solved the *general* webhook-idempotency decision; Bob hits the *refund* variant. He reuses Alice's **route-boundary** decision rather than re-deriving it — and avoids the plausible-but-wrong in-handler fix. That "got it right the first time *because* of a teammate's prior call, in a different tool" is the whole point.

---

## 2. The 1-minute cut — "felt **and** proven"

**Goal:** in 60s, one screen of warm-start value + one screen of the ledger event. We film **Bob's** side live (Claude Code); **Alice's** Codex session is *implied* — its trace shows up as provenance, we don't film it. Tight, punchy, recordable.

| Time | On screen | Tool / who | Real vs staged |
|---|---|---|---|
| 0:00–0:08 | Bob, new to payments, types: *"We're double-fulfilling **refund** webhooks on retries again — make the handler idempotent."* | Claude Code · Bob | Real prompt, real session start |
| 0:08–0:22 | `/tf` surfaces one line: **↩ From Taskforce — Alice solved this in Codex 6 days ago:** *"dedupe at the route boundary; the WAL is the only thing preventing double-fulfillment — don't move it into the handlers."* + deep link. Agent **names Alice's specific decision** back. | Claude Code | Real cross-user/cross-tool match (C2). Surfaced line is from Alice's real doc |
| 0:22–0:38 | Bob's agent makes the **right** fix first try — the ~6-line route-boundary move (`record_stripe_event_or_skip` *before* dispatch, early-return on dup), narrating *"following the prior decision from Alice's session, the dedup has to short-circuit before fulfillment."* | Claude Code | Real edit; reliable because the seed locks the high-confidence pull (see §4) |
| 0:38–0:55 | **Cut to the ledger drill-down (C3).** One card: **Produced in Codex by Alice → Reused in Claude Code by Bob** · `payments` · **~28k tokens / ~$0.38 saved** · provenance trail (doc → both sessions → match reasons). Hold on it. | Browser · ledger view | **The real TF-204 row.** This is the non-stageable beat |
| 0:55–1:00 | Tagline card: *"AGENTS.md captures what you write down. **Taskforce captures what your agents figure out — across tools and people.**"* | Overlay | — |

**Why 1 minute works:** the viewer feels the dev value (warm start, right answer first try) and immediately sees the thing that makes it a *company* asset and not a personal cache — the same fact crossed a **tool** boundary *and* a **person** boundary and got **counted**. That triad is the empty cell.

**Honesty box (what a skeptic is told if they ask):** the Payments *profile* is seeded; **the reuse event is real** (Alice→Bob, Codex→Claude Code, live row). The $ figure is derived from the doc's `rediscovery_cost_tokens` (the math is inspectable via the deep link), not asserted. "Used" = surfaced + acted on; we don't claim "confirmed-still-correct."

---

## 3. The 3-minute cut — "the whole loop across the seams"

**Goal:** show both halves of the boundary **live** plus the ledger. Three acts, ~1 minute each. This is the version where you click into the real doc and the real ledger on camera.

### Act 1 — PRODUCE (0:00–1:00) · Alice · Codex — *the moment seam*
| Time | On screen | Notes |
|---|---|---|
| 0:00–0:35 | Alice works the gnarly idempotency task in **Codex**. She lands the decision: WAL at the route boundary, handlers not individually idempotent. | Real Codex session via `taskforce-cli --client codex` |
| 0:35–0:50 | Taskforce captures it **passively** — `202`, fire-and-forget, no latency tax. One messy session → one clean `V2Document`. | `observe` with `TASKFORCE_OBSERVE_SHADOW=0` |
| 0:50–1:00 | Flash the resulting doc in the library: substantive **decision record** ("ruled out Redis SETNX / in-handler `ON CONFLICT` because…"), stamped **owner=Alice · produced_by_client=codex · visibility=organization**. | Proves capture is real + cross-vendor + org-shared |

### Act 2 — REDROP (1:00–2:00) · Bob · Claude Code — *the person + vendor seams*
| Time | On screen | Notes |
|---|---|---|
| 1:00–1:12 | Days later, **Bob** (different person, different tool, new to payments) starts the **refund**-webhook task in Claude Code. | Real `session/start`, `client=claude-code` |
| 1:12–1:30 | `/tf` **routes the Payments specialist** + surfaces **Alice's** doc warm, with the deep link and the 3-line preview. | Real cross-user org hydration (C2) |
| 1:30–1:45 | **Click the deep link on camera** → doc viewer scrolls to the `decision-wal-table` anchor. Viewer sees Alice's real content. | Proves the thread isn't staged |
| 1:45–2:00 | Back in Claude Code: Bob's agent makes the right fix first try, explicitly crediting Alice's prior route-boundary decision. | The felt value: didn't re-derive, didn't go confidently wrong |

### Act 3 — THE LEDGER (2:00–3:00) · the moat — *the priced atom*
| Time | On screen | Notes |
|---|---|---|
| 2:00–2:30 | Cut to the **cross-boundary reuse** view (C3). The one real event end-to-end: **Produced in Codex by Alice → Reused in Claude Code by Bob** · `payments` · **net tokens / $ saved** · full provenance trail. Proven-vs-estimated split, understated. | The deliverable a skeptic clicks into |
| 2:30–2:48 | Pull back to the aggregate ledger: tokens saved, reuse rate — the **buyer's** view. "The dev never had to open this; the buyer never had to touch the memory." | Reuses the seeded metrics dashboard for the aggregate |
| 2:48–3:00 | Close on the north-star line + the one-sentence moat: *"This cross-tool, cross-person reuse number is the one thing no single vendor can show you — and it compounds. That's the company brain."* Optional 1-line forward-look: *the profile Bob used is seeded today; the roadmap earns it from real captured work (that's the part AGENTS.md can't be)*. | Earned-profiles teaser is optional — cut if running long |

**Honesty box:** same as §2. Additionally — Act 1's capture is real (shadow off); the only seeded thing in the whole chain is the *Payments profile shell*, and even that is linked to Alice's *real* produced doc.

---

## 4. What must be live to film (dependencies)

| Need | Component | Status / action |
|---|---|---|
| Real cross-boundary row exists | TF-204 runbook | ✅ writes it — run `seed_empty_cell_scenario` with `TASKFORCE_OBSERVE_SHADOW=0` |
| Provenance stamps (`produced_by_client` / `consumed_by_client`) | **C1** | Required for the ledger card; runbook lists the C1 migration as a prereq — **confirm merged + migrated** |
| Cross-user org hydration (Bob sees Alice's doc) | **C2** | Required for Act 2 / the 0:08 line — **confirm** B's `session/start` returns A's doc non-demo |
| The drill-down view (the ledger shot) | **C3** | **This is the gating dependency for the §2 0:38 beat and §3 Act 3.** The *data* is real today; the *view* must render one event with the provenance trail. If C3 isn't built, fall back to the SQL/JSON from the runbook on screen (weaker, but honest) |
| `/tf` warm-start output style + savings line | existing skill | Reuse `taskforce-demo-video-plan.md` §4 beats 3–5, 8 verbatim |
| Demo-mode aggregate dashboard (Act 3, 2:30) | seeded metrics | `taskforce-demo-prep-checklist.md` §1 |

**Recording discipline (from the prep checklist):** `TASKFORCE_OBSERVE_SHADOW=0` for the producing run; `demo=False` for the proof org (cross-user only works non-demo) but keep the *seeded aggregate dashboard* on a separate demo-flagged view; browser ≥110%, terminal ≥16pt; pre-warm the backend.

---

## 5. Open decisions / assumptions — verify, Alex

1. **C3 view readiness** — is the cross-boundary drill-down built enough to film, or do we ship it for this? It's the one true gate. *(Impact: high — it's the money shot of both cuts.)*
2. **Film Alice's Codex side live (3-min Act 1) or pre-record it?** Live is more convincing but Codex capture has to be reliable; a clean pre-record is safer. *(Impact: medium.)*
3. **Savings figure** — reuse the old ~28k/$0.38 derivation, or recompute from Alice's *actual* produced doc's `rediscovery_cost_tokens`? Prefer the latter so the number is honestly this event's. *(Impact: low–medium.)*
4. **Earned-profiles teaser** in the 3-min close — include (sharpens the moat vs. "shared prompt library") or cut for time? *(Impact: low.)*
5. **1-min for VC vs design-partner** — current draft is cold-viewer/VC oriented (felt value + the proof). A design-partner cut would foreground *their* data/workflow and the buyer dashboard. *(Impact: medium — changes emphasis, not structure.)*
