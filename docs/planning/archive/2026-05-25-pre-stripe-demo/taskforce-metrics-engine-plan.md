# Taskforce Metrics Engine — Architecture & Plan

Last updated: 2026-05-19

Plan only. No code in this pass.

This document plans a **Taskforce Metrics engine** plus a new **Metrics sub-tab** under `/v2`. Headline metric: **tokens saved**, with derived **USD saved**, over 7-day / 30-day / all-time windows. Each event records the model used and the tokens the model actually consumed (not raw doc size). The engine is designed so additional metrics can be added without schema migrations on the hot path.

Related writeups in this directory:

- [`taskforce-v2-architecture.md`](./taskforce-v2-architecture.md) — V2 document lifecycle.
- [`taskforce-v2-scoring-engine.md`](./taskforce-v2-scoring-engine.md) — congruence engine (becomes a savings source — see §2.3).

## 1. Goals And Non-Goals

### Goals

1. **Surface tokens saved + USD saved** for each user (and roll up by org), across 7d / 30d / all-time.
2. **Save model + actual-consumed token counts at the time of the event**, not raw doc size, so the dollar figure is meaningful.
3. **Persist a versioned pricing snapshot** so historical USD figures don't shift when prices change.
4. **Be extensible.** Add new metrics (reuse rate, documents touched, top models, conflict-block count, …) without altering hot-path schema or touching every endpoint.
5. **Wire the write path** through the existing V2 document endpoints (and MCP lifecycle tools) so it captures real usage from day one.
6. **Ship a Metrics sub-tab** under the Taskforce shell with a card-based, definition-driven layout.

### Non-goals

- **Not** a billing/Stripe integration. `src/api/billing.ts` already exists for subscription state; this is internal "your Taskforce is saving you $X" analytics, not a charge.
- **Not** a generic product-analytics replacement (Mixpanel/Amplitude). We only track Taskforce-mediated work and what it costs/saves.
- **Not** a real-time stream. 1-day rollup latency is fine; the displayed numbers update on a schedule, not per keystroke.

## 2. Tokens-Saved Methodology

This is the conceptual centerpiece. "Saved" needs a comparison point. We define three concrete, *attributable* savings sources and sum them. **Anything we can't attribute, we don't claim.**

### 2.1 What counts as "actually used"

The user's spec was: *"how much context was actually used, not just loaded in."* We translate that into a concrete rule:

> Use the token counts the API call **billed**, not the byte size of the document. Cache reads count at the cache-read rate. Tokens prepared in a tool result but never returned to the model don't count. Raw Details markdown sitting in the doc but not loaded into the turn doesn't count.

In practice, every metrics event that carries token counts gets them from the agent's reported `usage` payload (input, output, cache_read, cache_creation) — the same numbers the model SDK returns. The backend never invents token counts from doc length.

### 2.2 Three attributable savings sources

| Source | Formula | When it fires |
|---|---|---|
| **Cache savings** | `cache_read_tokens × (base_input_rate − cache_read_rate)` | Any turn where the agent reports `cache_read_input_tokens > 0`. |
| **Summary-instead-of-Details** | `(details_full_tokens − summary_loaded_tokens) × base_input_rate`, only counted once per (document, session) | Agent reports it consulted Summary only. |
| **Reuse-on-begin** | `bootstrap_tokens × base_input_rate`, where `bootstrap_tokens` is a constant per-doc estimate from the reused doc | `enderai_begin_document` returns `reused_existing: true`. |

Other candidates intentionally **not** included in v1 because they're not attributable cleanly:
- "Doc shortened a downstream prompt" — depends on the agent harness, not measurable.
- "Conflict signal blocked a bad reuse" — saved future tokens but the counterfactual is too speculative.

These can become metrics later as *observability* (counts, not USD).

### 2.3 Why this is conservative-and-honest

