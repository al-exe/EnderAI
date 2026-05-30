# Taskforce V2 Architecture

Last updated: 2026-05-18

A concise architecture writeup for the Taskforce V2 document lifecycle. V2 replaces the legacy Topic/Case/ContextPack model with a single durable artifact — the **V2 document** — that an agent maintains across a unit of meaningful work. The MCP layer wraps the existing V2 document REST API with a guided three-step lifecycle (`begin → update → finish`), a deterministic congruence engine for reuse decisions, and a self-heal planner that repairs structural drift on reused documents.

This document covers what exists today in `EnderAI/mcp/enderai-api-mcp/src/v2Documents`. It is not a roadmap — open areas are called out at the end.

## 1. High-Level Shape

```
┌──────────────────────────────────────────────────────────────────┐
│                          Agent (Claude)                          │
│                                                                  │
│   enderai_begin_document  ──┐                                    │
│   enderai_update_document ──┤  three guided MCP tools            │
│   enderai_finish_document ──┘                                    │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│              enderai-api-mcp / v2Documents/                      │
│                                                                  │
│   tools.ts        — lifecycle orchestration                      │
│   scoring/        — congruence engine (signals → decision)       │
│   selfHeal.ts     — minimal-PATCH structural repair              │
│   active.ts       — in-process active-document pointer           │
│   client.ts       — thin wrapper over V2 REST                    │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                EnderAI backend — V2 document API                 │
│                                                                  │
│   GET    /api/v1/v2/documents/                                   │
│   POST   /api/v1/v2/documents/                                   │
│   GET    /api/v1/v2/documents/{id}                               │
│   PATCH  /api/v1/v2/documents/{id}                               │
└──────────────────────────────────────────────────────────────────┘
```

The MCP package is the only place reuse-vs-create logic lives. The backend is a CRUD surface; it does not know about scoring, anchors, or working logs.

## 2. Document Data Model

`V2Document` (see `v2Documents/types.ts`) carries both human and agent-maintained fields:

| Field | Owner | Purpose |
|---|---|---|
| `title`, `description` | shared | identification + short blurb |
| `human_summary` | human | preserved by default; only edited when explicitly asked |
| `ai_generated_summary` | agent | rolling executive summary |
| `main_body` | agent | Summary paragraphs; each segment can carry an `evidence_anchor_id` |
| `details_markdown_sections` | agent | Details payload — markdown sections keyed by stable `anchor_id` |
| `details_file_name` | agent | filename for the Details blob |
| `collaborators` | shared | merged set |
| `visibility` | owner | `private` or `organization` |
| `is_demo` | system | isolates demo data from real |
| `created_at`, `updated_at` | system | |

The **Summary / Details split is the central contract**. `main_body` segments cite `details_markdown_sections` by `anchor_id`. This is what lets the frontend render a scannable summary that drills into evidence, and what lets the self-heal planner detect and repair drift.

## 3. Lifecycle Tools

Three guided tools live in `v2Documents/tools.ts`. Each returns an `agent_usage_note` telling the agent what to do next — the workflow is self-describing.

### 3.1 `enderai_begin_document`

Chooses the document for the work and returns an active handle.

Decision tree:

1. **Explicit `document_id`** → read, plan a self-heal patch, apply it, return as `match_confidence: "explicit"`.
2. **`force_new: true`** → skip scoring, create a fresh document, return as `match_confidence: "forced-new"`.
3. **Otherwise** → list current user's V2 documents → run the scoring engine → call `decide()`:
   - `reuse` → read the winner, plan and apply self-heal, return with band + reasons + candidate summaries.
   - `create` → build initial Summary/Details from the request, return with the losing candidates summarized so the choice is auditable.

The returned `match_reasons` and `candidate_summaries` are deliberately user-visible — the agent (and a human reading the doc) can see *why* a particular doc was picked.

### 3.2 `enderai_update_document`

Appends material progress as work develops. Requires an active document (from session state) or an explicit `document_id`.

It builds a single PATCH from whichever inputs are present:

- `summary_points` → de-duped append into `main_body`.
- `details_sections` → explicit anchor-keyed upsert into `details_markdown_sections` (full replace on anchor match).
- Working-log payload (`progress_note`, `commands`, `files`, `links`, `decisions`, `changes`, `open_questions`) → folded into a single timestamped **Working Log** Details section with a fresh anchor.
- Top-level fields (`title`, `description`, `ai_generated_summary`, `collaborators`, `visibility`) only patched when changed.
- `human_summary` is patched **only when the caller explicitly sets it** — preserving the human-owned surface is enforced here, not just by convention.

Calling update with no material changes throws. This is intentional: it forces the agent to either pass evidence or stay silent.

### 3.3 `enderai_finish_document`

Finalizes the document. Upserts an `outcome` Details section containing `status`, outcome narrative, validation results, follow-ups, and an optional closing note. Adds an anchor-linked outcome paragraph to `main_body` unless an identical one already exists. Clears the active-document pointer.

Status values: `done`, `paused`, `blocked`, `superseded`. These live inside the Outcome Details section today — there is no first-class status column on the document yet (see Open Areas).

## 4. Congruence Engine

Reuse decisions are deterministic and explainable. `scoring/` contains the engine; `tools.ts` is just the caller.

### 4.1 Signals

Each signal is a `SignalScorer: (candidate, request) → SignalResult` returning a `strength ∈ [0, 1]` plus a human-readable `reason`. Signals are split into two `kind`s:

**Positive** (default weights sum to 100):
- `title-overlap` (25)
- `file-overlap` (20)
- `error-overlap` (15)
- `symbol-overlap` (10)
- `recency` (10)
- `intent-phrase` (10) — "continue", "follow up", "same issue", etc.
- `anchor-overlap` (5) — overlap with existing Details anchor IDs/headings
- `collaborator-overlap` (5)

