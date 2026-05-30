# Taskforce MCP + Metrics — Investigation Writeup
_Date: 2026-05-21 · Author: alexlee + Claude Opus 4.7 · Audience: anyone touching the V2 document or metrics stack_

## TL;DR

- The Taskforce stack today is two Render services + a React app: **EnderAI MCP** (Node) → **EnderAI backend** (FastAPI) → **EnderAI frontend** (React/Tanstack). Every "meaningful work" agent action flows through three MCP tools — `enderai_begin_document` / `enderai_update_document` / `enderai_finish_document` — which both write the V2 document body **and** fire a separate metrics side-channel call.
- Metrics events are emitted **server-side** by `record_document_*` / `record_usage` helpers in `app/core/metrics/events.py`. They're inserted in the same DB transaction as the document mutation so a failed write doesn't leave orphan events.
- I queried `/v2/metrics?window=30d` against my account today: every non-zero data point lives on **2026-05-20**, the day PR #60 ("Accept `usage` in V2 document MCP zod validators") shipped. Everything before that day reads zero because the MCP server's `.strict()` Zod validator was rejecting any payload with `usage` at the front door, so the backend never saw a usage event.
- One real bug surfaced while tracing: `tokens_consumed.total` only sums `input_tokens` but its `top_models` table sums `input_tokens + output_tokens`. The card on the metrics page is underreporting by ~7× against the same metric's per-model breakdown.

---

## 1. The system today

### 1.1 Components

| Component | Repo path | Hosted at |
|---|---|---|
| EnderAI MCP server | `mcp/enderai-api-mcp/` (Node 20+, TypeScript) | Render, `/opt/render/project/src/mcp/...` (URL exposed by the Atlassian MCP gateway as `enderai-api`) |
| EnderAI backend | `demo/full-stack-fastapi-template/backend/` (FastAPI 0.115, SQLModel, Postgres + pgvector) | Render, `https://enderai-backend.onrender.com` |
| EnderAI frontend | `EnderAI-frontend/` (React 18, Tanstack Router/Query, Vite) | `https://www.enderai.xyz/` |

The MCP server is a thin translator: it speaks the MCP JSON-RPC protocol on the inbound side and HTTPS to the backend on the outbound side. It owns a small amount of state (the active case/document for the current session) and the scoring engine that decides "reuse this doc" vs "create a fresh one". Everything that ends up in Postgres is a backend route call.

### 1.2 Tool surface

Today the MCP exposes (`mcp/enderai-api-mcp/src/mcpServer.ts`):

| Tool | Zod schema (`mcpServer.ts`) | Handler (`v2Documents/tools.ts` or inline) | Backend calls |
|---|---|---|---|
| `enderai_session_info` | `{}` | inline | none |
| `enderai_openapi` | `{}` | inline | `GET /api/v1/openapi.json` |
| `enderai_health_check` | `{}` | inline | `GET /api/v1/utils/health-check/` |
| `enderai_request` | escape-hatch HTTP | inline | arbitrary |
| `enderai_begin_case` / `_update_case` / `_finish_case` / `_use_skill` | `BeginCaseArgsSchema` etc. | inline | `/topics`, `/cases`, `/skills` routes |
| `enderai_begin_document` | `BeginDocumentArgsSchema` (now incl. `usage`) | `tools.ts::beginDocument` | list + score, then `POST /v2/documents/` **or** `PATCH /v2/documents/{id}` + `POST /v2/documents/{id}/reused` |
| `enderai_update_document` | `UpdateDocumentArgsSchema` (now incl. `usage`) | `tools.ts::updateDocument` | `PATCH /v2/documents/{id}` + `POST /v2/documents/{id}/usage` |
| `enderai_finish_document` | `FinishDocumentArgsSchema` (now incl. `usage`) | `tools.ts::finishDocument` | `PATCH /v2/documents/{id}` (appends Outcome to Details) + `POST /v2/documents/{id}/usage` |

