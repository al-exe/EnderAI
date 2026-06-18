# Taskforce demo — the live fleet story (2-min & 5-min cuts)

*Created 2026-06-17. A **new** demo story whose hero is the live multi-agent
fleet — 2–4 Claudes running at once, each routed to a **Profile**, supported by
**Library** documents that update as the fleet works, all recorded in the
**Ledger**. ROI/$ is deliberately banked for now (mentioned, never the headline).*

*Companions (reuse their seed + scenario, don't re-invent): the single-thread
[`taskforce-demo-cuts-1min-3min.md`](./taskforce-demo-cuts-1min-3min.md), the
specialist/seed brief [`taskforce-agents-demo-handoff.md`](./taskforce-agents-demo-handoff.md),
the Sessions roadmap [`taskforce-fleet-mission-control.md`](./taskforce-fleet-mission-control.md),
and the original single-tool [`taskforce-demo-video-plan.md`](./taskforce-demo-video-plan.md).*

---

## 0. What this proves (and how it differs from the existing cuts)

The shipped 1-/3-minute cuts prove **one carryover, counted**: Alice's Codex
decision lands warm in Bob's Claude Code, one ledger row. Great moat shot, but a
*single thread*.

This story sells the **product surface as a whole** — the four tabs as one loop:

> Spin up a small fleet → each agent is **routed to a Profile** that brings the
> right knowledge → the **Library** docs they lean on update *while they work* →
> what one agent figures out becomes the next agent's starting point → the
> **Ledger** is the org-wide record of all of it.

The pitch in one line: **Mission Control for a multi-agent team — it observes the
fleet, routes the right specialist into each session, and remembers across every
agent, person, and tool.**

| Tab (sidebar) | Route | What it proves on screen |
|---|---|---|
| **Sessions** | `/v2/fleet` | 2–4 Claudes live at once — status, tool, branch, and a live activity line of what each is doing. "I can see my whole fleet." |
| **Profiles** | `/v2/agents` | Each agent is steered by a reusable specialist (Jensen/Billing, Orin/Agent-infra…) built from the team's captured work — not a prompt someone hand-wrote. |
| **Library** | `/v2/library` | The decision/incident docs the agents lean on are real *and* self-updating (Referenced-by appended; new nuance captured live). |
| **Ledger** | `/v2/ledger` | One org-wide record of every reuse — who produced it, who consumed it, which specialist, which tool. Filter to cross-boundary to see knowledge crossing people/tools. |

---

## 1. The cast — one shared world both cuts film from

All real seed already specced in `taskforce-agents-demo-handoff.md` (§2–3) and the
Stripe branch in `taskforce-demo-video-plan.md`. Nothing new to invent.

**Repo / branch:** `taskforce-claude` backend · `demo/stripe-double-charge`
(the pre-built branch where the WAL dedupe is called *after* dispatch — the bug).

**The fleet (Sessions board):**

| Agent (pinned name) | Tool | Profile routed | Task | Editing |
|---|---|---|---|---|
| **Atlas** | Claude Code · Opus 4.7 | **Jensen — Billing Reliability** | *Task A (hero):* "Stripe is double-charging on plan upgrades — webhook retries get fulfilled twice. Fix it." | `app/api/routes/billing.py` |
| **Bree** | Claude Code · Opus 4.7 | **Jensen — Billing Reliability** | *Task A companion:* "Lock it down — add the regression test that proves dedupe happens before dispatch on the plan-upgrade path." | `tests/api/routes/test_billing.py` |
| **Cy** | Claude Code · Opus 4.7 | **Orin — Agent Infrastructure** | *Task B (independent):* "The Stop hook isn't appending Referenced-by entries after sessions — fix it." | `scripts/taskforce-hooks/stop.sh` |
| *(5-min only)* **Dot** | Claude Code *(or Codex — see Open Decisions)* | **Mira — Search & Retrieval** | *Task B-adjacent:* "Citations are linking to the summary, not the exact anchor — repair it." | `app/core/search/...` |

Two tasks, one repo. Atlas + Bree share the **same Profile and the same docs**
(that's where collaboration + a collision moment live). Cy (and Dot) run a
*different* domain so the board reads like a real fleet, not one task cloned — and
so the **Profiles** grid visibly has more than one specialist in play.

**The Library docs in play** (all seeded, all clickable):
- `stripe-webhook-idempotency-strategy` — the hero doc: 2026-04-11 incident +
  the decision *"WAL at the route boundary, before dispatch; handlers are not
  individually idempotent."* (anchors `decision-wal-table`, `incident-2026-04-11`)
- `debugging-stripe-webhook-flakes` — Jensen's ops playbook.
- `stripe-plan-upgrade-regression-coverage` — what Bree's test is built from.
- `claude-code-taskforce-hook-setup` / `referenced-by-update-policy` — Cy's docs.

**The live document updates** (the "updated as we go" the demo must show):
1. Atlas consults the idempotency doc → a **Referenced-by** entry appends (Atlas's
   session). *Shipped behavior.*
2. Atlas hits the *new* nuance — the demo bug is a dispatch-**order** regression,
   not the original incident — and that nuance is **captured into the Library**
   (patches the `targeted-regression-test` anchor / a short new note). *This fresh
   decision is what Bree starts from.*

---

## 2. The 2-minute cut — "A fleet that shares a brain"

**Goal:** all four tabs, one throughline, two agents. Tight. Atlas + Bree only.

| Time | On screen | Tab | Real vs staged |
|---|---|---|---|
| 0:00–0:15 | Open on **Sessions**. Two Claude cards live, status dots green, each showing tool chip · Opus 4.7 · `demo/stripe-double-charge` · a live activity line ("editing billing.py…", "writing test_billing.py…"). VO: *"This is my fleet right now — every running agent and what it's touching."* | Sessions | Real roster (`/fleet` poll). Activity line + client chip ship today. |
| 0:15–0:40 | Click **Atlas → its Profile: Jensen, Billing Reliability**. Show when-to-use, the instruction *"dedupe at the route boundary, before fulfillment"*, and **linked knowledge** (the Stripe docs). VO: *"Atlas didn't start cold — Taskforce routed it to Jensen, a specialist built from our own past billing incidents, and Jensen brings the right decisions in."* | Profiles | Profiles grid/detail ship today. Routing line shown via `/tf`. |
| 0:40–1:05 | Click Jensen's linked doc → **Library**: real 2026-04-11 incident + the WAL-before-dispatch decision. Cut to Atlas's terminal: it makes the **right** ~6-line fix first try, *citing that decision*. Back to the doc — a new **"Referenced by — Atlas"** entry has appeared. VO: *"The documents aren't static. They update as the fleet uses them."* | Library | Doc content + Referenced-by are real. The fix is the proven Stripe beat. |
| 1:05–1:30 | **The handoff.** Bree (second Claude, same Jensen profile, writing the test) picks up Atlas's just-captured *dispatch-order* decision — surfaced in her **Shared context** — and writes the test asserting dedupe-before-dispatch **without re-deriving it**. VO: *"What one agent figures out, the next one starts with — automatically."* | Sessions → terminal | See §5: live push to a running agent is the roadmap beat; honest fallback in the dependencies table. |
| 1:30–1:55 | Cut to **Ledger**. The two rows that just happened: Atlas consulted Jensen's idempotency doc; Bree consulted the same doc **plus Atlas's update**. Hover one → provenance trail (doc → both sessions → why it matched). (Savings sits quietly in the corner; not narrated.) VO: *"And it's all on the record — every reuse, across every agent, in one ledger."* | Ledger | Ledger + provenance ship today. |
| 1:55–2:00 | Tagline card: *"AGENTS.md captures what you write down. **Taskforce captures what your agents figure out — and shares it across the whole fleet.**"* | Overlay | — |

**Why 2 minutes works:** the viewer touches all four tabs but feels *one* motion —
fleet → specialist → living doc → the next agent inherits it → the record. Sessions
and Library do the emotional work; the Ledger closes it as a company asset.

---

## 3. The 5-minute cut — "Mission Control for a multi-agent team"

**Goal:** the full loop with breadth. 3 agents (optionally 4), 2 tasks, deeper
drill-downs, a live doc *capture* (not just Referenced-by), and the Ledger filtered
to cross-boundary. Five acts, ~1 minute each.

### Act 1 — The board (Sessions) · 0:00–1:00
Open Mission Control with **3 live Claudes across 2 tasks**. Walk the cards:
status dots, tool chips, `demo/stripe-double-charge`, and the live activity line on
each (Atlas → billing.py, Bree → test_billing.py, Cy → stop.sh). Note Atlas + Bree
are in the **same repo on the same files** (the collision/coordination setup). Open
the **Shared context** drawer so the viewer sees the fleet already has a common
memory surface. VO: *"Three agents, two jobs, one screen. I can see exactly what
each one is doing — and they're not working blind to each other."*

### Act 2 — The specialists (Profiles) · 1:00–2:00
Go to the **Profiles** grid: Jensen, Mira, Orin, Vega, Nia — a populated command
center, each with domain tags, linked-doc counts, invocation history. Open
**Jensen**: routing triggers, instructions, **linked knowledge**, recent
invocations. VO: *"These aren't prompts I wrote. They're specialists built from our
team's captured work — and Taskforce routes each task to the right one."* Show the
`/tf` line in Atlas's session: *"Routed to Jensen — Billing Reliability (0.91)."*

### Act 3 — Living documents (Library) · 2:00–3:00
Open `stripe-webhook-idempotency-strategy`. Real incident + the WAL-before-dispatch
decision. Cut to Atlas applying the fix, citing `decision-wal-table`. Two updates
land **on camera**: (1) a **Referenced-by — Atlas** entry; (2) Atlas captures the
*new* nuance — this branch regressed the **order** (WAL after dispatch) — into the
Library as a fresh, inspectable note under `targeted-regression-test`. VO: *"The
knowledge didn't just get used — it got better. The fleet is writing the team's
memory as it works."* (This is the "self-updating documents" promise made literal.)

### Act 4 — The fleet shares a brain (collaboration) · 3:00–4:00
**Bree** (same Jensen profile, the test) inherits Atlas's just-captured decision —
via Shared context / her next discover — and writes
`test_plan_upgrade_webhook_retry_short_circuits_before_dispatch` that asserts
dedupe-before-dispatch, *because Atlas already settled it*. Run it: green. Meanwhile
**Cy** (Orin profile) is fixing the Stop-hook Referenced-by bug **in parallel,
independently** — proof this is a fleet, not a relay. Optional cross-tool beat: if
Dot/Cy runs on **Codex**, the same knowledge crosses a *tool* boundary too. VO:
*"One agent's discovery — one person's, even one tool's — becomes everyone's
starting point. Nobody re-derived the route-boundary rule. Nobody went confidently
wrong."*

### Act 5 — The record (Ledger) · 4:00–5:00
Cut to the **Ledger** — the org-wide list of everything the fleet just did. Filter
**cross_boundary = true** → the reuse events that crossed a person or a tool. Drill
into one event: **produced-by → consumed-by**, the specialist (Jensen), the doc,
the sessions, why it matched. Pull back to the aggregate; let "tokens saved" sit
there understated (ROI banked — *"we'll get to the dollars another day"*). Close on
the north-star line: *"Mission Control that observes the fleet, routes the right
specialist, and remembers across every agent, person, and tool. That's the company
brain — and no single vendor can show it to you."*

---

## 4. What's real vs staged (honesty box)

Say this if a skeptic asks; keep it the same across both cuts.
- **Real:** the Sessions roster + live activity lines; the Library docs and their
  content; the `/tf` routing to Jensen; the fix and the regression test on the demo
  branch; the Ledger rows and provenance.
- **Seeded:** the five **Profile shells** (Jensen et al.) and their historical
  invocation counts — but each is linked to *real* produced docs.
- **The one beat to be careful with:** *instant* push of Atlas's fresh decision to
  Bree's **already-running** session (Act 4 / the 2-min 1:05 beat). See §5 — film it
  via the honest fallback unless the knowledge-bus push is built.
- **ROI:** any token/$ number shown is *derived* from doc structure (see
  `taskforce-session-savings-math`), not asserted — and it is intentionally not the
  headline here.

---

## 5. What must be live to film (dependencies)

> **Demo-work build status (2026-06-17).** Three of the gaps below are now built
> (tagged `[DEMO WORK]`, revert the merge to undo):
> - **`tf-fleet.sh` — the fleet knowledge bus** + **`tf-capture.sh` — live decision capture**, both as new `/tf` beats: EnderAI PR **#177**.
> - **Profile pill on the Sessions card**: EnderAI-frontend PR **#340**.
>
> To install the updated skill for filming: `bash scripts/taskforce-skill/install.sh`
> from the PR #177 branch (or after merge). The pill needs sessions whose
> `specialist_slug` is set; the bus needs the fleet-mates in the same fleet
> session. Run with `TASKFORCE_DEMO=1` for the seeded library.

Marked: ✅ ships / built · 🟡 server/UI surfacing on the Mission-Control roadmap ·
🔶 needs the discover directive channel.

| Need | Beat | Status / action |
|---|---|---|
| Multi-agent roster, status, tool chip, branch, live activity line | Sessions, Act 1 | ✅ `FleetPage` renders all of this today. Pin friendly names (Atlas/Bree/Cy) via rename. |
| Shared context drawer | Act 1, Act 4 | ✅ exists (`SharedContextDrawer`). Confirm it shows the fleet's recent docs. |
| Profiles grid + Jensen detail + `/tf` routing line | Profiles, Act 2 | ✅ ships (seed per `taskforce-agents-demo-handoff.md`). |
| Library doc content + deep-link anchors | Library, Act 3 | ✅ shipped. |
| **Referenced-by appended live** | 0:40 / Act 3 | ✅ behavior exists (`/reference`); confirm it renders without refresh. |
| **New nuance captured into a doc live** | Act 3 | ✅ **built** — `tf-capture.sh` (`/tf` Beat 7b, PR [#177]) writes the decision into the Library deterministically this turn (cheap `/observe` structured path), instead of waiting on the async summarizer. |
| **Profile pill on the Sessions card** | Act 1 polish | ✅ **built** — PR [EnderAI-frontend #340] renders `specialist_slug`/name as a violet pill on each agent row. Needs sessions whose `specialist_slug` is populated (the routed-profile demo seed) to appear. |
| **Collision badge** ("Atlas & Bree both editing billing.py") | Act 1 | 🟡 still roadmap (needs `files_touched` on the fleet response + overlap detection). Without it, the two activity lines already show the overlap; narrate it. |
| **Fresh decision reaches a fleet-mate** | Act 4 / 1:05 | ✅ **built** — `tf-fleet.sh` (`/tf` Beat 4b, PR [#177]) is a client-side **knowledge bus**: each `/tf` turn pulls your fleet-mates' active docs and surfaces them (🛰). It's a pull per turn (one discover cycle), **not** a realtime push — film Bree's *next* `/tf` after Atlas captures; don't claim "live telepathy." The server push/directive channel stays unbuilt. |
| Ledger list + cross_boundary filter + per-event provenance | Ledger, Act 5 | ✅ ships (`/v2/ledger` supports `cross_boundary`, `specialist`, `client`, `event_id`). |
| Cross-tool row in the Ledger (optional) | Act 4/5 | ✅ data-wise — run one agent on **Codex** so a real Claude↔Codex row exists. |

**Recording discipline** (from `taskforce-demo-prep-checklist.md`): pre-warm the
backend; demo + real isolation per `is_demo`; browser ≥110%, terminal ≥16pt; pin
agent display names before rolling so the board reads cleanly.

---

## 6. Open decisions — verify, Alex

1. **Fleet size for the 5-min:** 3 agents (Atlas/Bree/Cy) or add Dot for a fuller
   board? 3 is cleaner; 4 looks more like a "fleet." *(Impact: low.)*
2. **Cross-tool seam:** run one agent on **Codex** (lights up the Ledger
   cross-boundary + cross-tool row, sharpens the moat) vs. all-Claude (simpler,
   matches "2–4 Claudes"). *Recommend Codex for one agent in the 5-min only.*
   *(Impact: medium — it's the difference between "my fleet" and "the company
   brain.")*
3. **Act 4 collaboration beat:** build the knowledge-bus push for the instant
   version, or ship with the one-prompt-latency fallback (§5)? *(Impact: high — it's
   the most magical beat; the fallback is honest but less flashy.)*
4. **Profile pill on Sessions cards:** worth the small FE add before filming so Act
   1 reads in one glance? *(Impact: medium — pure polish, high visual payoff.)*
5. **Two tasks vs one:** keep Task B (Cy/Orin) for breadth, or go all-billing so
   the whole fleet shares one brain harder? *(Impact: medium — breadth vs.
   intensity.)*