**Conflicts** (negative weights, can pull the total deep negative before clamping):
- `tenant-conflict` (-60)
- `repo-conflict` (-30)
- `error-family-conflict` (-25)
- `terminal-state-conflict` (-25)

Conflict signals exist because most false reuses are not "low score" — they're "high score on the wrong axis". A doc about tenant A and a request about tenant B can have huge title/file overlap; the tenant conflict must dominate.

### 4.2 Engine

`scoreCongruence` sums `strength * weight` for each signal, clamps to `[0, 100]`, and assigns a band:

- `high` ≥ 70 → reuse automatically.
- `medium` ≥ 45 → reuse only if no conflict fired **and** the runner-up is more than `ambiguousLeadMargin = 10` points behind.
- `low` < 45 → create.

`decide()` returns a `Decision` with the action, the chosen `documentId`, the full sorted candidate list with scores, and a reason string. The caller surfaces all of that to the agent.

Signals whose strength falls below `weakSignalThreshold = 0.3` are flagged in `weakSignals`. The self-heal planner consumes that list — weak signals are the gaps in the reused document that the new request should fill.

## 5. Self-Heal Planner

`selfHeal.ts:planSelfHeal` produces a minimal `V2DocumentUpdate` patch + a list of applied-fix strings. It runs whenever a document is reused (explicit, scored, or forced reuse via `document_id`).

Fixes, in order:

1. Populate missing `description` from `goal` or `request_summary`.
2. Populate missing `ai_generated_summary` with an agent-maintained stub.
3. Set `details_file_name` from a slug of the title if empty.
4. Merge any new collaborators (case-insensitive de-dupe).
5. Ensure every Details section has a unique non-empty `anchor_id`.
6. Drop `evidence_anchor_id`s in `main_body` that no longer resolve to a Details section (orphaned anchors are silently corrected, not preserved).
7. If `weakSignals` includes any of `file-overlap`, `symbol-overlap`, `error-overlap`, or `anchor-overlap`, **and** the new request brings new content, append a `current-work-<timestamp>` Details section seeded only with the dimensions the doc didn't already cover, and add a matching Summary paragraph.
8. Title repair: only when `request.title` differs meaningfully **and** another patch field is already changing. Standalone title rewrites are too destructive to apply silently.

The planner is intentionally conservative. The principle is *make the document navigable and evidence-backed, don't rewrite it*.

## 6. Summary ↔ Details Evidence Contract

This is the invariant the rest of the architecture defends:

- Every important Summary claim should carry an `evidence_anchor_id` pointing at a Details section.
- Every Details section should have a stable `anchor_id`.
- A Summary segment pointing at a missing anchor is a bug — the self-heal planner drops it on the next reuse.
- The agent never edits `human_summary` unless explicitly asked.

`main_body` is structured (`Paragraph[].segments[]` with optional anchor refs) rather than raw markdown specifically so this invariant can be enforced mechanically.

## 7. MCP Session State

`active.ts` keeps a lightweight in-process pointer:

```ts
{ documentId, title, startedAt, lastUpdatedAt, demo }
```

`begin` sets it; `update` touches `lastUpdatedAt`; `finish` clears it. Every write tool also accepts an explicit `document_id`, so the pointer is opportunistic — hosted MCP instances must not rely on it surviving across processes.

## 8. Demo Isolation

`demo: true` flows end-to-end: it propagates through `MatchRequest`, becomes a `?demo=true` query param on every HTTP call, is stored on the active-document state, and is honored by `enderai_update_document` / `enderai_finish_document` via `args.demo ?? env.state.demo`. Real and demo documents never appear in each other's candidate pool.

## 9. Open Areas

Known gaps, in roughly the order they'd be worth picking up:

- **First-class status field.** Today `status` lives inside the Outcome Details markdown. Promoting it to a column would unlock filtering, list-view affordances, and clean termination-state conflict scoring.
- **Backend matching endpoint.** All scoring runs in the MCP package against a list response. For larger libraries this becomes slow and inconsistent across MCP instances. Moving scoring to `POST /v2/documents/match` (preserving reasons + bands) is the obvious next step.
- **Idempotent working-log merging.** Repeated `update` calls with overlapping content currently create new Working Log sections each time. Deduping by content hash within a short window would prevent log churn.
- **Source refs / activity kind.** `source_refs` and `last_activity_kind` were called out in the original plan as later additions; neither exists yet.
- **Frontend affordances.** The UI doesn't yet visually distinguish agent-maintained sections from human-edited ones; without this, the human/agent ownership rules are only enforced on the write path.

## 10. File Map

```
EnderAI/mcp/enderai-api-mcp/src/v2Documents/
├── index.ts            — barrel re-exports
├── types.ts            — V2Document shape + MatchRequest
├── client.ts           — list / read / create / patch over REST
├── active.ts           — in-process active-document pointer
├── tools.ts            — beginDocument / updateDocument / finishDocument
├── selfHeal.ts         — planSelfHeal
└── scoring/
    ├── index.ts
    ├── types.ts        — SignalName, Decision, CongruenceScore
    ├── config.ts       — DEFAULT_CONFIG: weights, bands, thresholds
    ├── engine.ts       — scoreCongruence, decide
    └── signals.ts      — the twelve default scorers
```

Related planning docs in this directory:

- `taskforce-v2-mcp-document-generation-plan.md` — original design plan; this writeup tracks current implementation against it.
- `library-document-organization-sharing-handoff.md` — adjacent library/sharing concerns.
