> ⚠️ **ARCHIVED 2026-06-21 — historical; NOT current product direction.**
> Superseded by [`../../taskforce-northstar.md`](../../taskforce-northstar.md). Retained for reference only. Future agents: do not treat this as current guidance.

# Taskforce — Core Thesis

*A living document: the core philosophy of Taskforce, evolving over time.*
*~~The **Current Thesis** section is always the latest distilled view.~~ (Superseded 2026-05-30 PM — see ritual.) The **Log** records what changed, newest first, each entry datetime-stamped. **Addenda** (appended after the Current Thesis) carry refinements; the live view = Current Thesis + Addenda − anything marked 🔶 STALE.*

> **Thesis ritual — standing instructions (as of 2026-05-30 PM).** This doc mirrors Taskforce's own memory model: append-only, no hard delete, supersede + mark stale.
>
> **At the start of each session** (before new thesis work): read the **most recent Addendum's "Open questions"** and raise them with Alex first — those are the threads we deliberately left open last session. Treat them as the default agenda unless Alex redirects.
>
> **Whenever you append to this thesis:**
> 1. **Never edit prior content in place.** Add new thinking as a new dated **Addendum** section (in chronological order, after the Current Thesis).
> 2. **Mark every superseded claim 🔶 STALE inline** — leave the original text intact and add a callout immediately after it stating **(a) the datetime, (b) the reason it is stale, and (c) a pointer to what supersedes it.** Never delete.
> 3. **Append a dated, newest-first entry to the Log** noting what changed and what it superseded.
> 4. The **current view** = the founding *Current Thesis* + all later *Addenda*, minus anything marked 🔶 STALE.
>
> ~~Previous ritual: revise Current Thesis in place → bump its *Last updated* stamp → append a Log entry.~~ (Superseded 2026-05-30 PM: in-place revision replaced by append-only + stale-marking, per Alex.)

Started: 2026-05-30 01:46 PDT

---

## Current Thesis

*Last updated: 2026-05-30 01:46 PDT (2026-05-30T08:46Z)*

> **Taskforce is the non-parametric continual-learning layer for AI-assisted engineering — the vendor-neutral memory that makes every team's agents start warm, stop repeating solved problems, and prove what that was worth.**

### 1. Why we exist — the continual-learning bet
Models ship frozen. The leverage is no longer only in bigger weights; it's in *learning from experience between sessions*. Two ways to do that:
- **Parametric** (fine-tuning) — slow, expensive, catastrophic forgetting, owned by the labs.
- **Non-parametric** (memory / retrieval) — cheap, fast, editable, auditable, and winnable by a neutral third party because it doesn't require owning the weights.

Taskforce is the **non-parametric pole**, built for agents that act over long horizons and keep hitting the same problems. Long game: a curated store of *confirmed wins* is also the cleanest dataset for eventual parametric updates — so we sit **upstream of fine-tuning**.

### 2. What we are / are not
We **are** a continual-learning memory layer for coding agents: capture useful work, retrieve it the next time any agent hits something similar.

We are **not**:
- an autonomous-engineering harness (work queues, agents pulling tickets, self-driving factories) — that collides head-on with Devin/Cursor/Copilot and the labs;
- a generic memory API racing to the bottom on a vector DB;
- a dev-productivity-surveillance tool.

### 3. The moat — the seams the labs won't cross
Memory is being absorbed into every harness (Claude Code, Cursor, Copilot), which commoditizes "the place an AI remembers." Our defensible territory is the union of the seams no single vendor will ever own:
- **Vendor seam** — no lab curates context for a competitor's agent.
- **Person seam** — my-machine memory ≠ the team's shared, durable knowledge.
- **Moment seam** — ephemeral session memory ≠ a maintained institutional record.
- **The neutral ROI ledger** — a vendor will never tell you "you'd have spent N tokens re-deriving this," because that's telling you to buy less of them. We will. That's the procurement wedge, and a category we can own.

### 4. The wedge
Beachhead: **production reliability / incident recurrence — "have we seen this before?"** Highest cost of forgetting, intrinsic recurrence, measurable in units buyers already track, and the place agents are most dangerous — memory stops them from confidently doing the architecturally *wrong* thing, not just from re-deriving.
> 🔶 **STALE / de-emphasized — 2026-05-30 (PM-4):** Alex deliberately pulled *back from committing to a specific vertical for now* ("there's a lot to capture" — stay general). The production-incident framing is **dropped as the lead wedge**: TF is *not* an incident-response / prevention product. The recurrence we wedge on is redefined as **re-deriving solved work / re-explaining context every session** (higher-frequency, universal), surfaced under the hero noun **"the company brain."** Incident-recurrence may return later as *one* vertical instance, never the beachhead. Superseded by **Addendum D §4**.