The case-based tools (`enderai_begin_case` …) are the older topic/case workflow; the document-based tools are the V2 "Taskforce Document" workflow that CLAUDE.md tells agents to prefer.

### 1.3 The deliberate split between body and metrics calls

The MCP handlers call the backend **twice** per write: once to mutate the document body, once to record the metrics side-effect. This is on purpose:

1. The mutation route (`POST /v2/documents/`, `PATCH /v2/documents/{id}`) already fires the **primary** event (`document.created` / `updated` / `finished`) inside the same transaction as the body change. That means `documents_touched` and `reuse_rate` always reflect reality, even if the agent never bothers with `usage`.
2. The metrics-only routes (`POST /v2/documents/{id}/usage`, `POST /v2/documents/{id}/reused`) exist so the agent can attribute **per-turn token consumption + savings** to a specific document without having to bundle that payload into every body PATCH. They're idempotent in spirit (each call inserts a new event) and they live behind the same actor + edit-access checks as the PATCH route.

The handler's `forwardUsage` helper (`tools.ts:281-296`) wraps the side call in a `try/catch` that **swallows the error** and returns `metrics_events: []`. The reasoning: metrics are auxiliary; never fail the user's tool call because the metrics POST 500'd. The cost is real, though — see §5 — because callers can't distinguish "no usage passed" from "usage rejected".

---

## 2. End-to-end paths

### 2.1 `enderai_begin_document` — create-or-reuse

```text
agent → MCP                                      → backend                            → DB / metrics
  begin_document(args)                                                                  
    └─ BeginDocumentArgsSchema.parse(args)                                              
         (rejects if .strict and unknown key)                                          
    └─ tools.ts::beginDocument                                                          
        ├─ if args.document_id:                                                         
        │     GET /v2/documents/{id}              → readV2Document                       
        │     plan + apply self-heal patch         → PATCH /v2/documents/{id}            → V2Document row updated
        │     POST /v2/documents/{id}/reused       → record_document_reused              → metrics_event(document.reused)
        │       payload: { band: "explicit", usage }                                       + metrics_event(tokens.saved.reuse)
        │                                                                                  + (if usage) metrics_event(tokens.consumed) + tokens.saved.*
        │                                                                                  
        ├─ elif args.force_new:                                                          
        │     POST /v2/documents/                  → create_v2_document                  → V2Document row inserted
        │       (body: title, ai_generated_summary, …)                                     + metrics_event(document.created)
        │     POST /v2/documents/{id}/usage         (if usage)                            + metrics_event(tokens.consumed) + savings
        │                                                                                  
        └─ else (auto): list + score + decide                                            
              GET /v2/documents/                   → list_v2_documents_for_actor          
              decide() picks reuse or create                                              
              same as above for the chosen branch                                         
```

The interesting bit on the auto branch is the **scoring engine** (`scoring/engine.ts`). It computes a congruence score for every candidate document the user owns/can access against the inbound `request_summary` + `files` + `symbols` + `errors` + `contexts`, applies tenant/repo/error-family/terminal-state conflict deductions, then ranks. The top candidate either gets reused (with a self-heal patch tightening its metadata) or the engine creates a fresh doc.

### 2.2 `enderai_update_document` — append progress

```text
agent → MCP                                      → backend                            → DB
  update_document(args)                                                                 
    └─ UpdateDocumentArgsSchema.parse(args)                                             
    └─ tools.ts::updateDocument                                                         
        ├─ resolve target document_id (from args or active session)                     
        ├─ build a V2DocumentUpdate patch from high-level args                          
        │   - summary_points → append to main_body[0].segments                          
        │   - details_sections → upsert by anchor_id into details_markdown_sections     
        │   - commands/files/links/decisions/changes → folded into the appropriate     
        │     Details sections                                                          
        ├─ PATCH /v2/documents/{id}                → apply_v2_document_update            → V2Document row updated
        │                                                                                  + metrics_event(document.updated)
        └─ POST /v2/documents/{id}/usage (if usage)                                     → metrics_event(tokens.consumed) + savings
```

