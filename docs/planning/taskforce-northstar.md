# Taskforce — North Star

**Status: CANONICAL** (as of 2026-06-21). This is the current product north star.
It **supersedes and replaces**:
- `archive/2026-06-21-northstar-refresh/thesis.md` (the May-30 "living thesis," Addenda A–D)
- `archive/2026-06-21-northstar-refresh/taskforce-north-star-and-proof-plan.md` (the May-30 north star)
- `archive/2026-06-21-northstar-refresh/harness-product-thesis.md` (the Apr-27 "Identity A" harness thesis)

> **Draft note (v1):** written from the 2026-06-21 strategy session and **verified
> against shipped `origin/main` code**. Several calls are still open — see §12.
> Future agents: treat this doc as the source of truth; the three docs above are
> archived and must not be used as current direction.

---

## 1. One line

**Taskforce is the vendor-neutral control plane for a company's AI agents** — the
system of record that sits **above every harness** (Claude Code, Cursor, Codex, and
whatever comes next), capturing what the agents do and injecting the context and
systems they need, so the org's AI work is **observable, attributable, and portable.**

Three registers for three audiences:
- **Vision:** *"the operating system for your company's AI."*
- **Category (precise):** *"the vendor-neutral control plane for AI agents."*
- **Stickiness (buyer):** *"the system of record for agentic work."*
- **Banner:** **Bring your own harness.** Work anywhere; see and steer everything from one place.

---

## 2. The wedge — why this exists

Without Taskforce you have **ephemeral, siloed agents.** Claude Code's memory does
nothing for your Cursor users; the next great harness drops and the org is back to
**square 0.** Per-harness memory is siloed *per vendor* — ephemeral **and**
fragmented. The org needs **one persistent layer across all of them**, and no single
harness will build it: *you can't be neutral while selling one army's harness.*

That layer holds the org's **AI capital — memory, identity, audit** — and its core
promise is **portability**: switch harnesses without starting over.

---

## 3. What Taskforce is — the control-plane / execution-plane dyad

> **Harnesses are the _execution plane_ — they run the agents.**
> **Taskforce is the _control plane_ — identity, memory, audit, observability across all of them.**
> **We never touch execution. That's precisely why we can sit above every vendor.**

The loop is **bidirectional and active** — this is the difference between a control
plane and a passive memory store:

- **Capture (harness → up):** `session_observe`, provenance (`origin_tool`, JWT
  identity), harness/usage stamps, transcript ingest.
- **Inject (down → into the agent):** Stop-hook re-injection (session inbox),
  the `/tf` skill hydrating ContextPacks, the fleet **knowledge bus** surfacing
  fleet-mates' docs, and **web → session-inbox directives.**

We sit *above* the context and do **real work on both legs of the stream** — not
just watch.

---

## 4. The kernel line — the one guardrail

**Taskforce schedules nothing and runs nothing.** The test for every future feature:

> *Does it require us to drive the agent?* If yes, it's the trap.

Driving the agents = becoming a harness (the old "Identity A" / Letta path) =
forfeiting the neutrality that is the **entire** moat. We are the **control plane,
not the kernel.** We remember, attribute, observe, surface, and inject — for whatever
is running.

---

## 5. The moat — because features are cheap

Features are cheap and **will converge** (anyone can clone a Sessions board or a
Library viewer). So the moat is **not features.** It is, in order:

1. **The accruing record** — cross-boundary reuse + provenance + audit history that
   lives in us. Clone-resistant because it is *accumulated, not coded.* This is the
   atom; **keep it compounding even when it is not the marketing headline.**
