# Taskforce — Pipeline Surfaces: Design

*Build design, 2026-05-31. Successor to `taskforce-empty-cell-build-design.md` (TF-199, now merged). Anchored on `taskforce-pipeline-deep-dive.md` (the three-noun model) and `earned-profiles-design.md` (TF-205/C6 spec). This is the agent-facing spec — components are independently implementable, reviewable, and assignable.*

## Context — why this epic exists

TF-199 shipped the **provenance plumbing** for the empty-cell proof: origin/consuming tool (`produced_by_client` / `consumed_by_client`), cross-user org hydration, a `GET /v2/taskforce/cross-boundary-reuse` read API + a standalone view, and a seed scenario.

In review, the standalone "cross-boundary reuse" tab was rejected as **gimmicky / demo-shaped**: a page whose only job is to *announce* "person A made this, person B reused it" reads as built-for-the-demo, not as a production feature. No real product has a "here is proof our value prop is real" page.

The fix is not a better layout for that tab — it's to **stop treating the proof as a destination** and instead make the **pipeline itself the product**, with each tier a real surface and the cross-boundary signal *emerging* from real data (a ledger-row attribute + a metrics dimension), never headlined.

## The model (from `taskforce-pipeline-deep-dive.md`)

Three data nouns already exist; they form a **distillation chain**, with a fourth surface (analytics) reading over tier 0:

```
  LEDGER            →  LIBRARY            →  PROFILES         METRICS
  (MetricsEvent)       (V2Document)          (AgentSpecialist) (rollup over Ledger)
  every session,       sessions deduped      documents          collective totals,
  what was done        into 1 doc per        distilled into     a *read over the
  (append-only,        core thing            packaged expertise  same events*
  source of truth)     (lossy synthesis)     (lossy synthesis)
```

- **Distillation order: Ledger → Document → Profile.** Each step compresses + synthesizes; each is *lossy*.
- **Metrics is not in the chain** — it is the analytics rollup beside tier 0 ("a read over the same events", per the deep-dive).
- This is a textbook **event-sourcing** shape: ledger = event log, documents = cleaned projections, profiles = serving layer, metrics = analytics.

### Why the Ledger earns its keep (the question that drove this design)

The Ledger is **architecturally mandatory, experientially optional**:

- **Provenance floor.** Documents and profiles are *lossy claims*. The only reason to believe a profile is real is that it traces down: profile ← documents ← real sessions ← actual prompts. Remove the ledger and the tower above becomes unfalsifiable. **The proof should EMERGE from drilling tiers, not from a dedicated page.**
- **It already exists as data** (`MetricsEvent`). The question was never existence — only *visibility*.
- **Its one non-gimmicky job is recall, not proof:** a single timeline of the org's AI work *across* Claude Code + Codex + Cursor — searchable. Nothing else does cross-tool recall. That's a real utility.

**Discipline:** the Ledger is framed as **activity / recall / provenance**, *never* as a trophy case. Cross-boundary-ness is *shown* (consumer ≠ owner; tools differ) and *filterable*, never announced.

## Sidebar (decided)

Top→bottom by distillation altitude (most-distilled first), analytics last:

```
Profiles   ← packaged expertise (apex of the funnel)
Library    ← cleaned documents
Ledger     ← raw sessions (NEW)
Metrics    ← rollup over the ledger
```

(Today: Search · Library · Profiles · Metrics · Upgrade in `EnderAI-frontend/src/components/V2/TaskforceShell.tsx`. This epic inserts **Ledger** and reorders to **Profiles · Library · Ledger · Metrics**; Search/Upgrade placement unchanged unless noted.)

**Parallel + linked** (decided): Ledger and Metrics stay separate tabs (different interaction modes — Ledger is a *content/feed* surface; Metrics is *analytics*), but **linked hard** — every metric total drills into the Ledger rows that compose it; every Ledger row drills into the Document it produced/consulted and the Profile that routed it.

## Gaps in TF-199 this epic closes

| # | Gap (verified on `main`) | Closed by |
|---|---|---|
| 1 | `produced_by_client`/`consumed_by_client` read **only** by the cross-boundary query | P1 (ledger read), P3 (metrics dimension) |
| 2 | **No org-wide session read** — only per-`session_id` (`session-log`, `session-savings`) | **P1 — the keystone** |
| 3 | `observe` ships `TASKFORCE_OBSERVE_SHADOW=1` (ledger→doc distillation dormant in real orgs) | called out by P1 (Ledger shows value even pre-distillation); ops flip is separate |
| 4 | C6 earned-profiles is a `NotImplementedError` stub (`core/agents/compounding.py`) | P4 |
| 5 | Standalone cross-boundary tab/endpoint are throwaway demo-shaped | P2 (folded into Ledger), P0 (removed) |

## Components

### P0 — Retire the standalone cross-boundary surface *(me)*
Remove the demo-shaped tab so it can't ship. Net deletion.
- **Frontend** (`EnderAI-frontend`): delete `routes/v2/cross-boundary-reuse.tsx`, `components/V2/Agents/CrossBoundaryReuse*.tsx`, `api/v2CrossBoundaryReuse.ts`; remove the sidebar item; regenerate `routeTree.gen.ts` (**run `npx vite build` — see `[[enderai-frontend-route-tree-gen]]`**).
- **Backend**: keep `GET /v2/taskforce/cross-boundary-reuse` + `cross_boundary_reuse()` for now (P1 supersedes; remove in P1 to avoid a dead endpoint) — OR delete here and build fresh in P1. **Decision: keep the query helper, drop the route in P1.**
- **Acceptance:** no cross-boundary tab; app builds clean (`npm run build` exit 0); no dead imports.

