# Taskforce demo — "Mission control for your AI" (1-min & 3-min cuts)

*Created 2026-06-17. **Reframed 2026-06-22** to the north star
(`taskforce-northstar.md`): Taskforce is **Mission control for your AI — the
vendor-neutral control plane that remembers, observes, and steers every agent across
every harness.** **Updated again 2026-06-22:** retargeted to **1-min & 3-min** cuts
(the 1-min is a near-wordless feature montage), and the **self-evolving knowledge
layer (T0–T7) is now BUILT** — promoted from "coming" to a filmable beat (gated by
`TF_SELF_EVOLVE`; see §4–§5). ROI/$ is banked — mentioned, never the headline.*

*Companions (reuse their seed + scenario): the specialist/seed brief
[`taskforce-agents-demo-handoff.md`](./taskforce-agents-demo-handoff.md) and the
self-evolving plan [`~/dev/docs/self-evolving-knowledge-layer/`].*

---

## 0. What this proves

**Without Taskforce: ephemeral agents, siloed per harness.** Your Claude Code memory
does nothing for your Cursor users; the next great harness drops and the org is back
to square 0.

**With Taskforce: one control plane above every harness.**

> **Mission control for your AI** — your agents run wherever you like (Claude Code,
> Codex, Cursor); Taskforce sits on top and **observes** the whole fleet,
> **remembers** what each one figures out (docs + specialists that now *write
> themselves*), lets you **steer** any agent from one screen, and keeps every reuse
> **on the record.** Bring your own harness; migrate nothing.

Kernel line (say it if asked): **we never run the agents — the harness does.** We
observe, remember, and steer; we never take the stick. That's why we can be neutral.