- Cache savings are a real billed delta against base-rate input. The Anthropic pricing page sets cache-read at 10% of base input, so the saving is `0.9 × cache_read_tokens × base_rate`. No estimation.
- Summary-instead-of-Details requires the agent to *say* it consulted Summary only. If it doesn't say so, we don't claim it. This is why the write payload (§5) carries a `view_consulted` flag.
- Reuse-on-begin uses a fixed `bootstrap_tokens` estimate per document (e.g., `min(20_000, details_tokens + summary_tokens)`) — the "you'd have had to re-establish this context from scratch" floor. It's the most assumption-heavy of the three; documented as such in the UI.

The scoring engine (`scoring/engine.ts`, see [`taskforce-v2-scoring-engine.md`](./taskforce-v2-scoring-engine.md)) is the trigger for source #3: a `reuse` decision emits a `document.reused` event carrying `bootstrap_tokens`. Source #3 is, by construction, the only one that depends on the scoring engine actually choosing reuse.

### 2.4 USD calculation

For every token count, USD = `(tokens / 1_000_000) × per_mtok_rate_from_pricing_snapshot`. The pricing snapshot row (§4.3) is FK'd from the metrics event, so the dollar value of a historical event is reproducible even after prices change. Aggregated USD = sum of per-event USD; we never re-price old events against current rates.

## 3. Model Pricing Catalog (May 2026)

These are seed values; the `model_pricing` table (§4.3) is the source of truth at query time.

### 3.1 Anthropic (source: claude.com pricing page)

| Model | Input $/MTok | Output $/MTok | Cache read $/MTok | 5m cache write $/MTok | 1h cache write $/MTok |
|---|---:|---:|---:|---:|---:|
| Claude Opus 4.7 | 5.00 | 25.00 | 0.50 | 6.25 | 10.00 |
| Claude Opus 4.6 | 5.00 | 25.00 | 0.50 | 6.25 | 10.00 |
| Claude Opus 4.5 | 5.00 | 25.00 | 0.50 | 6.25 | 10.00 |
| Claude Opus 4.1 | 15.00 | 75.00 | 1.50 | 18.75 | 30.00 |
| Claude Sonnet 4.6 | 3.00 | 15.00 | 0.30 | 3.75 | 6.00 |
| Claude Sonnet 4.5 | 3.00 | 15.00 | 0.30 | 3.75 | 6.00 |
| Claude Haiku 4.5 | 1.00 | 5.00 | 0.10 | 1.25 | 2.00 |
| Claude Haiku 3.5 | 0.80 | 4.00 | 0.08 | 1.00 | 1.60 |

Modifiers:
- Batch API → 50% off input and output (no cache discount on top — already discounted).
- `inference_geo: "us"` → 1.10× on every token category, for Sonnet 4.5+ / Haiku 4.5+ / Opus 4.5+.
- Fast mode (Opus only) → 6× base ($30 in / $150 out).
- Web search → +$10 per 1,000 searches (separate line item; not a token multiplier).

### 3.2 OpenAI (source: OpenAI pricing page)

Tracked but optional — only relevant if any Taskforce workflow uses OpenAI models.

| Model | Input $/MTok | Output $/MTok |
|---|---:|---:|
| GPT-5.5 | 5.00 | 30.00 |
| GPT-5.4 | 2.50 | 15.00 |
| GPT-5 | 1.25 | 10.00 |
| GPT-4o | 2.50 | 10.00 |

### 3.3 How the catalog is maintained

- Seed migration loads 3.1/3.2 with `effective_from = 2026-05-19` and `effective_to = NULL`.
- When prices change, write a new row with the new `effective_from` and close the previous row's `effective_to`. Old events keep pointing at their original `pricing_id`.
- No automatic scraping. A quarterly seed-update migration is fine; price-changes are rare.

## 4. Data Model

Five new tables. Three are hot-path, two are catalog/registry.

### 4.1 `metrics_events` (hot path — append-only)