2. **Default position** — zero-switching-cost adoption ("bring your own harness,
   migrate nothing") → become the default thing agents report to.
3. **Data network effect** — cross-person / cross-tool reuse gets more valuable as
   more agents report.
4. **Structural neutrality** — unavailable to a harness *or* a destination app.

All four are **earned over time, not built in a sprint.** Defensibility is a
**clock, not a wall:** reach default-position + a compounding record before a funded
horizontal player points its MCP at the same lane.

---

## 6. The OS-primitive map — with verified current state (2026-06-21)

| OS primitive | Taskforce surface | State |
|---|---|---|
| Process table (`ps`) | Sessions / fleet board | ✅ shipped |
| Filesystem | Library / documents | ✅ shipped |
| Audit / syscall log | Ledger | 🟡 partial |
| Installed capabilities | Profiles / routed specialists | ✅ shipped (seeded; *earned* is the differentiator, not yet built) |
| Syscall / driver interface | MCP + `/tf` skill + hooks | 🟡 most OS-like & most defensible; underexploited |
| **Identity / permissions** | BYOK + agent_credentials + sharing | ❌ **fragmented — the missing kernel piece; build next** |
| Scheduler | — *the harness* | 🚫 **not ours, and must stay that way** |

---

## 7. Verified harness support — do not overclaim

| Harness | Capture | View | Control (inject directives) |
|---|---|---|---|
| **Claude Code** | ✅ | ✅ | ✅ (skill + hooks + inbox) |
| **Codex** | ✅ | ✅ | ✅ (stop-hook injection) |
| **Cursor** | ✅ | ✅ | ❌ **no stop-hook injection surface — view-only** |

- Identity = **JWT** (harness-agnostic). Harness/client = **self-reported provenance**
  (advisory only).
- Honest one-liner: **"Bring your own harness — full control on Claude/Codex, full
  visibility everywhere."** The Cursor steering gap is real (no injection surface).

---

## 8. Two audiences, one install

- **The IC (user):** value felt **in the harness** — warm starts, the right doc
  surfaced, no re-deriving. The *painkiller* that keeps the skill/hooks installed.
- **The lead/buyer:** value felt **in the web** — fleet visibility, audit, ROI,
  provenance. What gets *bought*.

Motion: **dev installs bottoms-up** (frictionless) → **org buys the control-plane
view top-down.** The web is the **control plane, not a home** — do not over-build it
into a destination (that is drifting into "Macro-lite" and forfeiting the wedge).

---

## 9. Competitive frame — two camps

- **Consolidation / horizontal-hub camp** (e.g., **Macro**): "replace **or**
  integrate" your stack; your *work-data* consolidates **into** a shared store;
  agents **pull** from it via serve-out MCP. Horizontal (email/chat/docs/CRM/PRs).
  **No fleet / no agent-observability.** Memory source = your **human work**.
- **Control-plane camp** (**Taskforce**): instrument the **agents** in place;
  **bidirectional** capture + inject; **fleet-native**; vertical on the agent layer.
  Memory source = **what agents figure out**.

**Convergence:** the feature **maps** will converge (features are cheap); the
**territory** (accrual + position + neutrality) will not — *but only as long as each
side holds its opposite posture.* The day either abandons it (Macro ships a pure
overlay; we ship a workspace), it collapses into a capital/distribution race.

> Full Macro teardown to be filed under `research/` (verified 2026-06-21 against
> macro.com + their open-source repo). Key verified facts: "replace or integrate";
> MCP is serve-out (agent reads Macro), not capture-in; no multi-agent fleet;
> background = scheduled automations only.

---

## 10. Anti-goals (carried forward + sharpened)

1. **No orchestration runtime / scheduler.** Don't drive the agents.
2. **Don't become a destination/workspace.** The web is a control plane, not a home.
   Avoid "Macro-lite."
3. **No deflationary headline.** $/tokens are *proof*, never the hero line.
4. **Don't sell the mechanism.** Capture/store/retrieve are table stakes.
5. **Features ≠ strategy.** Parity is cheap; bias to accrual / position / neutrality / identity.

---

## 11. What this means for the build (near-term bias)

- **Build the identity/permission plane** — the missing kernel piece that makes
  visibility, cross-person reuse, and audit cohere.
- **Keep the reuse/provenance ledger compounding** — the accrual moat — even if it
  is not the headline metric.
- **Close (or honestly scope) the Cursor control gap** — no stop-hook injection today.
- **Move profiles seeded → earned** — auto-compounded from real cases is the real
  differentiator.
- **Treat feature parity as table stakes** — do it cheaply, don't enter a feature war
  with a horizontal incumbent.

---

## 12. Open questions — to nail down with Alex

1. Is `thesis.md` **fully superseded**, or should its competitive analysis live on as
   a separate "living competitive log" rather than be archived wholesale?
2. **Primary category term** — lock "control plane," or lead with "system of record"
   / "operating system" for a given audience?
3. Is the **identity/permission plane** truly the next build, or does
   earned-profiles / the Cursor gap come first?
4. The metric you "backseated" — confirm we **keep the reuse ledger compounding**
   (accrual moat) even while it is *not* the headline.
5. **Scope of "control"** — invest to close Cursor steering, or commit to
   "full control on Claude/Codex, visibility everywhere" and move on?

---

## Provenance
Written 2026-06-21 from the strategy session with Alex. Supersedes (all archived
2026-06-21 under `archive/2026-06-21-northstar-refresh/`): `thesis.md`,
`taskforce-north-star-and-proof-plan.md`, `harness-product-thesis.md`. Current-state
claims verified against `origin/main` (session inbox, `/tf` skill, hooks for
claude/codex/cursor, JWT identity, BYOK).