`apply_v2_document_update` (`core/v2_documents.py:2144-2156`) sets the fields that were explicitly passed (uses `model_fields_set` to distinguish "not sent" from "sent as null"), refreshes the token counts on the row, and bumps `updated_at` to "now" **unless** the caller explicitly set `updated_at` (that exception exists for TF-154's click-to-edit dates — see #63).

### 2.3 `enderai_finish_document` — terminal close

Same shape as update; the body PATCH appends an Outcome section to Details with `status`, `outcome`, `validation`, and `follow_ups`, and clears the MCP server's active-document pointer for this session.

### 2.4 Reads

The frontend talks to the backend directly via the React Query layer (no MCP involvement on the read path):

- `GET /v2/documents/` — list, no pagination, filtered server-side by `list_v2_documents_for_actor` to owned + shared docs (live or demo).
- `GET /v2/documents/{id}` — single, returns `V2DocumentPublic` with shares + tokens counts populated.
- `GET /v2/documents/folders/` — folder list for the org/owner.
- `GET /v2/document/shares` and friends — sharing endpoints.

The MCP layer reads documents only as input to scoring (`listV2Documents` inside `beginDocument`) — it never serves reads to the agent directly.

---

## 3. Metrics wiring in detail

### 3.1 Event model

`MetricsEvent` (table `metrics_event`) is the single source of truth. One row per event. Columns of interest:

- `kind: str` — one of `document.created | document.updated | document.reused | document.finished | tokens.consumed | tokens.saved.cache | tokens.saved.summary_only | tokens.saved.reuse`
- `user_id`, `organization_id`, `document_id` (the last is `ON DELETE SET NULL` so deleting a doc doesn't blow away the history)
- `occurred_at: datetime`, `is_demo: bool`
- `model_id`, `pricing_id` (FK to `model_pricing`)
- `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `usd_amount`
- `payload: jsonb` for kind-specific extras (`{ "score": ..., "band": ..., "reasons": [...] }` on reuse, `{ "status": ... }` on finished, etc.)

### 3.2 Emission helpers (`core/metrics/events.py`)

| Function | Inserts |
|---|---|
| `record_document_created` | 1 × `document.created`, plus `tokens.consumed` + `tokens.saved.*` **only if `usage` is passed** |
| `record_document_updated` | 1 × `document.updated`, plus same usage events if present |
| `record_document_finished` | 1 × `document.finished` (with `status` in payload), plus same usage events |
| `record_document_reused` | 1 × `document.reused` (with score/band/reasons + `bootstrap_tokens` in payload) + 1 × `tokens.saved.reuse` sized at the doc's cached `summary_tokens + details_tokens`, plus optional consumed-and-savings from `usage` |
| `record_usage` | `tokens.consumed` + `tokens.saved.*` (cache + summary_only) — **no primary event**. Used by `POST /v2/documents/{id}/usage` |

`_price_usage` looks up `pricing_for(session, model_id, occurred_at)` from `model_pricing` (versioned rows; the catalog has effective_from/effective_to so historical numbers stay reproducible across price changes), then multiplies each tokens-line by the per-Mtok rate. Missing pricing → `usd = 0` but the event still inserts so token counts aren't lost.

The savings sources fire conditionally:
- **cache** — only if `usage.cache_read_input_tokens > 0`
- **summary_only** — only if `usage.view_consulted == "summary"` **and** the doc has a non-zero cached `details_tokens` (the implicit claim is "you would have read details_tokens but you didn't")
- **reuse** — only on the `/reused` path, sized at the doc's cached token counts

### 3.3 Aggregation (`core/metrics/queries.py`)

The read endpoint (`GET /v2/metrics`) iterates the `REGISTRY` (`core/metrics/registry.py`), and for each `MetricDefinition`:

- **Direct-sum metrics** (`tokens_saved`, `tokens_consumed`, `usd_saved`, `usd_consumed`) → `sum_metric_total` sums the configured `field_name` column across the configured `kinds`, scoped to the user + demo flag + window.
- **Composed metrics** (`documents_touched`, `reuse_rate`) → bespoke SQL. `reuse_rate` = `count(document.reused) / count(document.reused + document.created)`. `documents_touched` = distinct `document_id` across the four `document.*` kinds.
- Per-day series (`daily_series`) → `date_trunc('day', occurred_at)` group-by, padded to a continuous range so charts get zero days.
- Per-model breakdown (`top_models`) → group-by `model_id`, only on `tokens.consumed`, sums `input_tokens + output_tokens`.

The frontend (`src/components/V2/Metrics/MetricsPage.tsx`) reads `/v2/metrics?window=…` and `/v2/metrics/definitions`, overrides a few labels client-side, and computes the visible "USD Saved" net card as `usd_offset - usd_spent`.

### 3.4 The `field_name` mismatch

`MetricDefinition.field_name` is typed `Literal["input_tokens", "output_tokens", "cache_read_tokens", "usd_amount"] | None` — exactly one column. That's fine for usd_amount-based metrics, but **`tokens_consumed` sets `field_name="input_tokens"`** even though its description says "Total input + output". The card therefore underreports. The per-model breakdown query (`top_models`) hardcodes `coalesce(input_tokens, 0) + coalesce(output_tokens, 0)` and gets the right answer.

This bug means **the headline `Tokens Used` number on the metrics page is wrong**. My account shows `tokens_consumed.total = 1249` vs `top_models[0].tokens = 8934` for the same window — a 7× understatement.

Cleanest fix is probably to widen `field_name` to also accept a tuple (sum-of-columns) and special-case it in `sum_metric_total` / `daily_series`. Alternative is a `composed=True` definition with bespoke SQL. Either is small.

---

## 4. What I actually found in production today

I hit `GET /v2/metrics?window=30d&scope=personal&demo=false` via the live MCP. Personal scope, no demo:

| Metric | Value | Sanity check |
|---|---|---|
| `documents_touched` | **20** | primary events do land |
| `reuse_rate` | **0.0588** | ≈ 1 reuse per 17 begins |
| `tokens_saved` (total) | **2,764** | 1,321 summary_only + 1,443 reuse, 0 cache |
| `usd_saved` | **$0.0948** | |
| `tokens_consumed` (total) | **1,249** | …but `top_models[claude-opus-4-7].tokens = 8,934` — see §3.4 |
| `usd_consumed` | **$0.017** | only claude-opus-4-7 |

Every non-zero day in the series is **2026-05-20**. Both the 28 days before and the partial day after are flat zero.

That maps to **two root causes**:

### Cause A — the zod gate was eating `usage` until 2026-05-20

PR #60 ("Accept `usage` in V2 document MCP zod validators", merged 2026-05-20 00:16 UTC) added `TaskforceUsageSchema` and plugged it as `usage: TaskforceUsageSchema.optional()` into `BeginDocumentArgsSchema`, `UpdateDocumentArgsSchema`, and `FinishDocumentArgsSchema`.

Before that PR, those schemas were `.strict()` without `usage`. Any agent that followed CLAUDE.md and sent `usage` got the entire tool call rejected with `unrecognized_keys: ["usage"]` at the MCP front door — the backend never saw a usage event, and the agent had to retry without `usage` (which loses the metrics signal) or give up.

The handler-layer unit tests in `v2Documents.tools.test.ts` bypassed `BeginDocumentArgsSchema` and called `beginDocument()` directly, so they kept passing while real callers were blocked. That's why this regression wasn't caught for as long as it was.

### Cause B — agents only sometimes call the V2 document tools at all

Even with the zod fix in place, metrics only move when the agent wraps work in `enderai_begin_document` + `_update_document` + `_finish_document`. A lot of agent work (raw Bash, file edits, gh CLI, the Atlassian MCP, the case-based tools) doesn't touch the V2 document path and so contributes zero to the dashboard.

The CLAUDE.md instruction "Prefer these over the legacy V1 enderai_begin_case workflow and over raw enderai_request when both are available" relies on the agent **remembering** to use them and **knowing its own per-turn token counts**. That second part is the harder one: the LLM itself doesn't see the post-response token usage; the harness (Claude Code / Codex) has to inject it. If it doesn't, the agent has to either guess or omit, and omission means zero attributable savings.

---

## 5. Bugs and gaps worth fixing

| # | What | Where | Effort |
|---|---|---|---|
| 1 | `tokens_consumed.total` sums only `input_tokens` while the description and `top_models` count input+output. | `core/metrics/registry.py:102-109` + `core/metrics/queries.py:sum_metric_total` | small |
| 2 | `forwardUsage` swallows backend errors silently. A 400/422 from `/usage` is indistinguishable from "no usage passed" in the tool response. Add a structured warning to the returned `agent_usage_note` or log on the server side. | `mcp/enderai-api-mcp/src/v2Documents/tools.ts:281-296` | small |
| 3 | No end-to-end test from `createMcpServer` through `client.callTool` for the `usage`-pass-through path. That's why the schema regression (PR #60's fix) wasn't caught earlier. | `mcp/enderai-api-mcp/test/` | medium |
| 4 | Pricing rows: confirm `model_pricing` actually has rows for `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`, and `gpt-5-codex`. If a row is missing, `_price_usage` returns `usd=0` and the event still inserts, which produces "lots of tokens, no USD" rows — easy to confuse with bug #1. | `model_pricing` table | small (data) |
| 5 | Optional: backfill events for pre-2026-05-20 work. Walk `v2_document` rows, synthesize `document.created` and `document.updated` events at the row's `created_at`/`updated_at` with no usage. Documents Touched and Reuse Rate would get a real trend line; Tokens/USD stay zero for those days. | one-shot script | medium |

---

## 6. Reproducing this investigation

```bash
# 1. Backend route definitions
$ grep -n "@router" demo/full-stack-fastapi-template/backend/app/api/routes/v2_documents.py

# 2. Metrics emission
$ ls   demo/full-stack-fastapi-template/backend/app/core/metrics/
events.py  pricing.py  queries.py  registry.py  rollup.py  savings.py  tokens.py

# 3. Metrics read endpoint
$ less demo/full-stack-fastapi-template/backend/app/api/routes/v2_metrics.py

# 4. MCP tool schemas + handlers
$ less mcp/enderai-api-mcp/src/mcpServer.ts            # zod + JSON Schema
$ less mcp/enderai-api-mcp/src/v2Documents/tools.ts    # beginDocument/updateDocument/finishDocument
$ less mcp/enderai-api-mcp/src/v2Documents/client.ts   # HTTP calls to the backend

# 5. Live metrics for the current user (via MCP escape hatch)
$ enderai_request method=GET path=/api/v1/v2/metrics query='{"window":"30d","scope":"personal"}'
```

## 7. References

- PR #60 (zod fix): https://github.com/al-exe/EnderAI/pull/60 — root-cause fix for Cause A
- PR #61: `DELETE /v2/documents/{document_id}` (TF-151 backend)
- PR #63: TF-154 backend (owner can override `created_at` / `updated_at`)
- `/home/alexlee/dev/docs/taskforce-metrics-engine-plan.md` — original design doc
- `/home/alexlee/dev/docs/taskforce-v2-architecture.md` — V2 architecture overview
- `/home/alexlee/dev/docs/taskforce-v2-mcp-document-generation-plan.md` — MCP doc workflow plan