```sql
metrics_events
  id                  uuid PK
  occurred_at         timestamptz NOT NULL  -- indexed
  user_id             uuid FK -> users.id   -- indexed
  organization_id     uuid FK -> organizations.id NULL  -- indexed
  document_id         uuid FK -> v2_documents.id NULL  -- indexed
  kind                text NOT NULL  -- enum-like; see §4.5
  model_id            text NULL      -- e.g. "claude-opus-4-7"
  pricing_id          uuid FK -> model_pricing.id NULL
  input_tokens        int NULL
  output_tokens       int NULL
  cache_read_tokens   int NULL
  cache_write_tokens  int NULL
  usd_amount          numeric(12,6) NULL  -- frozen at write time
  is_demo             bool NOT NULL default false
  payload             jsonb NOT NULL default '{}'  -- per-kind extras
  created_at          timestamptz NOT NULL default now()
```

Notes:
- Append-only. No updates, no deletes (except for GDPR-style user deletion which cascades).
- `usd_amount` is **denormalized** so reads don't need to re-join pricing per row. `pricing_id` is the audit trail.
- `payload` holds kind-specific extras (e.g. for `document.reused`: `{score, band, bootstrap_tokens, reasons[]}`).
- `is_demo` matches existing demo isolation on `v2_documents`.

Indexes:
- `(user_id, occurred_at desc)` — primary user-scoped scan.
- `(organization_id, occurred_at desc) WHERE organization_id IS NOT NULL` — org rollups.
- `(kind, occurred_at desc)` — global metric-typed scans (admin/diagnostics).
- `(document_id)` — per-doc detail.

### 4.2 `metrics_daily_rollup` (read path)

```sql
metrics_daily_rollup
  day              date NOT NULL
  user_id          uuid FK
  organization_id  uuid FK NULL
  is_demo          bool NOT NULL
  metric_name      text NOT NULL   -- registry key, see §4.4
  value_num        numeric(20,6) NOT NULL
  value_count      int NOT NULL     -- event count contributing
  updated_at       timestamptz NOT NULL default now()
  PRIMARY KEY (day, user_id, is_demo, metric_name)
```

- Daily granularity is enough for 7d/30d/all-time views (each window aggregates day-level rows).
- Filled by a background job that scans `metrics_events` for the previous day. Idempotent: re-running a day's rollup replaces the row.
- Optional on-write fast-path: increment today's row in the same transaction as the event insert, for "live" 7d numbers. Background job remains the source of truth and runs reconciliation.
- "All time" = `SUM(value_num)` over all rows for the user/metric — fast because rolled up.

### 4.3 `model_pricing` (catalog)

```sql
model_pricing
  id                          uuid PK
  provider                    text NOT NULL  -- "anthropic", "openai", ...
  model_id                    text NOT NULL  -- "claude-opus-4-7"
  effective_from              timestamptz NOT NULL
  effective_to                timestamptz NULL  -- NULL = current
  currency                    text NOT NULL default 'USD'
  input_per_mtok              numeric(10,4) NOT NULL
  output_per_mtok             numeric(10,4) NOT NULL
  cache_read_per_mtok         numeric(10,4) NULL
  cache_write_5m_per_mtok     numeric(10,4) NULL
  cache_write_1h_per_mtok     numeric(10,4) NULL
  batch_discount              numeric(4,3) NULL  -- 0.50 = 50% off
  source_url                  text NULL
  recorded_at                 timestamptz NOT NULL default now()
  UNIQUE (model_id, effective_from)
```

Lookup helper (Python/SQL):

```sql
SELECT * FROM model_pricing
WHERE model_id = :model AND effective_from <= :occurred_at
  AND (effective_to IS NULL OR effective_to > :occurred_at)
ORDER BY effective_from DESC LIMIT 1;
```

### 4.4 `metric_definitions` (registry — code-defined, not in DB)

This is intentionally **code, not a table**. Adding a metric means adding a registry entry, plus optionally a new `kind` value if it's measuring a new event type.