| Verb | Surface | Proves |
|---|---|---|
| **Observe** | **Sessions** `/v2/fleet` | 3 agents live **across 3 harnesses** — status, tool, branch, activity line, profile pill. |
| **Remember** | **Profiles** + **Library** | Routed specialists + docs that **auto-create / auto-update themselves** as the fleet works (self-evolving layer). |
| **Steer** | **Session inbox** `/v2/fleet/:id` | Type a directive to a running agent from the web; its Stop hook picks it up. (Claude/Codex; Cursor observe-only.) |
| **The record** | **Ledger** `/v2/ledger` | Every reuse with provenance — who/who/which specialist/**which tool**; filter cross-boundary. |

---

## 1. The cast — one shared world both cuts film from

**Repo / branch:** `taskforce-claude` backend · `demo/stripe-double-charge` (WAL
dedupe runs *after* dispatch — the bug). Seed per `taskforce-agents-demo-handoff.md`.

| Agent | Harness | Profile | Task | Steerable? |
|---|---|---|---|---|
| **Atlas** | **Claude Code** | **Jensen — Billing Reliability** | *Hero:* "Stripe double-charges on plan upgrades — webhook retries fulfilled twice. Fix it." | ✅ |
| **Bree** | **Codex** | **Jensen — Billing Reliability** | *Via the steer beat:* "Lock it in — add the regression test (dedupe before dispatch)." | ✅ |
| **Cy** | **Cursor** | **Orin — Agent Infrastructure** | *Independent:* "Stop hook isn't appending Referenced-by — fix it." | ❌ observe/capture only |

Three harnesses, one repo — the neutrality shot. Atlas + Bree share a specialist (the
collaboration + cross-tool moment); Cy runs a different domain on Cursor.

**Library docs (seeded, clickable):** `stripe-webhook-idempotency-strategy` (hero:
2026-04-11 incident + the WAL-before-dispatch decision), `debugging-stripe-webhook-flakes`,
`stripe-plan-upgrade-regression-coverage`, `claude-code-taskforce-hook-setup`.

**The knowledge gets better as they work (now self-evolving — see §4):**
1. Atlas consults the idempotency doc → **Referenced-by — Atlas** appends. *Shipped.*
2. The new dispatch-**order** nuance is written back into the Library — via the
   **self-evolving sweeper** (auto-update + changelog) when `TF_SELF_EVOLVE` is on, or
   the deterministic `tf-capture` path as the always-on fallback.

---

## 2. The 1-minute cut — feature montage (near-wordless)

**Goal:** show *every* surface fast. **Two sentences of voice total** — one to open,
one to close. Everything else is on-screen captions + the product moving. Atlas
(Claude) + Bree (Codex) carry it; the self-evolving beats are the wow.

**Open (the only opening line):** *"This is Mission control for your AI."*

| Time | On screen | Caption | Surface |
|---|---|---|---|
| 0:00–0:09 | The **fleet** — 3 cards live across **Claude Code · Codex · Cursor**, status dots, branch, activity lines, violet **profile pills**. | *"your whole fleet · any harness"* | Sessions |
| 0:09–0:19 | Click **Atlas → Jensen** → its linked **Library** doc (the WAL decision). Cut to Atlas's terminal: the right fix, first try, *citing it.* | *"routed to the right specialist"* | Profiles → Library |
| 0:19–0:31 | The doc **updates itself** on camera (new dispatch-order section + changelog), and a **new doc auto-appears** from another session. | *"docs that write themselves"* | Library (self-evolving) |
| 0:31–0:40 | A **specialist auto-created** from real sessions surfaces (proposed → one click → active, routing). | *"specialists that earn themselves"* | Profiles (earned) |
| 0:40–0:50 | From the web, type into **Bree's session inbox**; Bree (Codex) picks it up and writes the test green. | *"steer any agent from here"* | Session inbox |
| 0:50–0:57 | **Ledger** scrolls reuse events; hover → provenance (Claude→Codex), ROI ticks in the corner. | *"every reuse, on the record"* | Ledger |
| 0:57–1:00 | Tagline card. | — | — |

**Close (the only closing line):** *"Remembers, observes, steers — across every
harness. **Bring your own harness.**"*

Six surfaces in sixty seconds. Let the self-evolving + steer beats breathe (they're
the differentiators); everything else is a fast cut.

---

## 3. The 3-minute cut — the control plane, in four acts

~45s/act, light narration. Same cast; deeper drill-downs.

### Act 1 — Observe (Sessions) · 0:00–0:45
3 agents across **Claude Code, Codex, Cursor**; status, tool chips, branch, activity
lines, profile pills; open the **Shared context** drawer. VO: *"Three agents, three
tools, one screen. They run in their own harness — Taskforce doesn't run them, it
sits above them."*

### Act 2 — Remember + self-evolve (Profiles + Library) · 0:45–1:45
Open **Jensen** (routing triggers, instructions, linked knowledge); show the `/tf`
routing line in Atlas's session. Cut to Atlas applying the fix citing
`decision-wal-table`. Then the payoff: the Library doc **auto-updates itself** (new
section + changelog), a **new doc auto-creates** from a session with no match, and an
**earned specialist** appears (proposed → confirmed → routing). VO: *"These weren't
written by hand. The docs and the specialists write themselves from what the fleet
figures out — and Taskforce routes the right one in."*

### Act 3 — Steer + the handoff (Session inbox) · 1:45–2:30
From the web, send the regression-test directive into **Bree's session inbox** —
**steering a running Codex agent without touching its terminal.** Bree inherits
Atlas's just-written decision (the knowledge bus) and writes the test green.
Meanwhile **Cy** fixes its bug **on Cursor, in parallel** (observed, not steered). VO:
*"One agent's discovery becomes the next one's starting point — across people and
tools — and I can steer any of them from here."*

### Act 4 — The record (Ledger) · 2:30–3:00
Filter **cross_boundary = true** → reuse that crossed a person or a harness. Drill one
event: produced-by → consumed-by, specialist, doc, sessions, **tools** (Claude→Codex).
ROI sits understated. Close: *"Mission control for your AI — it remembers, observes,
and steers across every agent, person, and tool. No single vendor can show it to you."*

---

## 4. What's real vs staged (honesty box)

- **Real today:** the cross-harness Sessions roster + activity lines + profile pill;
  Library docs + content; `/tf` routing; the fix + regression test on the demo branch;
  `tf-capture` live doc write; **the session-inbox steer (Claude/Codex)**; Ledger +
  provenance.
- **Self-evolving — BUILT, gated OFF.** The auto-create / auto-update docs and
  auto-earned specialists (T0–T7) are **merged, deployed, and migrated on prod**, but
  the master switch **`TF_SELF_EVOLVE` is unset**, so the sweeper isn't running. To
  film the self-evolving beats live: **enable `TF_SELF_EVOLVE`** (§7) and **confirm
  auto-proposed specialists via the review API** — the review **UI is not built yet**.
  *If you don't enable it:* fall back to the always-on `tf-capture` + Referenced-by
  path for the "docs get better" beat, and keep profiles seeded.
- **Handoff timing:** Bree inheriting Atlas's decision is a **pull on Bree's next
  `/tf` turn** (the knowledge bus), not realtime telepathy. Film Bree right after.
- **Harness honesty:** Claude/Codex are steerable (Stop-hook injection); **Cursor is
  observe/capture only** — put the steer beat on Atlas or Bree.
- **ROI:** any token/$ figure is derived from doc structure, not asserted — never the headline.

---

## 5. What must be live to film (dependencies)

> **Build status (2026-06-22).** All beats now ship on `main`, incl. the self-evolving
> layer (T0–T7, merged + migrated). Install the skill: `bash scripts/taskforce-skill/install.sh`.
> Seeded library: `TASKFORCE_DEMO=1`.

| Need | Cut/beat | Status / action |
|---|---|---|
| Cross-harness roster + activity lines + profile pill | 1-min 0:00 / Act 1 | ✅ `FleetPage` + PR #356. Set one agent each to Claude/Codex/Cursor. |
| Profiles grid + Jensen + `/tf` routing line | 1-min 0:09 / Act 2 | ✅ ships (seed per handoff). |
| Library content + anchors + Referenced-by live | both / Act 2 | ✅ shipped (`/reference`). |
| **Docs auto-create / auto-update themselves** | 1-min 0:19 / Act 2 | ✅ **built (T1–T3)** — needs **`TF_SELF_EVOLVE=true`** + the sweeper running; else `tf-capture` fallback. |
| **Earned specialist auto-created** | 1-min 0:31 / Act 2 | ✅ **built (T4)** — lands `status="proposed"`; **confirm via `POST /v2/evolution/review/specialists/{id}/confirm`** (review UI pending). |
| **Steer a running agent from the web** | 1-min 0:40 / Act 3 | ✅ shipped — enqueue to `POST /v2/taskforce/session/:id/inbox`; Stop hook (**Claude/Codex**) re-injects. Cursor = observe only. Smoke-test first. |
| Fresh decision reaches a fleet-mate | Act 3 | ✅ `tf-fleet.sh` bus — pull per `/tf` turn, not realtime. |
| Ledger + `cross_boundary` + provenance | 1-min 0:50 / Act 4 | ✅ `/v2/ledger`. Bree on Codex → real Claude↔Codex row. |

**Recording discipline:** pre-warm; demo/real isolation per `is_demo`; browser ≥110%,
terminal ≥16pt; pin display names.

---

## 6. Open decisions — verify, Alex

1. **Film real self-evolution?** Enabling `TF_SELF_EVOLVE` on prod (the magic 1-min
   beats) requires the go-live flip + confirming proposed specialists via API
   (review UI not built). *Recommend: build the review UI + enable, then film the
   real auto-evolution.* Otherwise use the `tf-capture` fallback. *(Impact: high — it's
   the most differentiated beat.)*
2. **Harness mix:** Atlas·Claude / Bree·Codex / Cy·Cursor (3 harnesses) vs. simplify
   to Claude+Codex. *Recommend 3 — it's the "bring your own harness" pitch.*
3. **Steer beat:** deliver Bree's task via the **web session inbox** (recommended — the
   new differentiated moment) vs. typing in the terminal.

---

## 7. How to run it — operator runbook

Helpers: [`demo-fleet-seed.sh`](./demo-fleet-seed.sh), [`demo-fleet-reset.sh`](./demo-fleet-reset.sh).

### 7.0 One-time setup
**A. Install the `/tf` skill:** `cd ~/dev/EnderAI && bash scripts/taskforce-skill/install.sh`.
**B. Seed** (Render Shell, `cd /app/backend`): `bash /path/to/demo-fleet-seed.sh --email alexlee4190@gmail.com`.
Verify (Demo mode ON): Profiles 5 cards, Library Stripe docs, Ledger rows. Routing smoke:
```bash
TASKFORCE_DEMO=1 ~/.claude/skills/tf/tf-discover.sh \
  --prompt "Stripe double-charging on plan upgrades — webhook retries fulfilled twice. Fix it?" \
  --files "app/api/routes/billing.py" | jq .matched_specialist   # expect slug "jensen"
```
**C. Steer smoke test:** with a Claude/Codex agent on the board, enqueue a directive to its session-detail page; confirm it re-injects on the next Stop. (Cursor won't.)

**D. (Only to film real self-evolution) Turn on the sweeper.** On Render, set
`TF_SELF_EVOLVE=true` and a short `EVOLUTION_SWEEP_INTERVAL_SECONDS=20` for the take;
run a material session; watch the Library doc auto-update + a new doc auto-create;
**confirm the auto-proposed specialist:**
`POST /v2/evolution/review/specialists/{id}/confirm`. Set `TF_SELF_EVOLVE` back to
unset after filming. *(Skip D to use the `tf-capture` fallback.)*

### 7.1 Launch the fleet (one terminal per agent, one harness each)
```bash
cd ~/dev/taskforce-claude && git checkout demo/stripe-double-charge
export TASKFORCE_DEMO=1 TASKFORCE_HOOKS_DISABLED=1
# Atlas: claude        | Bree: TASKFORCE_CLIENT=codex codex | Cy: TASKFORCE_CLIENT=cursor <cursor>
```
New sessions auto-join the **Default** fleet session. Rename Atlas / Bree / Cy before rolling.

### 7.2 The run, in order
| # | Agent · harness | How | Content |
|---|---|---|---|
| 1 | **Atlas** · Claude | terminal | `/tf Stripe is double-charging on plan upgrades — webhook retries fulfilled twice. Fix it?` |
| 2 | **Cy** · Cursor *(parallel)* | terminal | `/tf The Stop hook isn't appending "Referenced by" entries — fix it.` |
| 3 | **Bree** · Codex *(after Atlas)* | **web session inbox (steer beat)** | `Lock in the fix — add the regression test (dedupe before dispatch).` |

Atlas confirms "yes" → its capture writes the decision before Bree runs. Steer Bree
from the web; its next turn pulls Atlas's doc via `tf-fleet` (🛰) and writes the test.

### 7.3 Reset between takes
```bash
bash /path/to/demo-fleet-reset.sh   # token-only: clears this take's captured docs
# Full reset (also consult events + Referenced-by + code + inbox + auto-evolved docs):
DATABASE_URL='postgresql://…' TASKFORCE_DEMO_REPO=~/dev/taskforce-claude \
  TASKFORCE_DEMO_BRANCH=demo/stripe-double-charge bash /path/to/demo-fleet-reset.sh
```
Leaves the seeded baseline intact. If you ran step D, also delete the auto-created
docs/specialists from that take (or reset before the next).
