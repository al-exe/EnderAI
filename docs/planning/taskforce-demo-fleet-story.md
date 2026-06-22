# Taskforce demo — "Mission control for your AI" (2-min & 5-min cuts)

*Created 2026-06-17. **Reframed 2026-06-22** to the canonical north star
(`taskforce-northstar.md`): Taskforce is **Mission control for your AI — the
vendor-neutral control plane that remembers, observes, and steers every agent across
every harness.** Beats rebuilt around **observe → remember → steer → the record**,
and the new **steer-from-web** capability (session inbox) is now a beat. ROI/$ is
banked — mentioned, never the headline.*

*Companions (reuse their seed + scenario, don't re-invent): the single-thread
[`taskforce-demo-cuts-1min-3min.md`](./taskforce-demo-cuts-1min-3min.md), the
specialist/seed brief [`taskforce-agents-demo-handoff.md`](./taskforce-agents-demo-handoff.md),
and the Sessions roadmap [`taskforce-fleet-mission-control.md`](./taskforce-fleet-mission-control.md).*

---

## 0. What this proves

**Without Taskforce: ephemeral agents, siloed per harness.** Your Claude Code memory
does nothing for your Cursor users; the next great harness drops and the org is back
to square 0.

**With Taskforce: one control plane above every harness.** The pitch in one line:

> **Mission control for your AI** — your agents run wherever you like (Claude Code,
> Codex, Cursor); Taskforce sits on top and **observes** the whole fleet,
> **remembers** what each one figures out and routes the right specialist in, lets
> you **steer** any agent from one screen, and keeps every reuse **on the record.**
> Bring your own harness; migrate nothing.

The kernel line (say it if asked): **we never run the agents — the harness does.**
We observe, remember, and steer; we never take the stick. That's why we can sit
above every vendor.

| Verb | Tab / surface | Route | What it proves on screen |
|---|---|---|---|
| **Observe** | **Sessions** (Fleet) | `/v2/fleet` | 3 agents live **across three harnesses** — status, tool chip, branch, live activity line, routed-profile pill. "My whole fleet, every tool, one screen." |
| **Remember** | **Profiles** + **Library** | `/v2/agents`, `/v2/library` | Each agent is routed to a specialist built from the team's captured work; the docs it leans on are real *and* update as it works (Referenced-by + live capture). |
| **Steer** | **Session inbox** | `/v2/fleet/:id` | Type a directive to a running agent from the web; its Stop hook picks it up — no touching the terminal. (Claude/Codex; Cursor is observe-only.) |
| **The record** | **Ledger** | `/v2/ledger` | Every reuse, with provenance — who produced it, who consumed it, which specialist, **which tool.** Filter cross-boundary to watch knowledge cross a person or a harness. |

---

## 1. The cast — one shared world both cuts film from

Real seed in `taskforce-agents-demo-handoff.md` (§2–3); the Stripe branch is
pre-built. Nothing new to invent — but the fleet now spans **three harnesses** to
prove neutrality.

**Repo / branch:** `taskforce-claude` backend · `demo/stripe-double-charge`
(the pre-built branch where the WAL dedupe runs *after* dispatch — the bug).

**The fleet (Sessions board):**

| Agent | Harness | Profile routed | Task | Steerable? |
|---|---|---|---|---|
| **Atlas** | **Claude Code** | **Jensen — Billing Reliability** | *Hero:* "Stripe double-charges on plan upgrades — webhook retries get fulfilled twice. Fix it." | ✅ |
| **Bree** | **Codex** | **Jensen — Billing Reliability** | *Companion (delivered via the steer beat):* "Lock it in — add the regression test proving dedupe happens before dispatch." | ✅ |
| **Cy** | **Cursor** | **Orin — Agent Infrastructure** | *Independent:* "The Stop hook isn't appending Referenced-by entries — fix it." | ❌ observe/capture only |

Three harnesses, one repo. Atlas + Bree share the **same specialist and docs** (the
collaboration + cross-tool moment). Cy runs a different domain **on Cursor** — proof
the board is a real cross-vendor fleet *and* an honest note that Cursor we can watch
and capture from, just not steer yet.

**The Library docs in play** (all seeded, all clickable):
- `stripe-webhook-idempotency-strategy` — the hero doc: 2026-04-11 incident + the
  decision *"WAL at the route boundary, before dispatch; handlers are not individually
  idempotent."* (anchors `decision-wal-table`, `incident-2026-04-11`)
- `debugging-stripe-webhook-flakes` — Jensen's ops playbook.
- `stripe-plan-upgrade-regression-coverage` — what Bree's test is built from.
- `claude-code-taskforce-hook-setup` / `referenced-by-update-policy` — Cy's docs.

**Live document updates (the "remembers, and keeps getting better" beat):**
1. Atlas consults the idempotency doc → a **Referenced-by — Atlas** entry appends. *Shipped.*
2. Atlas hits the *new* nuance — this branch regressed the dispatch **order**, not the
   original incident — and that nuance is **captured into the Library** live
   (`tf-capture`). *This fresh decision is what Bree starts from.*

---

## 2. The 2-minute cut — "Mission control for your AI"

**Goal:** the four verbs as one motion. Atlas (Claude Code) + Bree (Codex).

| Time | On screen | Verb / surface | Real vs staged |
|---|---|---|---|
| 0:00–0:20 | Open **Mission Control**. Three agent cards live **across three harnesses** — Atlas·Claude Code, Bree·Codex, Cy·Cursor — each with status dot, tool chip, branch `demo/stripe-double-charge`, a live activity line, and a violet **profile pill**. VO: *"This is my whole AI fleet — every agent, every tool, one screen. They run in their own harness; Taskforce sits on top."* | **Observe** · Sessions | Real roster (`/fleet`), activity lines, tool chips, profile pill (PR #356) all ship. |
| 0:20–0:50 | Click **Atlas → Jensen, Billing Reliability** → its linked **Library** doc: real 2026-04-11 incident + the WAL-before-dispatch decision. Cut to Atlas's terminal: the **right ~6-line fix**, first try, *citing the decision*. Back to the doc — a **Referenced-by — Atlas** entry appears, and the new dispatch-order nuance is **captured** in live. VO: *"Atlas didn't start cold — Taskforce remembered our past billing fix and routed the specialist in. And the doc got better as it worked."* | **Remember** · Profiles→Library | Routing, doc content, Referenced-by, `tf-capture` all real. |
| 0:50–1:20 | Back on **Sessions**, open **Bree's card → its session inbox**. Type a directive from the web: *"Lock it in — add the regression test asserting dedupe-before-dispatch."* Bree (Codex) picks it up on its next turn, **starting from Atlas's just-captured decision** (the knowledge bus), and writes the test green. VO: *"I steered Bree from right here — without touching its terminal — and it already knew what Atlas figured out."* | **Steer** · Session inbox | Session inbox ships (Claude/Codex). Bus is a pull-per-turn (not realtime) — see §5. |
| 1:20–1:50 | Cut to the **Ledger**. The reuse rows that just happened; hover one → provenance trail (doc → both sessions → specialist → **tool**). Filter **cross_boundary** → the Claude→Codex reuse crossing a *harness*. (Savings sits quietly; not narrated.) VO: *"Every reuse, on the record — across every agent, person, and tool. No single vendor can show you this."* | **The record** · Ledger | Ledger + `cross_boundary`/provenance ship. |
| 1:50–2:00 | Tagline card: *"**Mission control for your AI.** It remembers, observes, and steers — across every harness. **Bring your own harness.**"* | Overlay | — |

**Why it works:** observe → remember → steer → record is *one* motion. Sessions and
the steer beat do the emotional work; the Ledger closes it as a company asset.

---

## 3. The 5-minute cut — the full control plane

Five acts, ~1 minute each. 3 agents, 3 harnesses, deeper drill-downs.

### Act 1 — Observe (Sessions) · 0:00–1:00
Open Mission Control: **3 agents across Claude Code, Codex, and Cursor.** Walk the
cards — status, tool chips, branch, activity lines, profile pills. Open the **Shared
context** drawer (the fleet's common memory). Land the kernel line: *"Three agents,
three different tools, one screen. They run in their own harness — Taskforce doesn't
run them, it sits above them."*

### Act 2 — Remember: the specialists (Profiles) · 1:00–2:00
The **Profiles** grid: Jensen, Orin, Mira… each with domain tags, linked-doc counts,
invocation history. Open **Jensen**: routing triggers, instructions, linked knowledge.
Show the `/tf` line in Atlas's session: *"Routed to Jensen — Billing Reliability
(0.91)."* VO: *"These aren't prompts someone wrote — they're specialists built from
our team's captured work, and Taskforce routes the right one in."* (Honest: profiles
are **seeded** today; auto-**earned** profiles are the next build — see §4.)

### Act 3 — Remember: living documents (Library) · 2:00–3:00
Open `stripe-webhook-idempotency-strategy` — real incident + the WAL-before-dispatch
decision. Cut to Atlas applying the fix, citing `decision-wal-table`. Two updates land
**on camera**: (1) **Referenced-by — Atlas**; (2) Atlas **captures** the new
dispatch-order nuance into the doc (`tf-capture`). VO: *"The knowledge didn't just get
used — it got better. The fleet writes the team's memory as it works."*

### Act 4 — Steer + the handoff (Session inbox + bus) · 3:00–4:00
From the web, open **Bree's session inbox** and send the regression-test directive —
**steering a running Codex agent without touching its terminal.** Bree picks it up,
**inherits Atlas's captured decision** via the knowledge bus, and writes the test
green — *because Atlas already settled it.* Meanwhile **Cy** is fixing the Stop-hook
bug **on Cursor, in parallel** (observed + captured, not steered). VO: *"One agent's
discovery becomes the next one's starting point — across people and across tools.
And I can steer any of them from one place."*

### Act 5 — The record (Ledger) · 4:00–5:00
The **Ledger** — everything the fleet just did. Filter **cross_boundary = true** → the
reuse that crossed a person or a harness. Drill one event: **produced-by → consumed-by**,
the specialist, the doc, the sessions, the **tools** (Claude→Codex). Pull back; let
"tokens saved" sit understated (*"we'll get to the dollars another day"*). Close:
*"Mission control for your AI — it remembers, observes, and steers across every agent,
person, and tool. That's the company's memory, and no single vendor can show it to you."*

---

## 4. What's real vs staged (honesty box)

- **Real:** the cross-harness Sessions roster + activity lines + profile pill; the
  Library docs and their content; `/tf` routing to Jensen; the fix and the regression
  test on the demo branch; `tf-capture`'s live doc write; **the session-inbox steer
  (Claude/Codex)**; the Ledger rows and provenance.
- **Seeded (not yet earned):** the five **Profile shells** and their historical
  invocation counts — linked to *real* produced docs, but hand-seeded. **Auto-earned /
  self-evolving profiles + docs are the *next build*** (`~/dev/docs/self-evolving-knowledge-layer/`),
  **not live** — don't claim auto-evolution; claim capture + Referenced-by + `tf-capture`.
- **The handoff timing:** Bree inheriting Atlas's fresh decision is a **pull on Bree's
  next `/tf` turn** (the knowledge bus), **not** realtime telepathy. Film Bree right
  after Atlas captures.
- **Harness honesty:** Claude Code + Codex can be **steered** (Stop-hook injection);
  **Cursor is observe/capture only.** Put the steer beat on Atlas or Bree, never Cy.
- **ROI:** any token/$ figure is *derived* from doc structure, not asserted — and it
  is intentionally not the headline.

---

## 5. What must be live to film (dependencies)

> **Build status (2026-06-22).** All core beats now ship on `main`:
> - **Knowledge bus + live capture** — `tf-fleet.sh` + `tf-capture.sh` (EnderAI PR **#177**, merged).
> - **Profile pill on Sessions cards** — EnderAI-frontend PR **#356** (merged).
> - **Steer from the web (session inbox)** — `core/taskforce/inbox.py` + the enqueue box on the session-detail page (merged). Smoke-test the Codex/Claude Stop-hook claim before filming.
>
> Install the skill for filming: `bash scripts/taskforce-skill/install.sh`. Run with
> `TASKFORCE_DEMO=1` for the seeded library.

Marked: ✅ ships · 🟡 roadmap polish.

| Need | Beat | Status / action |
|---|---|---|
| Cross-harness roster, status, tool chip, branch, activity line | Observe / Act 1 | ✅ `FleetPage` renders all of it. Pin friendly names; set one agent each to Claude/Codex/Cursor. |
| Shared context drawer | Act 1, Act 4 | ✅ `SharedContextDrawer`. |
| Profiles grid + Jensen detail + `/tf` routing line | Remember / Act 2 | ✅ ships (seed per handoff doc). |
| Library doc content + anchors + **Referenced-by live** | Remember / Act 3 | ✅ shipped (`/reference`); renders without refresh. |
| **New nuance captured into a doc live** | Act 3 | ✅ `tf-capture.sh` (`/tf` Beat 7b, PR #177) writes the decision deterministically this turn. |
| **Profile pill on the Sessions card** | Act 1 polish | ✅ PR #356 (merged). Needs `specialist_slug` populated (the routed-profile seed). |
| **Steer a running agent from the web** | **Steer / Act 4** | ✅ **shipped** — enqueue to `POST /v2/taskforce/session/:id/inbox`; the agent's Stop hook (**Claude/Codex**) claims + re-injects next turn. **Cursor has no injection surface — observe only.** Smoke-test before rolling. |
| **Fresh decision reaches a fleet-mate** | Act 4 | ✅ `tf-fleet.sh` knowledge bus — a **pull per `/tf` turn**, *not* realtime push. Film Bree's turn right after Atlas captures; don't claim "live telepathy." |
| Ledger list + `cross_boundary` filter + per-event provenance | Record / Act 5 | ✅ `/v2/ledger` (`cross_boundary`, `specialist`, `client`, `event_id`). |
| Cross-tool Ledger row | Act 4/5 | ✅ free — Bree on **Codex** gives a real Claude↔Codex row. |
| Collision badge ("Atlas & Bree both on billing.py") | Act 1 | 🟡 roadmap; the two activity lines already show the overlap — narrate it. |

**Recording discipline:** pre-warm the backend; demo/real isolation per `is_demo`;
browser ≥110%, terminal ≥16pt; pin agent display names before rolling.

---

## 6. Open decisions — verify, Alex

1. **Harness mix:** Atlas·Claude / Bree·Codex / Cy·Cursor (3 harnesses = strongest
   neutrality + cross-tool Ledger row). Confirm, or simplify to Claude+Codex only.
   *(Impact: medium — three harnesses is the whole "bring your own harness" pitch.)*
2. **The steer beat:** deliver Bree's regression-test task **via the web session
   inbox** (the "steer" beat) instead of typing into Bree's terminal. *Recommended —
   it's the new, differentiated moment.* *(Impact: high — it's the "steers" half of the
   thesis made literal.)*
3. **Profiles seeded vs earned:** seeded for the demo (fine); narrate earned as
   "coming" or stay silent? *Recommend a one-line "these are built from captured work,
   and they'll soon write themselves" — points at the next build without overclaiming.*
4. **Two tasks vs one:** keep Cy's independent task for fleet breadth, or go
   all-billing for a tighter shared-brain story? *(Impact: medium.)*

---

## 7. How to run it — operator runbook

Helper scripts live next to this doc: [`demo-fleet-seed.sh`](./demo-fleet-seed.sh)
(seed) and [`demo-fleet-reset.sh`](./demo-fleet-reset.sh) (reset between takes).

### 7.0 One-time setup (before the first take)

**A. Install the `/tf` skill** (fleet bus + capture; after PR #177 merge):

```bash
cd ~/dev/EnderAI
bash scripts/taskforce-skill/install.sh
ls ~/.claude/skills/tf            # → SKILL.md tf-discover tf-fleet tf-reference tf-capture tf-savings
```

**B. Seed profiles + library + ledger.** In the **Render Shell** on `EnderAI-backend`
(`cd /app/backend`):

```bash
bash /path/to/demo-fleet-seed.sh --email alexlee4190@gmail.com
```

Verify (Demo mode ON): Profiles = 5 cards, Library = the Stripe docs, Ledger = rows.
Routing smoke test:

```bash
TASKFORCE_DEMO=1 ~/.claude/skills/tf/tf-discover.sh \
  --prompt "Stripe is double-charging on plan upgrades — webhook retries fulfilled twice. Fix it?" \
  --files "app/api/routes/billing.py,app/core/stripe_billing.py" | jq .matched_specialist
# expect: slug "jensen", band medium/high
```

**C. Steer smoke test** (do this before rolling — it's the new beat): with a Claude or
Codex agent running and visible on the Sessions board, open its session-detail page,
enqueue a one-line directive, and confirm the agent re-injects it on its next Stop.
**Cursor will not** — keep Cy off the steer beat.

**D. Recording hygiene:** pre-warm the backend; browser ≥110%, terminal ≥16pt, Demo
mode ON.

### 7.1 Launch the fleet (one terminal per agent, one harness each)

```bash
cd ~/dev/taskforce-claude                 # the demo backend repo
git checkout demo/stripe-double-charge    # the pre-built buggy branch
export TASKFORCE_DEMO=1                    # seeded specialists + docs
export TASKFORCE_HOOKS_DISABLED=1          # /tf is the only injector on camera
# Atlas: claude          (Claude Code)
# Bree:  export TASKFORCE_CLIENT=codex  && codex     (Codex — steerable)
# Cy:    export TASKFORCE_CLIENT=cursor && <cursor>  (Cursor — observe/capture only)
```

New sessions auto-join the **Default** fleet session (so they see each other + the bus
is in scope). Rename each from the Sessions roster (Atlas / Bree / Cy) before rolling.

### 7.2 The run, in order

| # | Agent · harness | Delivered how | Content |
|---|---|---|---|
| 1 | **Atlas** · Claude Code | type in terminal | `/tf Stripe is double-charging some users on plan upgrades — webhook retries are getting fulfilled twice. Fix it?` |
| 2 | **Cy** · Cursor *(parallel)* | type in terminal | `/tf The Stop hook isn't appending "Referenced by" entries after sessions — fix it.` |
| 3 | **Bree** · Codex *(AFTER Atlas confirms)* | **from the web — the steer beat** | enqueue to Bree's session inbox: `Lock in the fix — add the regression test proving the plan-upgrade webhook dedupe happens before dispatch.` |

**Why the order:** Atlas must confirm "yes" so its `tf-capture` writes the decision
into the Library *before* Bree runs. Then **steer Bree from the web** (step 3) — its
next turn pulls Atlas's fresh doc via `tf-fleet` (🛰) and writes the test. It's a pull
on Bree's turn, not realtime — enqueue right after Atlas finishes.

When Atlas finishes, confirm "yes" so the `✍️ Referenced by` writes **and** the
`Captured: …` link land live. The profile pill (PR #356) shows the routed specialist
on each card.

### 7.3 Reset between takes

```bash
# Easy / token-only — clears just this take's captured docs:
bash /path/to/demo-fleet-reset.sh

# Full reset (also consult events + Referenced-by + code + session-inbox messages):
DATABASE_URL='postgresql://…' \
  TASKFORCE_DEMO_REPO=~/dev/taskforce-claude \
  TASKFORCE_DEMO_BRANCH=demo/stripe-double-charge \
  bash /path/to/demo-fleet-reset.sh
```

Deletes this take's captured docs (ids in `~/.claude/taskforce-demo-captures.log`),
and — with `DATABASE_URL` + `psql` — removes non-seeded consult events, strips the
appended "Referenced by" sections, clears pending session-inbox messages, and
git-resets the demo branch. The seeded baseline (profiles, library, ledger history) is
left intact. After it runs: quit each agent, relaunch, pre-warm, roll the next take.

> `DATABASE_URL`: Render → Postgres → "External Database URL". No local `psql`? Use the
> Render-shell Python fallback in [`reset-between-takes.sh`](./reset-between-takes.sh).