```python
# app/core/metrics/registry.py  (sketch)

@dataclass(frozen=True)
class MetricDefinition:
    name: str                         # "tokens_saved", "usd_saved", ...
    display_name: str
    unit: Literal["tokens", "usd", "count", "ratio", "ms"]
    description: str
    # How to derive value from a metrics_events row, or None if computed from
    # other metrics (composed at read time).
    derive: Callable[[MetricsEvent], Decimal] | None
    # Which event kinds contribute. Empty → never directly populated.
    kinds: tuple[EventKind, ...]
    # Display hints
    presentation: MetricPresentation

REGISTRY: dict[str, MetricDefinition] = {
    "tokens_saved":   MetricDefinition(...),
    "usd_saved":      MetricDefinition(...),
    "documents_touched": MetricDefinition(...),
    "reuse_rate":     MetricDefinition(...),  # computed from two others
    "top_models":     MetricDefinition(...),  # group-by, not scalar
    ...
}
```

The frontend gets the **same** registry shape via a new `GET /v2/metrics/definitions` endpoint, so cards self-describe (unit, label, formatter). Adding a metric = one PR, no DB migration.

### 4.5 Event kinds (initial)

| Kind | Emitted by | Carries |
|---|---|---|
| `document.created` | `POST /v2/documents/`, MCP `begin_document` create path | model_id, usage if known |
| `document.reused` | MCP `begin_document` reuse path | model_id, usage, score, band, bootstrap_tokens |
| `document.updated` | `PATCH /v2/documents/{id}`, MCP `update_document` | model_id, usage, view_consulted, document_id |
| `document.finished` | MCP `finish_document` | model_id, usage, status |
| `tokens.consumed` | Any of the above with a `usage` payload — derived by trigger or app code | model_id, all token cols, usd_amount |
| `tokens.saved.cache` | Derived when `usage.cache_read_tokens > 0` | cache_read_tokens, usd_amount |
| `tokens.saved.summary_only` | When `view_consulted == "summary"` | tokens_avoided, usd_amount |
| `tokens.saved.reuse` | On `document.reused` | bootstrap_tokens, usd_amount |

`tokens.consumed` and the three `tokens.saved.*` events are derived. They can either be:
- **(a) Written explicitly** alongside the source event (recommended — simpler reads, harder to forget a metric retroactively), or
- **(b) Computed via a view** over base events.

Recommend (a): on insert of a `document.reused`, the app code also inserts a paired `tokens.saved.reuse` event. Adds at most 3 inserts per turn; trivial.

## 5. Write Path

### 5.1 Backend endpoint changes (FastAPI, `app/api/routes/v2_documents.py`)

Two endpoints change shape; one is added.

**Changed: `PATCH /v2/documents/{document_id}`** — accept an optional `usage` field in the body:

```python
class V2DocumentUpdate(BaseModel):
    # ... existing fields ...
    usage: TaskforceUsagePayload | None = None  # new

class TaskforceUsagePayload(BaseModel):
    model_id: str                            # "claude-opus-4-7"
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    view_consulted: Literal["summary", "details", "both"] | None = None
    occurred_at: datetime | None = None
```

When present, the route calls `metrics.record_usage_for_document(document, current_user, usage)` which inserts `document.updated` + `tokens.consumed` + any applicable `tokens.saved.*` events.

**Changed: `POST /v2/documents/`** — accept the same optional `usage` field on creation. Emits `document.created` + `tokens.consumed`.

**Added: `POST /v2/documents/{document_id}/usage`** — pure usage event recorder, no doc body mutation. Useful for the MCP layer to fire after each turn without re-PATCHing the document.

```python
@router.post("/{document_id}/usage", status_code=202)
def record_document_usage(
    document_id: UUID,
    payload: TaskforceUsagePayload,
    session: SessionDep,
    current_user: ActiveUser,
    demo: bool = Query(default=False),
) -> None:
    document = get_v2_document_for_actor(session, current_user, document_id, demo=demo)
    if document is None: raise HTTPException(404)
    metrics.record_usage_for_document(session, document, current_user, payload)
    session.commit()
```

