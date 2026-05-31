# Taskforce — North Star & Empty-Cell Proof Plan

*Created 2026-05-30 (PM-4). Derived from thesis **Addendum D** (`thesis.md`). This is the "what to build & demonstrate next" doc. Written while Alex is away — **every demo assumption is flagged in §5 for verification.** Adjust the script once assumptions are checked.*

---

## 1. North Star

**The company brain:** *we remember what your company and coworkers figure out — across every tool, person, and content type — and bring it back at the right time.*

- **Category noun (honest substrate):** continual-learning / memory layer.
- **Hero / buyer / moat noun:** the **record + reuse-ROI ledger** — *not* "memory" (commodity), *not* "save tokens" (deflationary, Mem0's pitch).
- **The differentiating line vs. the free commodity:** *AGENTS.md captures what you **write down**; Taskforce captures what your agents **figure out*** — and carries it across people and tools.

### The one metric to optimize — the atom
**Confirmed cross-boundary reuse events.** One event = *an artifact produced in tool X by person P, surfaced + used + confirmed in tool Y by person Q, with provenance, and an original-derivation cost.* This is the number **no single vendor can structurally show**. Everything else (token savings, $, throughput) is a *view* of this atom.

- **Proven base** (mechanical): surfaced + used + provenance + origin cost.
- **Estimated layer** (labeled, buyer-adjustable): the $ valuation and the "saved-original-cost" counterfactual.
- **Flagship cut:** *cross-vendor + cross-person* reuse — the empty cell.

### Anti-goals (write these down so we don't drift)
1. **No orchestration runtime.** We supply the expert context any harness consumes; we never *run / coordinate* the agents. (That = Identity A = becoming Letta = forfeiting neutrality. Thesis §2, D5.)
2. **No vertical lock-in yet.** Stay general ("company brain"); incident-response is *not* our framing (D4).
3. **No deflationary headline.** Token/$ savings are *proof*, never the hero line (D4).
4. **Don't sell the mechanism.** Store/retrieve/consolidate are table stakes; build on a substrate, don't headline it (D1).

---

## 2. The claim under test (what the proof must make undeniable)

> A piece of knowledge one teammate's agent figured out **in one tool** is automatically surfaced and reused by another teammate's agent **in a different tool** — warm, with provenance, and counted as a real reuse event in the ledger.

If we can show **one** of these end-to-end with a real (not seeded) event, the empty cell is no longer a slide — it's a fact. That is the entire job of v1.

---

## 3. Spine vs. black-box (the discipline: *fake the engine, never fake the result*)

### MUST be real (may be crude) — the non-black-boxable spine
1. **Capture in two *different* harnesses** — e.g. Cursor (person A) and Claude Code (person B), both via the existing hosted MCP. *Real, not mocked.*
2. **The provenance "came-from" stamp** — `{origin_tool, user, repo, case_id, timestamp}` genuinely recorded at capture and carried onto the reuse event.
3. **The end-to-end thread** — the provenance shown in the final ledger view is data that *actually traveled* A's capture → store → B's hydration. Every box can be dumb; the thread cannot be staged.

### CAN be black-boxed (naive / stubbed / labeled)
- Store, consolidation, invalidation, decay → use what TF v2 already has (Postgres + congruence match). No Graphiti.
- Retrieval sophistication → adequate is fine; **narrow the scenario so the right artifact surfaces** (don't let commodity recall be the failure point).
- **"Used + confirmed"** → stub it (manual/heuristic mark) and label the event **estimated** on the "used" axis.
- **$ valuation** → illustrative, buyer-adjustable multiplier, labeled **estimated**.
- Profiles may stay partly seeded — *but the A→B reuse event itself must be real* (see §5 assumption A9).

---

## 4. The demo (grounded on the real TF v2 architecture)

**What already exists** (so we build *on*, not from scratch): MCP capture/hydration (`enderai_begin/update/finish_case`, V2 `*_document`, TF-181 `taskforce_session_observe`); Postgres store (`topic`, `case_record`, `case_event`, `v2_document` + shares/folders, `agent_specialist`, `metrics_event`); congruence-scored topic match → `ContextPack`; specialist routing; the metrics-event ledger schema (`DOCUMENT_REUSED`, `TOKENS_SAVED_REUSE`, `usd_amount`). **Cross-vendor is near-free** because capture is MCP-based — any MCP client hits the same backend + identity.

**What's currently *seeded* (the gap to close):** the AgentSpecialists and the metrics dashboard are manually seeded (TF-198). The proof replaces *one* seeded reuse with a real one.

### The scenario (cross-tool + cross-person + profile reuse)
1. **Person A, in Cursor**, works a gnarly task — e.g. *"add idempotency to the Stripe webhook handler."* Through the MCP lifecycle (`begin_case` → `update_case` → `finish_case`) the case is captured with provenance (`origin_tool = cursor`, `user = A`) and links to/compounds a **"Payments" AgentSpecialist** profile.
2. **Person B, in Claude Code**, days later and new to payments, starts a *related* task — *"handle refund webhooks."* On `begin_case`, the backend congruence-matches A's prior case, **routes the Payments specialist**, and hydrates a `ContextPack`. B's agent **starts warm** — it already has A's idempotency pattern, *without B re-deriving or re-asking.*
3. A **real `metrics_event` reuse row** is written: artifact produced in Cursor by A → reused in Claude Code by B, with provenance + a labeled-estimated token-savings figure.
4. **The "it worked" moment (success criterion):** B's agent visibly uses the *specific* decision that originated in A's Cursor session, **and** the Agents/Metrics tab shows that **one real cross-boundary reuse event**, drillable to the single instance with full provenance (came-from-Cursor-by-A → used-in-Claude-Code-by-B), with *proven* vs *estimated* fields clearly split.

### Build tasks (smallest path; sequence)
- **B1. Origin-harness provenance.** Add/confirm a first-class `origin_tool` (harness/client id) stamped at the MCP boundary and carried onto `case_record` + the `metrics_event` reuse row. *(A `harness` usage stamp exists for tokens; verify it covers artifact origin — see A2.)*
- **B2. Real reuse-event emission.** Ensure a real `begin_case` hydration that surfaces A's artifact emits a genuine `DOCUMENT_REUSED`/reuse `metrics_event` (not seeded), tagged with both endpoints' provenance.
- **B3. Cross-user visibility.** Confirm B's `begin_case` can hydrate A's case/profile within a shared workspace/org (V2DocumentShare / topic visibility).
- **B4. Single-instance drill-down view.** A view (extend Agents or Metrics tab) that renders **one** real reuse event with full provenance and the proven/estimated split. This is the deliverable a skeptic clicks into.
- **B5. Scenario content.** The payments case (A's) + the Payments specialist, staged so congruence reliably matches B's related task.

---

## 5. ASSUMPTIONS — **verify these, Alex** (we adjust the script after)

> These are everything I assumed without being able to confirm. Each is tagged with how it affects the demo and where to check.

- **A1 — Two MCP-capable harnesses behave the same.** Assumed **Cursor** and **Claude Code** can both run the `enderai_begin/update/finish_case` workflow against the hosted MCP. *Verify Cursor's MCP support drives the same lifecycle; if not, swap in Codex/Windsurf or use two Claude Code instances as a fallback (weaker — same vendor).* **Impact: high (the cross-vendor spine).**
- **A2 — Origin-tool identity is capturable at the MCP boundary.** Assumed the MCP session can record *which client/harness* connected (or we can add `origin_tool`). *Verify whether `mcp/enderai-api-mcp` session handling exposes client identity; check if `case_record`/`metrics_event` has a usable field or needs a migration.* **Impact: high (provenance stamp = non-black-boxable).**
- **A3 — Two user identities with cross-user hydration.** Assumed A and B are distinct users in one workspace/org, and B's `begin_case` is *allowed* to hydrate A's artifacts (via share/topic visibility). *Verify the sharing/visibility model permits cross-user hydration; confirm `context-packs/build` pulls cross-user cases, not just self.* **Impact: high (cross-person leg).**
- **A4 — Congruence match will surface A's case for B's related task.** Assumed retrieval is adequate for a hand-scoped scenario. *We control the scenario, so we can tune A's case signals to match B's task. Verify topic-match/congruence thresholds; tune content if needed.* **Impact: medium (tunable).**
- **A5 — A real reuse `metrics_event` can be emitted on live hydration.** Assumed the hydration path can write a genuine reuse event, not only the seed path. *Verify `core/metrics/events.py` + the begin_case flow can emit `DOCUMENT_REUSED`/`TOKENS_SAVED_REUSE` on a real match.* **Impact: high (else the ledger stays a puppet show).**
- **A6 — "Used + confirmed" is stubbed (by design).** We mark the surfaced artifact "used" via a manual/heuristic signal and **label that axis estimated**. *Confirm you're OK demoing "used" as estimated for v1.* **Impact: low (intentional).**
- **A7 — Token/$ savings is illustrative, labeled estimated (by design).** Not a measured counterfactual. *Confirm acceptable.* **Impact: low (intentional, on-thesis).**
- **A8 — Audience = internal conviction, recordable.** Assumed we build the scrappiest honest version (you can play both A and B across two real tools), built clean enough to screen-record for investors later — *not* a design-partner's live environment. *Verify the intended audience; a design-partner version needs their workflow/data and is heavier.* **Impact: high (scopes everything).**
- **A9 — Profile may be pre-seeded; the *reuse event* must be real.** Assumed it's acceptable that the Payments specialist is pre-seeded, **provided** the A→B cross-boundary reuse is genuinely captured and counted. *Ideally the seeded profile is at least linked to A's real case. Confirm this is an OK line.* **Impact: medium (defensibility of the demo claim).**
- **A10 — Minimal provenance envelope fields suffice.** Assumed `{origin_tool, user, repo, case_id, timestamp}` is enough to make "across vendors/people" legible. *Verify which already exist on `case_record`/`metrics_event` vs. need adding.* **Impact: medium.**
- **A11 — Same-repo scenario.** Assumed A and B operate on the *same* repo/codebase (so the knowledge is genuinely transferable). *Confirm; cross-repo is a harder, later story.* **Impact: low.**

---

## 6. Decisions still needed from Alex
1. **Audience** (A8) — internal / design-partner / investor? Default taken: **internal-first, recordable.**
2. **Which second harness** (A1) — Cursor assumed; OK, or prefer Codex/Windsurf?
3. **Earned vs seeded profiles** — for v1 the profile can stay seeded (A9); but the *path to earned* profiles (auto-compounded from real cases) is the real differentiator (D5) and should be the v2 of this build. Confirm sequencing.
4. **My role** — this doc is plan-only. Say the word and I'll start on **B1–B4** (origin-provenance + real reuse-event emission + the single-instance drill-down view).

---

## 7. Pointers
- Thesis & rationale: `thesis.md` (esp. **Addendum D**).
- Competitive lens: `research/README.md`, `research/bear-case-validation.md`.
- Architecture: `../architecture-overview.md`, `../topic-case-contextpack-model.md`, `../single-token-auto-hydrating-mcp-workflow.md`.
- Current seeded demo: `backend/app/core/agents/seed.py`, `backend/app/scripts/seed_agents.py` (TF-198) — the thing the proof de-seeds.

## 8. Alex's responses
A1. yes we can make 2 harnesses the same, cursor, codex, and claude code are at our disposal, we can update the enderai mcp to taskforce mcp "tf" and start fresh with this northstar in mind.
A2. pretty sure we can? Each harness agent.md (or claude.md) can instruct which mcp tooling to use, or we only install that specific tooling to make it guaranteed to identify itself correctly. If possible, share 1 set of mcp between all, with instruction to the agent to self-report, or find more elegant native way to do this.
A3. we can provide a JWT token, or some other form of identity, to the agent when it starts up, and that can be used to identify the user in the provenance. We can also set up the sharing/visibility model to allow cross-user hydration. check what's available.
A4. yes.
A5. yes, see A1 for potentially new, clean mcp tooling if it calls for it
A6. We can just start with Used and provenance. Confirmed can become stale again another day. Used does not guarantee still useful.
A7. Sure, dont scream out it's estimated though.
A8. I'd say we should be building this to be used by early alpha testers today, and to demo to VC funds to demonstrate capability and target niche.
A9. Sure. 
A10. Sure.
A11. That's fine. I can give you 2 different users in the same repo same organization.

6 1. See A8. recordable, early users and potential investors.
6 2. Codex and Claude Code. If Codex is lacking capabilies that would make this easier, switch it to Cursor.
6 3. Profiles can be seeded for the sake of a smooth demo, but we should support capabilities of v2 earned profiles.
6 4. write up a comprehensive tech plan. no need to write every line of code, but it should be in components, individually inmplementable, reviewable, and assingnable as we need. Diagrams of architecture would be helpful too. We will use this to give to other agents to build out, so detail in the design doc is key.