ICP: the **staff+ / platform / reliability lead** at an org running more than one agent — the one human who both *feels* the dev value and *owns* the metrics that roll upward. The land-and-expand motion runs through this person.

### 5. Metrics philosophy — own the undeniable floor
- **Undeniable = legible = single-instance auditable.** A metric counts only if a skeptic can drill into ONE instance and verify it themselves. (This kills time-to-first-useful-action, org-velocity, and every soft aggregate proxy.)
- **The atom is the confirmed-reuse event** — a stored artifact surfaced, used, and confirmed, with provenance. It came from our store and nowhere else. Every metric is a *view* of this one event.
- **Flagship = cross-boundary reuse** (across tools, across people) — the number no single vendor can structurally show.
- **Split proven from estimated.** The proven base (surfaced + used + provenance + original cost) is mechanically logged; the valuation is a transparent, **buyer-adjustable** multiplier on top. The floor is unattackable; the value stays honest.
  > 🔶 **STALE / refined — 2026-05-30 PM:** the proven/estimated boundary is drawn one notch too generously. "Surfaced + used + provenance" is mechanically provable, but **booking "original cost" as *savings* is already a counterfactual** — it assumes reuse displaced full re-derivation (the agent might have gotten it from training data, a search, or a teammate). Redraw the line: *reuse-happened* = proven; *reuse-saved-original-cost* = estimated. Also define how **"used"** is proven (incorporated, not ignored). See **Addendum A4/A5** and the 2026-05-31 metric work.
- **Tokens prove, throughput prices.** Token-savings is the credibility device (mechanical, and it grows as agent spend grows). Throughput / incidents-prevented is the value and pricing story. Invoice on something mechanical (seats/usage); sell on throughput. Stay religiously on the *tool-credit* side of measurement, never the *dev-surveillance* side.

### 6. Two personas, one substrate
The user (dev) and the buyer (check-writer) are different people with different motivations — the normal shape of bottom-up dev tooling, not a flaw. **Unify the substrate, segment the surface:** one event stream, rendered in three denominations, never cross-wired —
- **Dev** → time saved + "you didn't re-break it" + profile credibility
- **Champion** → repeat-incident rate, regression reuse, throughput
- **Buyer** → dollars + risk avoided

Each persona is happy on *their own* surface. The buyer never touching the memory is correct — buyers of infrastructure never touch the mechanism (no VP reads a Datadog trace).

### 7. The flywheel — and how it breaks
**Curated dev value → confirmed-reuse events (one owned substrate) → two loops:**
- **(a) Fast / product loop:** events are *learning signal* → better retrieval & curation → better dev value → more use.
- **(b) Slow / commercial loop:** events → ROI ledger → buyer funds seats → more devs — via a deliberate champion → check-writer handoff.

Two failure modes to respect:
- **Direction:** the input is *curated, reusable knowledge*, not raw use. Uncurated, more use → more junk → worse retrieval → the wheel spins **backward**. Curation (decay, dedup, the confirmation gate as a quality filter) is load-bearing, not polish.
- **Ignition:** the wheel doesn't self-start. Reuse lags use until the store fills, so **seed it by hand** (existing incidents, PRs, postmortems) before it spins on its own.

Black-box the two *surfaces* for focus, but never the shared *substrate* — the confirmed-reuse event lives under both and is where coherence and the moat actually sit.