**Added: `GET /v2/metrics`** and **`GET /v2/metrics/definitions`** — see §7.

### 5.2 MCP lifecycle tool changes

Mirror the backend change in the existing tool inputs (`v2Documents/tools.ts`):

- `enderai_begin_document` → adds optional `usage?: TaskforceUsage` arg. On reuse, the tool itself derives `bootstrap_tokens` (sum of `details_markdown_sections` tokens, capped at 20k) and forwards it so the backend can emit `tokens.saved.reuse` without the agent doing the math.
- `enderai_update_document` → adds optional `usage?: TaskforceUsage`. Forwards to the new `POST /usage` endpoint (or includes inline in the PATCH body — backend accepts both).
- `enderai_finish_document` → adds optional `usage?: TaskforceUsage`.

The MCP tools never fabricate token counts. If the agent doesn't pass `usage`, the event is recorded without it and just contributes to non-token metrics (counts, reuse rate).

`view_consulted` becomes part of the MCP tool's recommended call pattern: when the agent only reads Summary, pass `view_consulted: "summary"` so source #2 (§2.2) can attribute savings.

### 5.3 Token-counting at the MCP layer

For `bootstrap_tokens` and `summary_loaded_tokens` we need *some* tokenizer. Recommend:
- Use `@anthropic-ai/tokenizer` for Claude models. Already a small dep.
- Cache per-document token counts on the document model (`summary_tokens`, `details_tokens` columns on `v2_documents`, recomputed on PATCH).
- The MCP layer reads those counts from the document it just fetched; doesn't tokenize itself.

This keeps the tokenizer dependency on the backend only.

## 6. Backend Module Layout

```
app/core/metrics/
├── __init__.py
├── registry.py          — MetricDefinition + REGISTRY dict (§4.4)
├── events.py            — record_*() helpers; one per kind family
├── pricing.py           — pricing_for(model_id, occurred_at) lookup
├── savings.py           — three savings calculators (§2.2)
├── rollup.py            — daily rollup job; idempotent
└── queries.py           — read-side aggregations for §7
```

`app/api/routes/v2_metrics.py` — new router, prefix `/v2/metrics`, tag `v2-metrics`.

`app/models.py` — add `MetricsEvent`, `MetricsDailyRollup`, `ModelPricing` SQLModel classes plus the public response shapes (`MetricsResponse`, `MetricSeriesPublic`, etc.).

Migration: one Alembic migration that creates the three tables plus seeds `model_pricing` with §3 values.

## 7. Read Path

### 7.1 Endpoints

`GET /v2/metrics/definitions` →

```json
{
  "data": [
    {
      "name": "tokens_saved",
      "display_name": "Tokens Saved",
      "unit": "tokens",
      "description": "Estimated tokens not sent to the model due to Taskforce reuse, cache hits, and Summary-instead-of-Details.",
      "presentation": { "icon": "spark", "format": "compact-int", "trend": true }
    },
    ...
  ]
}
```

`GET /v2/metrics?window=7d|30d|all&metrics=tokens_saved,usd_saved,...&demo=false` →

```json
{
  "window": "7d",
  "from": "2026-05-12T00:00:00Z",
  "to":   "2026-05-19T00:00:00Z",
  "metrics": {
    "tokens_saved": {
      "total": 184215,
      "delta_vs_prev_window": 0.27,
      "series": [
        {"day": "2026-05-13", "value": 21000},
        ...
      ],
      "breakdown_by_source": {
        "cache":         140000,
        "summary_only":   32000,
        "reuse":          12215
      }
    },
    "usd_saved": { "total": 4.21, "series": [...] },
    "reuse_rate": { "total": 0.34, "series": [...] },
    "top_models": {
      "rows": [
        {"model_id": "claude-opus-4-7", "tokens": 521000, "usd": 6.55},
        ...
      ]
    }
  }
}
```