### P1 — Ledger read model + API + tab *(the keystone — split backend/frontend)*
The org-wide session feed. **No first-class Session entity exists** — sessions are emergent from `payload->>'session_id'`. This builds the read model that groups events into session rows.
- **Backend** (`api/routes/taskforce.py` or a new `ledger.py` + `core/metrics/ledger.py`): `GET /v2/taskforce/ledger` → org-scoped, paginated list of **session rows**, each aggregating the events for one `session_id`: actor (display name), `client` (tool), specialist, doc(s) touched, `net_saved_tokens`, `usd`, kind mix (consulted/reused/observed), first/last timestamps, and a **cross-boundary flag** (any consult/reuse where consumer ≠ doc owner, or consuming tool ≠ producing tool). Filters: `actor`, `client`, `specialist`, `cross_boundary=true`, date window, free-text. Supersedes `cross_boundary-reuse` (remove that route here). Reuse `taskforce_session_savings` shapes where possible.
- **Frontend**: `Ledger` tab — a dense, scannable **activity feed / statement** (the "Reuse ledger" direction, generalized to *all* sessions, not just cross-boundary). Each row = one session: who · which tool · what was done (summary) · doc link · saved · when; cross-boundary is a quiet inline marker + a filter, not a headline. Row → drill into the Document (and Profile, if routed). Honors demo mode.
- **Acceptance:** Ledger lists real org sessions across tools; filters work; cross-boundary is a filter not a banner; every row drills to its document; org-scoped (422 for solo users matches existing pattern). Backend unit-tested; FE builds + lints clean.

### P2 — Document & Profile provenance back-links *(the "synthesis" links — split)*
Make distillation legible *in situ* (the production-credible home for the cross-boundary signal).
- **Document surface** (`routes/v2/library.$documentId.tsx`): a quiet **"Sessions / Reused by"** strip — which sessions produced + consulted this doc, by whom, in which tools (GitHub "Used by"-style). Cross-tool/cross-person is *shown* via names + tool icons, never announced.
- **Profile surface** (`routes/v2/agents.$slug.tsx`): **"Earned from"** — the documents (and, transitively, sessions) backing this specialist; distinguish `created_from` seeded vs earned.
- **Backend**: small read endpoints (or extend existing doc/agent detail) for "sessions for document X" and "documents for specialist Y with provenance".
- **Acceptance:** opening a Profile → its Documents → their Sessions is a continuous provenance drill; cross-boundary emerges naturally; nothing seeded-looking. Tested both ends.

### P3 — Cross-boundary as a Metrics dimension *(me)*
Fold the proof into analytics instead of a page.
- **Backend** (`core/metrics/`): a metric/breakdown — e.g. `% of reuse that crossed a person or tool boundary`, and cross-boundary `net_saved_tokens` as a slice of total saved. Reuse the registry pattern.
- **Frontend** (`components/V2/Metrics`): one understated card/breakdown; clicking it deep-links into the Ledger filtered to `cross_boundary=true` (the hard link P1↔P3).
- **Acceptance:** Metrics shows a cross-boundary slice; drill-through lands on the filtered Ledger; no standalone proof page anywhere.

### P4 — Earned-profile compounding *(codex — the document→profile arrow)*
Build the `NotImplementedError` stub per the existing spec. **Full algorithm, guardrails, acceptance already written in `earned-profiles-design.md`** — implement that, don't redesign.
- **Backend**: implement `core/agents/compounding.py::compound_specialists()` exactly per `earned-profiles-design.md` (offline, org-scoped, `dry_run=True` default, `MIN_LINK_SCORE`/`MAX_LINKS_PER_SPECIALIST` guardrails, idempotent upsert, flip `created_from` seeded→earned); worker entry `app/scripts/compound_specialists.py`. Reuse `score_document`, `list_v2_documents_for_actor`.
- **Acceptance:** verbatim from `earned-profiles-design.md` §Acceptance (idempotent; `route_specialist` unchanged; scoring-pattern unit tests + a write-path test).

## Sequencing
1. **P0** (retire the gimmick) — unblocks the reframe, net deletion, fast.
2. **P1** (Ledger spine) — the keystone; everything links to/from it.
3. **P2** + **P3** (the links — docs/profile back-links, metrics dimension) — parallelizable once P1's read model exists.
4. **P4** (earned profiles) — independent track (codex); only depends on the existing design doc, not on P0–P3.

## Verification (end-to-end)
The pipeline is legible as a product when a skeptic can, **without any page that announces it**, traverse: **Profile** (earned from real work) → its **Documents** (distilled from sessions) → the **Ledger** sessions that produced/consulted them (some cross-tool, cross-person) → **Metrics** showing the cross-boundary slice — and every hop is a real, useful surface. The proof *emerges*; nothing is staged.

## Risks / notes
- **Four surfaces over one pipeline risks bloat.** Each earns its place only if the **links between tiers are first-class** — that's the product, not the four pages. Guard against shipping four disconnected lists.
- **Ledger framing is load-bearing:** recall/activity/provenance, never "proof." The moment a row congratulates the user, it's gimmicky again.
- **Shadow mode** still defaults ON — in real orgs the Library may be sparse; the Ledger must be useful *even when documents aren't being written yet* (raw recall stands alone). Flipping `TASKFORCE_OBSERVE_SHADOW=0` in prod is a separate ops decision, not this epic.
- **No Session entity** — P1 builds a *read model* over emergent `session_id` groupings, not a new table (keep capture append-only + cheap). If session rows need their own persisted identity later, that's a follow-up.
- Cross-boundary provenance is already derivable (doc.`owner_id` = producer, event.`user_id` = consumer, `produced/consumed_by_client` = tools) — P1/P2/P3 are *read/surface* work, not new capture.