### 8. Open threads
- **Hero primitive:** "Profiles" (compounding, vendor-neutral operating context that behaves like a teammate who gets sharper) may be a more ownable hero noun than "memory." Is the hero *memory* (infra) or *expertise / profiles* (system-of-record)?
  > 🔶 **RESOLVED — 2026-05-30 PM:** the *category* noun is "continual-learning / memory layer" (ride a16z; it's the honest substrate term), but the **hero / buyer / moat noun is the record + ROI ledger, not "memory"** — memory is the commoditizing mechanism (per §3 and Addendum A1). "Profiles" risks the dev-surveillance third rail (§5) unless scoped to the *work / system*, never the *person*. Superseded by **Addendum A → Resolved**.
- **Champion handoff:** the single seam where bottom-up dev tools live or die — the concrete path from "a dev loves it" to "a lead defends the line item." Needs deliberate design.
- **Exact metric definitions:** the reuse event schema and the proven-vs-estimated line per metric. (Scheduled: 2026-05-31.)

---

## Addendum A — 2026-05-30 (PM session): Mechanism, Competitive Landscape & Build-vs-Buy

*Appended 2026-05-30 PM. This session moved from positioning (the founding Current Thesis above) down into mechanism and competitive reality. Net: the founding thesis holds, but the moat is **sharpened** — it is **not** in the memory operations (those are table stakes); it is in **capture + seams + the ROI ledger**.*

### A1. The memory operations are table stakes, not moat
Consolidation, invalidation, supersession, and retrieval are already shipped by the serious players:
- **Mem0** (Apache-2.0 OSS): LLM fact-extraction + an **A.U.D.N.** cycle (Add / Update / Delete / No-op) for consolidation. Note: it *deletes* obsolete memories.
- **Zep / Graphiti** (Apache-2.0 OSS): a **bi-temporal knowledge graph** that **invalidates rather than deletes** ("old facts are invalidated, not deleted"). Zep now concentrates OSS effort on Graphiti and sells the platform; a contributor CLA keeps relicensing control with Zep.

Through this session, every "our *mechanism* is novel" claim collapsed on inspection, and the moat kept falling back to the same place. **Treat extract / consolidate / invalidate / retrieve as table stakes to clear — never as the differentiator.** (A technical reviewer will put the Zep paper in front of you.)

### A2. a16z "Why We Need Continual Learning" — handle with care
The article says *"retrieval is not learning"* and leans **parametric** (*"the lossy compression is the learning"*), framing memory/retrieval as "external notebooks" / a crutch. It is closer to the **bear case** for a standalone memory layer than a tailwind. Use it for **vocabulary** (the model / harness / memory three layers; "retrieval ≠ learning" as a *product* argument for curating into structure) — **never as endorsement, and never for defensibility** (it makes zero moat claims). The richer "retain / validate / scope / reuse organizational knowledge" framing was from the *comments*, not the article. Survivable because the parametric pole a16z favors is **lab-owned** — we deliberately took the only pole a neutral third party can own, and per-vendor weight-compression never crosses the vendor seam.

### A3. Mechanism model — "CRUD for context," corrected to an append-only ledger
- **Not CRUD — an append-only ledger:** Create · Read · **Consolidate · Invalidate · Decay**. **No hard delete** (it breaks provenance and the system-of-record); "forgetting" = **supersede + decay-at-read**. Hard delete is reserved for a narrow, governed compliance path (secrets / PII / legal).
- **Consolidation is where the learning is** — the non-parametric analog of a16z's "lossy compression" — but per A1 it's table stakes: do it, don't sell it.
- **Invalidation ≠ forgetting.** Decay is gradual / time-based; invalidation is **event-triggered** (code-state changes → bound artifacts go invalid, even with no contradicting fact). Graphiti invalidates on contradiction / recency; the engineering-specific **code-state-triggered** twist is finer and unbuilt — don't oversell it.
- **In-loop = dumb & fast; out-of-loop = smart & slow** (CQRS / LSM-tree shape). In the agent loop, do only two cheap things: a precomputed **read** (inject) and a raw **append** (capture). All consolidation / invalidation / scoring / curation runs **offline** against the store. Forcing function = **latency** (the read sits in the agent's critical path).
- **Sensor, not processor.** TF is *present* at the loop boundary as sensor + injector (the TF-176 hook) but never *computes* there. Separate **observation / trigger** (at the loop) from **compute** (offline).
- **Capture everything, decide at home** — with two cheap **deterministic** exceptions you cannot defer to the backend:
  1. **Scrub secrets / PII at the boundary.** You can't un-leak; shipping raw loop context to the TF backend is an exfiltration + compliance liability for our own ICP. Hygiene, not intelligence.
  2. **Stamp the provenance envelope at capture** (see A4) — ethereal in the loop, un-reconstructable later.

### A4. Provenance & the "provenance envelope"
**Provenance** = the origin and lineage of a stored artifact (standard term: data lineage / SLSA-style attestation). The **provenance envelope** = the origin metadata wrapped around the payload **at capture**: vendor / agent / repo / commit / session / user / timestamp / task. It is:
- **the ledger atom** — cross-tool / cross-person reuse is literally an envelope statement (produced in tool X by person P, reused in tool Y by person Q);
- the **key for code-state invalidation** (which commit was this bound to?);
- the basis for **scoping** (which repo / team does this belong to?).

Lose the envelope and the content is an orphan fact you can neither price, expire, nor scope.

### A5. Injection precision — false-positive tolerance
The bar for an injection is **"beat the agent's native (cold) path"** — which is the *same counterfactual the ROI ledger must measure.* But false positives are not uniform:
- **Obviously-irrelevant** FP → agent discards it; cost ≈ a few tokens → **relaxed** tolerance.
- **Plausibly-wrong** FP (stale or mis-scoped, but looks authoritative) → the agent anchors on a false premise and goes confidently wrong → **worse than cold** → **near-zero** tolerance.

Therefore **injection precision ≈ invalidation + scope correctness**, *not* the relevance threshold. Two knobs: relevance threshold (benign FPs) + invalidation / scoping (malignant FPs). And **don't tune on speed alone** — a wrong injection is *fast*; pair the speed signal with a correctness / outcome signal or the system optimizes toward fast-and-wrong.

### A6. Build-vs-buy line
Both Mem0 and Graphiti are **Apache-2.0** (commercial use clear) and **open-core** (newest value gates to the managed tier — Mem0's paid graph is the tell).
- If leaning on a substrate, **Graphiti's temporal / invalidate-not-delete model fits the append-only ledger better than Mem0's delete-capable A.U.D.N.**, and Graphiti's graph is free vs. Mem0's paid graph. **Borrow Mem0's *extraction pattern* as a learning; drop its delete.**
- **Rule: depend on them only for the commodity (extract / consolidate / store / retrieve). Never build the moat layer — capture, provenance, the ledger — on someone else's data model**, least of all two adjacent companies that could drift toward our seam. *Borrow the engine, own the differentiator.*

### Resolved this session
- **Hero primitive (supersedes §8, bullet 1):** the *category* noun is "continual-learning / memory layer" (ride a16z); the *hero / buyer / moat* noun must **not** be "memory" (commoditizing, per §3 + A1) — lead with **the record + the ROI ledger.** Memory = mechanism; the record / ledger = the category we own.

### Open questions (as of 2026-05-30 PM)
- **Exact metric definitions + the proven/estimated line** (still scheduled **2026-05-31**). Refinement (see §5 stale-mark): *"reused"* is mechanically provable, but *"saved its original derivation cost"* is already a counterfactual. Draw the boundary between **reuse-happened** (proven) and **reuse-saved-original-cost** (estimated); define how **"used"** is proven (incorporated, not ignored).
- **Build-on vs. learn-from Graphiti** — can its data model carry reuse-events + the provenance envelope without a fight? License / CLA dependency risk? Is a graph even the right substrate?
- **Injection correctness signal** — how to measure "the agent ended up correct," not just "warm beat cold on speed," so the trigger isn't tuned toward fast-and-wrong.
- **Secret-scrub mechanism at the boundary** — deterministic-only (regex / entropy / denylist; fits the latency budget) vs. a cheap model pass (fights "dumb & fast"). Current lean: deterministic in-loop + model-based redaction offline before long-term persistence.
- **Champion → check-writer handoff** *(carried from §8)* — still the seam bottom-up dev tools live or die on; not addressed this session.
- **Curation labor & ignition** *(carried from §7)* — who curates; can routine-reuse volume be captured automatically (a byproduct of agent work) rather than by human librarian labor? **Volume of genuine reuse is the master variable** under both the flywheel and the metric count.

---

## Addendum B — 2026-05-30 (PM-2): Competitor research deltas

*Appended after the competitor teardown pass — detailed, evidence-linked writeups live in `~/dev/docs/research/` (start at `README.md`).*

- **Mechanism is table stakes — confirmed harder.** Letta ships **git-versioned memory** (Context Repositories), **"sleep-time compute"** (offline consolidation), **git-merge conflict resolution**, and a **code-verified cost benchmark** (Context-Bench). Reinforces A1: the moat is **capture + seams + ledger**, not mechanism.
- **Measurement reality (corrects the earlier "they don't prove it"):** competitors *do* measure — but all measure **benchmark/synthetic counterfactuals** or **illustrative models**, single-system, **self-reported and non-replicating** (Mem0 re-ran Zep's 84% LoCoMo → **58.44%**). None measures **production cross-boundary reuse with provenance.** The neutral, auditable, cross-tool reuse ledger is still the open slot. (Comparison table in `research/README.md`.)
- **Closest on each axis:** xMemory on **provenance** (first-class lineage / trace-IDs); Letta on **substrate** (git).

### New open questions (PM-2)
- **Per-harness vs cross-vendor — the bear case.** The market is building memory *into each harness* (Letta Code, Cursor, Claude Code) — the opposite of our cross-vendor bet. Validate: do teams run multiple harnesses, feel fragmented-memory pain, and trust a neutral third party? If not, the cross-vendor thesis is at risk.
- **Substrate choice: git vs temporal-graph vs vector.** Letta validates git-based versioned memory; Graphiti the temporal graph; turbopuffer cheap vectors. Which fits the provenance-ledger + invalidation needs?
- **Confirm Letta's scope:** is its memory usable outside Letta agents, or harness-locked?
- **Subconscious / Isara name-collisions** — resolve which entity, and whether on-thesis.

---

## Addendum C — 2026-05-30 (PM-3): Competitive positioning — beat each on one edge

*Appended after the competitor reads (`~/dev/docs/research/`: `letta.md`, `mem0.md`, `xmemory.md`, `infra-vector-dbs.md`). Synthesis: each memory-layer rival maxes **one** axis and is structurally/architecturally kept from at least one other. We beat each on the edge it can't hold; our uniqueness is the **combination none of them has.***

### The takedown — one edge each
| Competitor | Their max axis | Structural/architectural weakness | **Our edge** | The line |
|---|---|---|---|---|
| **Mem0** | Distribution (14M dl, AWS-exclusive, framework-native) | **Deletes** (A.U.D.N.); single-system; no ledger | Neutral cross-vendor **record + reuse-ROI ledger** — sit *above* the memory primitive, don't fight for it | *"A system that forgets can't be your system of record."* |
| **Letta** | Mechanism + research credibility + a coding harness | **Is a harness** → structurally barred from neutrality (same disincentive as the labs) | **Vendor-neutral capture across the harness you already use** | *"We sit across the tools; they want to be one."* |
| **xMemory** | Provenance/lineage idea + correctness (97% F1) | **Single-system** provenance (debug-scope); early, no distribution | Provenance extended to **cross-tool / cross-person reuse-*value* attribution** | *"Lineage of one system → priced reuse across the org."* |

> 🔶 **STALE / refined — 2026-05-30 (PM-4):** the Letta cell's *"Is a harness → structurally barred from neutrality"* overstates it as a **capability** claim — Letta *can* technically serve a cross-vendor team (its memory is API/git-accessible). The accurate, defensible claim is **incentive + trust, not capability**: shipping a competing harness (Letta Code) **structurally disincentivizes** Letta from making cross-vendor memory excellent (it commoditizes its own harness) and **disqualifies it from being *trusted* as neutral** (you can't be Switzerland while selling one army). Milder than a lab's conflict (no frontier model). Rewrite the cell → *"Ships a competing harness → disincentivized from, and untrusted for, neutrality."* See **Addendum D §2**.

### Our unique position (the empty cell)
**Taskforce = the neutral, cross-vendor reuse-ROI ledger / system-of-record** — the layer *above* the memory primitive, *across* the harnesses, that **proves and prices confirmed reuse with provenance, across tools and people.** Mem0 has distribution but not the ledger or a neutral record (it deletes); Letta has the mechanism but is a harness; xMemory has the provenance idea but one system and no reach. The triad — **cross-vendor + cross-person + reuse-ROI ledger** — is the cell no one occupies.

### Discipline (so the takedown is real, not wishful)
"Beat them on our edge" presumes **parity on theirs.** We must be table-stakes-good on the commodity axes (mechanism, provenance, retrieval) — likely by **building on** existing substrate (Graphiti / git / turbopuffer) rather than rebuilding — and spend the differentiation budget on the seam. We cannot win the seam while visibly worse at the basics.

### New open questions (PM-3)
- **Sequencing the takedown:** which edge / whose users do we wedge *first*? (The reliability/incident-recurrence ICP from §4 vs. multi-harness teams feeling Letta/Cursor/Claude-Code fragmentation.)
- **The "assembly" risk → our durable moat *at* the seam.** If one player (or an acquirer) welds Mem0's distribution + xMemory's provenance + Letta's git-portability into a neutral ledger, what's our defense — speed-to-seam, or a **data network effect** (cross-org reuse compounding) that's hard to assemble late? Define the moat that survives *after* we reach the seam.
- **Distribution wedge.** Mem0 won category mindshare via OSS + framework-native + the AWS deal; distribution can beat architecture. What's our distribution path so we're not out-distributed before the ledger matters?
- **Parity-by-building-on:** can we hit mechanism/provenance parity on Graphiti/git instead of rebuilding — and can any of their data models carry our provenance envelope + reuse-event without a fight? (Ties to A6 / B.)
- **Monitoring:** stand up per-competitor watch-signals — Letta decoupling Context Repositories into a standalone git-memory layer; Mem0 going append-only / adding a value ledger / team-shared memory; xMemory + funding + a cross-vendor move.
- *(carried from B)* validate the **per-harness-vs-cross-vendor bear case** before building.

---

## Addendum D — 2026-05-30 (PM-4): Memory-vs-moat, the "company brain" altitude, profiles ≠ orchestration, bear-case evidence & the proof spine

*Appended after a working session that ran from positioning down into the actual TF v2 codebase. Net: the moat is **re-confirmed and re-located** (capture + ledger — the layers around memory), the hero noun is raised to **"the company brain,"** the production-incident beachhead is **dropped for now** (stay general), **agent profiles are folded in as core** (memory, not orchestration), and the first build is scoped: **prove the empty cell with one real cross-boundary reuse event.***

### D1. "Is it memory?" (yes) vs "is the moat the memory ops?" (no) — the three-layer frame
The earlier shorthand "the moat is not the memory mechanism" was imprecise and caused real confusion. Precise version:
- **Category:** TF *is* a memory / continual-learning layer — it does store / retrieve / update / consolidate / invalidate. We never stop being memory.
- **Moat:** none of TF's *defensibility* lives in those operations — they're a closed, domain-agnostic, commodity set five companies ship. Picture **three layers; memory is only the middle:**
  1. **Capture** (upstream / ingestion) — sensor at the loop boundary, across vendors; scrub + stamp provenance *at capture*. Not a storage property.
  2. **Memory** (middle) — store / retrieve / update / consolidate. The commodity. Be table-stakes-good; don't *win* here.
  3. **Ledger** (downstream / accounting) — recognize + price the confirmed-reuse event across tools/people. Not memory; metering + valuation.
- **The tell is the hero word, *ledger*.** A ledger runs on a database but isn't one — its value is the accounting *on top*. TF : a memory store :: Datadog : a log store :: Stripe : a transaction DB. Built on the mechanism; not selling it.
- **Nuance:** of the three moat elements, capture and ledger genuinely aren't memory ops; the **seams** (cross-vendor retrieval) *look* like a retrieval property but their defensibility is **structural neutrality** (who's *allowed* to span vendors), not retrieval quality.

### D2. Letta "barred from neutrality" → "disincentivized from, and untrusted for, neutrality" (refines Addendum C)
"Barred" overstated it as **capability** — Letta *can* technically serve a cross-vendor team (API/git-accessible memory). The real claim is **incentive + trust**:
- **Incentive:** every hour Letta spends making memory great *inside Claude Code/Cursor* commoditizes **Letta Code** and helps competitors → the *same disincentive as the labs* (§3 vendor seam), which Letta *volunteered for* by shipping a harness.
- **Trust/positioning:** you can't be the neutral Switzerland while selling one of the armies (cf. CloudWatch-for-multicloud, GitHub-security-for-GitLab → teams reach for neutral Datadog/Snyk).
- **Calibration:** milder than a lab's conflict — Letta owns no frontier model, so its harness is "just a product," not a model-lock-in flywheel. Rank: pure memory layer (none) < Letta < Anthropic/OpenAI.
- **Watch-signal:** if Letta spins **Context Repositories** out as a standalone harness-agnostic layer and de-emphasizes Letta Code, it *sheds the conflict* and becomes a real neutral rival. (Marked the C cell 🔶 STALE.)

### D3. Bear-case evidence — survivable / partially validated (advances the B+C open question)
Source-linked pass on the three legs (Reddit excluded per the research standard; detail + sources in `research/bear-case-validation.md`):
- **(a) Multi-harness is the norm — supported.** ~59% of devs run 3+ AI tools in parallel; "many run both" Cursor + Claude Code; large enterprises use multi-tool strategies.
- **(b) Cross-tool fragmentation pain is real *and already being fought* — supported.** Per-tool CLAUDE.md + .cursorrules + copilot-instructions; **AGENTS.md** emerged as the neutral cross-tool standard (20k+ repos, now Linux Foundation governance). The pain is validated; the market already rallies to *neutral* standards.
- **(c) Appetite for a neutral cross-vendor layer — strong precedent.** **MCP** adopted by OpenAI/Google/Microsoft, donated to a Linux Foundation fund. Counterweight: enterprise data-governance anxiety about code context leaving to third parties — but that is *our own A3 boundary-scrub problem*, and it hits the harness vendors too.
- **Net + the sharp nuance:** the *proven* fragmentation today is at the **static-config** layer (AGENTS.md) — the **dynamic, learned-memory + ledger** layer is the conspicuously **unbuilt neutral slot.** The line that separates us from the commodity: **AGENTS.md captures what you *write down*; Taskforce captures what your agents *figure out*** — earned, not authored, carried across people and tools.

### D4. The altitude — "the company brain" (raises the hero noun; de-emphasizes the §4 beachhead)
- **"Cross-vendor / cross-user" is the moat, not the headline** — an adjective, not a noun. It belongs in *why-us*, never the hero line.
- **Reject the deflationary axis.** "Stop wasting time/money re-deriving" is an *efficiency/cost* story that **shrinks as inference cheapens** — and it's **Mem0's literal pitch** (">90% token cost saved"). Don't headline the credibility device.
- **Hero noun = "the company brain":** *we remember what your company and coworkers figure out — across every tool, person, and content type — and bring it back at the right time.* Token/time savings + the provenance-ledger sit underneath as **proof + commercial layer** (§5: *tokens prove, throughput prices*; sell the **compounding**, prove it with the tokens).
- **Recurrence, redefined:** not production incidents — the recurrence of **re-deriving solved work / re-explaining context every session, every dev, every tool** (higher-frequency, more universal than incidents). The §4 incident beachhead is **dropped for now** (stay general; see §4 STALE-mark). Candidate page lines: *"your team never solves the same problem twice" / "every agent starts where your team left off."*

### D5. Agent profiles = core (memory); orchestration runtime = trap (harness)
TF v2 ships **AgentSpecialists** ("profiles"): reusable expert-context bundles (linked docs/knowledge, prior invocations, routing signals) that let an agent assume a specialist role.
- **Profile = the company brain at richer granularity** — a flagship cross-team reuse unit ("Team B's Payments-Expert profile, reused warm by Team A in another tool"). *Core, not a feature-add* — and a more legible demo unit than a raw solved-bug.
- **Orchestration *runtime* = the rejected Identity A** (§2: "we are NOT an autonomous-engineering harness"). Worse than feature-creep: a runtime that *runs/coordinates* agents **makes us Letta** — forfeits the neutrality moat (D2).
- **The test for every "does this fit?":** does it make us a **substrate any harness consumes** (core) or a **harness that runs the agents** (trap)? *Profile = memory shaped like an expert; orchestration = being the harness.* We supply the expert; we never run the agent.
- **Caution:** profiles must be **earned** (auto-compounded from real work, not hand-authored), **neutral** (cross-harness), and **reuse-proven** (the ledger) — or they collapse into the custom-GPT / shared-prompt commodity. *(Today they are manually **seeded** for the demo — see D7.)*

### D6. The first build — prove the empty cell (the spine, and what's black-boxable)
- **Spine = one auditable cross-vendor + cross-person reuse event, end to end.** Substrate (capture + provenance) is *subsumed* here, not a separate bet; "used + confirmed" is **stubbed and labeled *estimated***; distribution is **move two**.
- **Discipline: fake the engine, never fake the result.** Black-box freely — the store, consolidation/invalidation, retrieval sophistication, "used" detection, dollar valuation (all naive, labeled). **Cannot black-box** (must be real, may be crude): (1) capture in *two different harnesses*, (2) the provenance "came-from-tool/person" stamp, (3) the end-to-end thread from harness-1 capture → store → harness-2 injection.
- **Adequacy, not parity.** Parity-with-Graphiti is a *sell-time* concern; irrelevant to proving the cell exists.

### D7. Grounded reality from the TF v2 codebase (built vs seeded)
Reading the repo changed the plan:
- **Already real:** capture + hydration is **MCP-based** (`enderai_begin/update/finish_case`, V2 `begin/update/finish_document`, TF-181 `taskforce_session_observe` harness-observe tier) → **cross-vendor is structurally near-free**: any MCP client (Claude Code, Cursor, Codex, Windsurf) hits the *same* backend + identity. Store = Postgres (topic/case/case_event; v2_document + **shares/folders/favorites** → cross-person already modeled; agent_specialist; **metrics_event** = the ledger schema, with `DOCUMENT_REUSED` / `TOKENS_SAVED_REUSE` / `usd_amount`). Retrieval = topic-match + congruence scoring → ContextPack; specialist routing.
- **Currently *seeded*, not earned:** the AgentSpecialists and the metrics dashboard numbers are **manually seeded for the demo** (TF-198; e.g. hardcoded 7-day token-saved targets). *This is the puppet-show risk in the flesh* — today's dashboard shows staged reuse, not captured reuse.
- **The gap the proof must close:** turn the seed into **one real, provenance-stamped, cross-tool + cross-person reuse event** flowing through the existing pipes — and confirm/add a first-class **origin-harness** field on the captured artifact + reuse event (a `harness` usage stamp exists for tokens; the *origin tool of the artifact* needs to be first-class so "across vendors" is legible).

### Open questions (as of 2026-05-30 PM-4)
- **Audience for the first proof** — internal conviction vs design-partner vs investor (gates how staged the scenario may be). *Unanswered; default lean = internal-first, but recordable.*
- **Earned profiles** — cheapest path from *seeded* AgentSpecialists to ones that **auto-compound from real captured cases** (the differentiator in D5).
- **Origin-harness provenance** — add/confirm a first-class "which tool produced this" stamp on the artifact + reuse event.
- **Distribution (move two)** — still open (carried from C): the path so we're not out-distributed before the ledger matters.
- *(carried)* exact metric definitions + the proven/estimated line (the 5/31 work); proving "used = incorporated, not ignored."

---

## Log

### 2026-05-30 (PM-4) — Memory-vs-moat, "company brain", profiles, bear-case, proof spine
Appended **Addendum D**. Headlines: (1) precise **three-layer frame** — capture → memory → ledger; TF *is* memory (category) but the moat is the layers *around* the commodity ops. (2) **Letta "barred" → "disincentivized from / untrusted for" neutrality** (capability vs incentive+trust) — marked the Addendum C cell 🔶 STALE. (3) **Bear case = survivable / partially validated** (multi-harness norm; AGENTS.md + MCP prove neutral-layer appetite; proven pain is *static-config*, the *learned-memory + ledger* slot is unbuilt) — evidence in `research/bear-case-validation.md`. (4) Hero noun raised to **"the company brain"**; **deflationary efficiency framing rejected**; **§4 incident beachhead dropped for now** (stay general) — marked §4 🔶 STALE. (5) **Profiles = core (memory); orchestration runtime = trap (harness / Identity A)** — the substrate-vs-harness test. (6) First build = **prove the empty cell** (one real cross-boundary reuse event; *fake the engine, never the result*). (7) **Codebase reality:** cross-vendor is near-free (MCP-based) and the ledger/profile schemas exist, but **agents + metrics are currently *seeded*, not earned** — the proof must make one reuse event *real*. Supersedes: Addendum C Letta cell; §4 beachhead. Refines §3 (moat location) and §5 (sell-compounding / prove-tokens). New artifacts: `research/bear-case-validation.md`, `taskforce-north-star-and-proof-plan.md`.

### 2026-05-30 (PM-3) — Competitive positioning
Appended **Addendum C**: each of the three memory-layer rivals maxes one axis (Mem0 distribution / Letta mechanism+harness / xMemory provenance-idea) and is kept from at least one other; we beat each on a single edge, and our uniqueness is the combination none holds — **cross-vendor + cross-person + reuse-ROI ledger.** Added the per-competitor edge + one-liner, the "parity-on-their-axis is table stakes" discipline, and new open questions (takedown sequencing, the assembly-risk + durable-moat-at-the-seam, distribution wedge, parity-by-building-on, competitor watch-signals). Links to `~/dev/docs/research/`. Additive to A/B — nothing superseded.

### 2026-05-30 (PM-2) — Competitor research pass
Added evidence-linked teardowns in `~/dev/docs/research/` (Letta, Mem0, xMemory, vector-DB infra; Subconscious/Isara pending disambiguation). Headlines: mechanism is table stakes (Letta has git-versioned memory + sleep-time compute + git-merge conflict resolution); competitors measure self-reported benchmark counterfactuals that don't replicate, none measure production cross-boundary reuse with provenance; **new bear case** — the per-harness-memory trend runs opposite to our cross-vendor neutrality. See **Addendum B**. Nothing in the founding thesis marked stale (all consistent / reinforced).

### 2026-05-30 (PM) — Mechanism & competitive-reality session
Switched the doc to **append-only** (ritual above is now the standing instruction; superseded claims are marked 🔶 STALE inline rather than rewritten) and appended **Addendum A** (mechanism, competitive landscape, build-vs-buy, plus refreshed open questions). Headline shifts:
- **Moat sharpened:** it is *not* the memory operations (consolidation / invalidation / retrieval are table stakes — Mem0 and Zep/Graphiti already ship them); it is **capture + seams + the ROI ledger**.
- **§8 hero-primitive resolved:** category = "memory / continual-learning layer"; hero / buyer noun = **the record + ledger**, not "memory."
- **a16z reframed** as closer to the *bear case* (leans parametric; "retrieval is not learning") — vocabulary only, never defensibility.
- **Mechanism:** append-only ledger (no hard delete; supersede + decay), **in-loop dumb / out-of-loop smart**, **sensor-not-processor**, **capture-everything but scrub-secrets + stamp-provenance at the boundary**.
- **§5 refined:** the proven/estimated line is one notch too generous (a counterfactual hides inside "saved original cost").

Supersedes the §8 hero-primitive thread; refines §3 (where the moat sits) and §5 (the proven/estimated boundary).

### 2026-05-30 01:46 PDT — Founding entry
First distillation, from a brainstorm sparked by a16z's "Why We Need Continual Learning." Converged on:
- **Identity B** (continual-learning memory layer) over Identity A (autonomous-engineering harness). The April harness thesis (`EnderAI/docs/harness-product-thesis.md`, `pre-alpha-product-evaluation.md`) is **superseded** by this document.
- **ROI ledger as a structural moat** — the LLM vendors are disincentivized to build it.
- **Single-instance-auditable metrics** anchored on the confirmed-reuse event, with a buyer-adjustable valuation; flagship = cross-boundary reuse.
- **"Tokens prove, throughput prices."**
- **Unify substrate / segment surface** for the dev≠buyer split.
- **The corrected two-speed flywheel**, with curation controlling direction and seeding controlling ignition.

Next: nail the exact metric definitions (reuse event schema, proven-vs-estimated line per metric) on 2026-05-31.