- Owner-scoped by default; org admins can pass `?scope=organization` to roll up across the org.
- `window=all` skips the date filter.
- Backed by `metrics_daily_rollup`. The fallback path (rollup missing for today) reads `metrics_events` directly and unions.

### 7.2 Cost & latency

- 30d window over rollup table = at most 30 rows × N metrics per user. Sub-millisecond aggregation.
- All-time = same number of rows as days the user has been active; fine until you have multi-year users with daily activity (still <1ms for tens of thousands of rows).
- No need for materialized views beyond the daily rollup.

### 7.3 Frontend client

Adds `src/api/v2Metrics.ts` (auto-generated from OpenAPI spec — already the pattern in this repo). Types come from `openapi-ts.config.ts`.

## 8. Frontend — Metrics Sub-Tab

### 8.1 Routing & shell

- New file `src/routes/v2/metrics.tsx` (TanStack Router file-based route → URL `/v2/metrics`).
- `TaskforceShell` (in `src/components/V2/TaskforceShell.tsx`) gains a "Metrics" nav entry after Library. Sibling to Home / Library / Admin.
- No new layout chrome; reuses the existing Taskforce shell.

### 8.2 IA

```
┌── /v2/metrics ────────────────────────────────────────────────┐
│                                                               │
│  [ 7 days | 30 days | All time ]    [ Personal | Org ▾ ]      │
│                                                               │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐  │
│  │ Tokens saved    │ │ USD saved       │ │ Reuse rate      │  │
│  │ 184k            │ │ $4.21           │ │ 34%             │  │
│  │ ▲ 27% vs prev   │ │ ▲ 19% vs prev   │ │ ▲ 4 pp vs prev  │  │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘  │
│                                                               │
│  ┌─ Trend ───────────────────────────────────────────────┐    │
│  │  (line chart: tokens saved/day over the window)       │    │
│  └───────────────────────────────────────────────────────┘    │
│                                                               │
│  ┌─ Savings by source ──┐  ┌─ Top models ──────────────┐      │
│  │ Cache       76%      │  │ Opus 4.7   521k  $6.55    │      │
│  │ Summary     17%      │  │ Sonnet 4.6 213k  $0.82    │      │
│  │ Reuse        7%      │  │ Haiku 4.5   91k  $0.11    │      │
│  └──────────────────────┘  └───────────────────────────┘      │
│                                                               │
│  ┌─ Documents touched ──┐  ┌─ Conflict signals fired ──┐      │
│  │ 42                   │  │ 3                          │     │
│  └──────────────────────┘  └────────────────────────────┘     │
└───────────────────────────────────────────────────────────────┘
```

### 8.3 Component contract — definition-driven

```
src/components/V2/Metrics/
├── MetricsPage.tsx       — page; fetches definitions + values once
├── MetricsTimeRange.tsx  — 7d/30d/all toggle
├── MetricsScopeToggle.tsx— personal/org toggle (hidden if user has no org)
├── MetricCard.tsx        — generic; renders one MetricDefinition value
├── MetricTrendChart.tsx  — line chart bound to a metric's series
├── MetricBreakdown.tsx   — table for grouped metrics (top_models, by_source)
└── formatters.ts         — compact-int, usd, ratio, ms
```

`MetricCard` does **not** know about specific metrics. It takes `MetricDefinition + MetricValue` and renders. Adding a new metric on the frontend = adding it to the registry on the backend; the page picks it up via `/v2/metrics/definitions`.

### 8.4 Empty states & honesty

- "Connect your MCP / start using Taskforce to see metrics here" for users with zero events.
- Reuse-on-begin savings show an "(estimated)" qualifier; cache + summary savings show "(measured)".
- USD always shown to two decimals; tokens shown in compact notation (`184k`, `1.2M`).

### 8.5 Methodology link

Beneath the Tokens Saved and USD Saved cards, render a small text link:

```
Learn how we calculate savings →
```

It routes to `/v2/metrics/methodology` (new file `src/routes/v2/metrics.methodology.tsx`). The page renders a user-facing version of §2 from this plan — the three attributable sources, what's measured vs estimated, what's intentionally excluded. The content lives in a markdown file under `src/components/V2/Metrics/methodology.md` (imported as a raw string and rendered with the same markdown component the V2 library uses), so editing the methodology is a one-file change. The link uses the existing typography link style; no separate modal or tooltip needed.

## 9. Extensibility — Adding A New Metric End-To-End

Walkthrough for adding "**Conflict signals fired**":

1. **Backend registry** — add an entry to `REGISTRY` in `metrics/registry.py`:
   ```python
   "conflicts_fired": MetricDefinition(
       name="conflicts_fired",
       display_name="Conflict signals fired",
       unit="count",
       description="How often the scoring engine's conflict signals blocked an unsafe reuse.",
       derive=lambda e: e.payload.get("conflicts_count", 0),
       kinds=("document.reused", "document.created"),
       presentation=MetricPresentation(format="count", trend=True),
   )
   ```
2. **Emitter** — the scoring path already attaches `conflicts` to the `document.*` event payload (§4.5). No new emitter needed for this one — that's the point of the generic payload.
3. **Rollup job** — picks up the new metric on next run automatically because it iterates the registry.
4. **Frontend** — nothing. The Metrics page renders the new card because `/v2/metrics/definitions` now lists it.

Total diff: ~10 lines, no migration, no manual frontend work. If the metric needs special rendering (e.g. a bar chart), add a custom component and reference it via `presentation.component`.

## 10. Phased Implementation Plan

Five phases. Each ends at a shippable point.

### Phase 1 — Catalog + tables + seed (backend only)

- Alembic migration: `metrics_events`, `metrics_daily_rollup`, `model_pricing`.
- Seed `model_pricing` with §3.1 + §3.2.
- `app/core/metrics/pricing.py` with `pricing_for()` lookup + tests.
- No endpoints exposed yet.

### Phase 2 — Write path

- `metrics/events.py` + `metrics/savings.py` with the three savings sources.
- Extend `V2DocumentUpdate` with optional `usage`; wire into `PATCH /v2/documents/{id}`.
- Add `POST /v2/documents/{id}/usage`.
- Extend `POST /v2/documents/` to optionally record `usage`.
- Add `summary_tokens` / `details_tokens` columns + recompute on PATCH.
- Tests: each emitter produces the expected event set; pricing snapshot frozen correctly; demo isolation respected.

### Phase 3 — MCP lifecycle plumbing

- `v2Documents/tools.ts` (in `EnderAI/mcp/enderai-api-mcp/`): add `usage?` to all three tool inputs; forward to backend.
- `enderai_begin_document` computes `bootstrap_tokens` from the reused doc on the reuse path and forwards it.
- Tests for tool inputs + forwarding.

### Phase 4 — Read path + rollup

- `metrics/rollup.py` background job (Celery-style; reuse whatever the rest of the backend uses for scheduled jobs).
- `metrics/queries.py` aggregations.
- `GET /v2/metrics` and `GET /v2/metrics/definitions` endpoints.
- Tests: rollup is idempotent; window math correct; org scope honored.

### Phase 5 — Metrics sub-tab

- New TanStack route `routes/v2/metrics.tsx`.
- `TaskforceShell` nav addition.
- Generic `MetricCard` + `MetricTrendChart` + `MetricBreakdown`.
- Wire `/v2/metrics/definitions` + `/v2/metrics` calls (auto-generated client).
- Playwright test for the page rendering cards from a seeded fixture.

Each phase is independently mergeable (per workspace rule: branch → PR → master). Phases 1-2 can ship without ever touching the frontend; Phase 5 is purely additive once the read endpoints exist.

## 11. Open Questions

Flagged for explicit decision before Phase 1 starts.

1. **`view_consulted` reporting.** The MCP tools today don't have a notion of "which view the agent read." We can either (a) require the agent to pass it on every update, (b) infer from the tool args (e.g. if `details_sections` is absent, assume Summary-only), or (c) skip source #2 in v1 and only ship cache + reuse savings. **Recommendation:** (b) infer + (a) accept override. Confirm.
2. **Bootstrap-token formula for reuse savings.** Proposed: `min(20_000, summary_tokens + details_tokens)`. The cap exists because a 200k-token doc doesn't mean a from-scratch session would re-derive 200k of context. Pick a cap and we live with it. **Recommendation:** 20k cap.
3. **OpenAI/Gemini coverage.** Current Taskforce is Claude-only at the agent layer. Do we need to seed non-Claude pricing now, or wait until a real workflow uses it? **Recommendation:** seed Claude only in Phase 1; add OpenAI when a real workflow needs it.
4. **Org-scope visibility.** Show personal metrics to anyone with V2 access. Show org rollups only to org admins, or to all org members? **Recommendation:** org admins by default; configurable later.
5. **Demo metrics.** Mirror demo isolation on `v2_documents` exactly — demo metrics never appear in personal/org totals, and the sub-tab has no demo toggle (just respects whatever shell mode the user is in). Confirm.
6. **Retention.** Keep `metrics_events` forever, or roll up + delete after N months? **Recommendation:** keep forever for v1; revisit only if the table grows past ~10M rows.
7. **MCP-side tokenization.** Token counts for `bootstrap_tokens` need a tokenizer. Backend has `tiktoken` already? **TBD — needs a quick check on the backend deps.** If not present, add `anthropic[tokenizer]`.

## 12. File Map (what will exist after Phase 5)

```
EnderAI backend
├── app/models.py                              [+] MetricsEvent, MetricsDailyRollup, ModelPricing, public shapes
├── app/api/main.py                            [~] include v2_metrics router
├── app/api/routes/v2_metrics.py               [+] new
├── app/api/routes/v2_documents.py             [~] usage field + POST /usage
├── app/core/v2_documents.py                   [~] recompute summary_tokens/details_tokens on PATCH
├── app/core/metrics/
│   ├── __init__.py                            [+]
│   ├── registry.py                            [+]
│   ├── events.py                              [+]
│   ├── pricing.py                             [+]
│   ├── savings.py                             [+]
│   ├── rollup.py                              [+]
│   └── queries.py                             [+]
└── migrations/versions/2026xxxx_metrics.py    [+] tables + seed

MCP package
└── mcp/enderai-api-mcp/src/v2Documents/tools.ts   [~] usage? on all three tools

EnderAI-frontend
├── src/api/v2Metrics.ts                       [+] (auto-generated)
├── src/routes/v2/metrics.tsx                  [+]
├── src/components/V2/TaskforceShell.tsx       [~] nav entry
├── src/routes/v2/metrics.methodology.tsx      [+] "Learn how we calculate savings" page
└── src/components/V2/Metrics/
    ├── MetricsPage.tsx                        [+]
    ├── MetricsTimeRange.tsx                   [+]
    ├── MetricsScopeToggle.tsx                 [+]
    ├── MetricCard.tsx                         [+]
    ├── MetricTrendChart.tsx                   [+]
    ├── MetricBreakdown.tsx                    [+]
    ├── MethodologyLink.tsx                    [+] small text-link component
    ├── methodology.md                         [+] user-facing methodology copy
    └── formatters.ts                          [+]

docs (local only — per CLAUDE.md)
└── docs/taskforce-metrics-engine-plan.md      ← this file
```

## 13. Sources

Pricing pulled from:

- Anthropic — [`platform.claude.com/docs/en/about-claude/pricing`](https://platform.claude.com/docs/en/about-claude/pricing) (canonical, May 2026 snapshot).
- OpenAI — [`openai.com/api/pricing`](https://openai.com/api/pricing/) (model rates for GPT-4o, GPT-5, GPT-5.4, GPT-5.5).
