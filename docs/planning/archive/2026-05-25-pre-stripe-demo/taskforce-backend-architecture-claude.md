# Taskforce Backend Architecture — Microservice Shape

Last updated: 2026-05-23
Author: Claude (independent pass; companion to `taskforce-backend-architecture-overview.md` from Codex)

Scope of this doc: how the backend is *partitioned* into services and sub-services, where decisions actually run, and how the scoring engine connects to the rest of the system. Auth, identity, billing, and the legacy V1 Topic/Case path are deliberately out of scope — see Codex's doc for those.

The big surprise vs. the Codex writeup: **there are two scoring engines**, not one. They live in different runtimes, run on different paths, and answer different questions. Most of this document is about that split and how it propagates outward.

## 1. Deployment view — what's actually a service

```mermaid
flowchart LR
  subgraph Local[Local agent box]
    Hooks["scripts/taskforce-hooks/*.sh<br/>UserPromptSubmit, PostToolUse, Stop"]
    Agent[Claude Code / Codex / Cursor]
  end

  subgraph Render[Render blueprint — render.yaml]
    Backend["enderai-backend<br/>FastAPI · Docker · 4 workers"]
    MCP["enderai-mcp<br/>Node · Streamable HTTP"]
    DB[("Postgres + pgvector")]
  end

  subgraph External[External]
    OpenAI[OpenAI embeddings]
    Anthropic[Anthropic — Haiku + Sonnet]
    Stripe[Stripe]
    Firebase[Firebase Auth]
  end

  Hooks -- "bearer · HTTPS · 4s timeout" --> Backend
  Agent -- "MCP Streamable HTTP" --> MCP
  MCP -- "per-session bearer · enderaiFetch" --> Backend
  Backend --> DB
  Backend --> OpenAI
  Backend --> Anthropic
  Backend --> Stripe
  Backend --> Firebase
```

The Render blueprint declares **two web services**: `enderai-backend` (Python/FastAPI) and `enderai-mcp` (Node/TS). Nothing else runs out-of-process. There is no Redis, no Celery/arq, no separate scoring service, no embeddings worker, no rollup cron container.

Everything that *looks* like a microservice — the scoring engine, search indexer, summarizer, metrics rollup — runs **inside the FastAPI process** or **inside the MCP process**. They are sub-services by module boundary, not deployment boundary.

The local hooks are the third runtime, but they live on the user's laptop. They're shell scripts that POST to the backend with the user's per-machine bearer token; the backend treats them indistinguishably from a browser session.

## 2. Service inventory by module

Everything below is a logical service. Co-located in one of the two processes.

| Service | Process | Path | Lines | What it owns |
|---|---|---|---|---|
| **Discovery scorer (fast)** | backend | `app/core/taskforce/scoring.py` | 275 | 6-signal Jaccard ranker, p95 < 500ms |
| **Discovery orchestrator** | backend | `app/core/taskforce/discover.py` | 202 | ACL fetch → score → emit consult events |
| **Session entry** | backend | `app/core/taskforce/session.py` | 71 | Mints `session_id`, runs discover, picks `suggested_pin` |
| **Observe orchestrator** | backend | `app/core/taskforce/observe.py` | 504 | Materiality → summarize *or* structured → patch doc → emit metrics |
| **Materiality gate** | backend | `app/core/taskforce/materiality.py` | 74 | Pure decision: is this session worth Haiku money? |
| **Summarizer** | backend | `app/core/taskforce/summarizer.py` | 211 | Async Haiku call with redacted transcript |
| **Redaction** | backend | `app/core/taskforce/redaction.py` | 83 | Pre-summarizer secret scrub |
| **Rediscovery cost** | backend | `app/core/taskforce/rediscovery.py` | 139 | Pure structural estimator, cached on doc |
| **Search indexer** | backend | `app/core/search/indexing.py` | 268 | Lifespan asyncio task; drift-sweep loop |
| **Search retrieval** | backend | `app/core/search/retrieval.py` | 93 | pgvector cosine + ACL join |
| **Search answer** | backend | `app/core/search/answer.py` | 234 | SSE stream; managed Claude or BYOK Claude/OpenAI |
| **Embeddings client** | backend | `app/core/search/embeddings.py` | 100 | Managed OpenAI key; lazy import |
| **Document connectors** | backend | `app/core/search/connectors/` | ~170 | `Source` protocol; only `DocumentSource` is real |
| **Metrics emitters** | backend | `app/core/metrics/events.py` | 509 | Append-only event writes; pricing snapshot per write |
| **Savings calculators** | backend | `app/core/metrics/savings.py` | 123 | Three sources: cache, summary-only, reuse |
| **Metrics registry** | backend | `app/core/metrics/registry.py` | 206 | Code-defined metric catalog |
| **Metrics rollup** | backend | `app/core/metrics/rollup.py` | 151 | Daily materialization to `metrics_daily_rollup` |
| **Metrics queries** | backend | `app/core/metrics/queries.py` | 335 | Read-side aggregations + windowing |
| **Document ACL/access** | backend | `app/core/v2_documents.py` | ~2200 | `build_v2_document_acl_filter`, token-count refresh |
| **Congruence engine (smart)** | MCP | `mcp/src/v2Documents/scoring/` | ~870 | 12-signal weighted engine w/ conflicts; reuse-or-create decision |
| **Self-heal planner** | MCP | `mcp/src/v2Documents/selfHeal.ts` | 248 | Builds PATCH from weak-signal gaps + new request |
| **Active doc state** | MCP | `mcp/src/v2Documents/active.ts` | 35 | Per-session pin tracking |
| **MCP tool registry** | MCP | `mcp/src/mcpServer.ts` | 2780 | All tool definitions and dispatch |
| **MCP HTTP transport** | MCP | `mcp/src/httpServer.ts` | 306 | Streamable HTTP server, session map, bearer binding |

## 3. The two scoring engines

This is the architectural point that matters most and that Codex's doc glossed over.

```mermaid
flowchart TB
  subgraph Hot[Hot-path · runs on every user prompt]
    Hook[user-prompt-submit.sh]
    Hook -->|"POST /v2/taskforce/discover<br/>4s timeout"| PyDiscover[discover.py orchestrator]
    PyDiscover --> PyScore["scoring.py<br/>6 signals · Jaccard · p95 &lt; 500ms<br/>capped at 200 most-recent docs"]
    PyScore --> PyBand["band: low/medium/high<br/>cutoffs 0.30 / 0.65"]
    PyBand --> Preamble[Hook prepends 'Related prior work' preamble]
  end

  subgraph Smart[Decision-path · runs on enderai_begin_document]
    Agent[Agent calls enderai_begin_document via MCP]
    Agent --> Active[active.ts — current pin?]
    Active --> Engine["congruence engine<br/>12 signals incl. conflicts<br/>0–100 score"]
    Engine --> Decide["decide()<br/>reuse / create"]
    Decide -->|"high band → reuse"| Reuse[Use existing doc]
    Decide -->|"medium + clear lead + no conflicts → reuse"| Reuse
    Decide -->|"low band OR ambiguous OR conflict fires → create"| Create[Mint new doc]
    Reuse --> SelfHeal["selfHeal.ts — weak signals →<br/>PATCH that fills gaps"]
  end

  PyScore -. "deliberately simpler·<br/>same tokenize() + bandFor()<br/>cutoffs for compatibility" .- Engine
```

### 3.1 Python scorer — `app/core/taskforce/scoring.py`

| Property | Value |
|---|---|
| Runtime | Backend FastAPI process |
| Caller | `discover.py`, which is called by the hook (HTTP) or the MCP `taskforce_discover` fallback |
| Latency budget | p95 < 500ms across 200 candidates |
| Signals | title-overlap, corpus-overlap, file-substring, symbol-substring, error-substring, recency (exp decay, 30d half-life) |
| Weights | `title 0.30, corpus 0.25, files 0.15, recency 0.15, symbols 0.10, errors 0.05` |
| Score range | `[0, 1]` |
| Bands | low < 0.30, medium < 0.65, high ≥ 0.65 |
| Output | `rank top-K above min_score` — for the preamble |
| What it can't do | Conflict signals, anti-matches, embeddings, collaborators, intent phrases |
| Purity | Pure: `score_document(doc, request) → ScoredCandidate`. No I/O. |

It exists to feed the **UserPromptSubmit hook**, which is on the critical path of every user keystroke. The hook has a hardcoded 4-second curl timeout and runs synchronously before Claude Code sees the prompt. So this scorer is optimized for *predictable, bounded latency*, not for *best possible ranking*.

### 3.2 TypeScript congruence engine — `mcp/src/v2Documents/scoring/`

| Property | Value |
|---|---|
| Runtime | MCP Node process |
| Caller | `enderai_begin_document` tool — the explicit, agent-driven decision |
| Latency budget | Single tool call; ~hundreds of ms is fine |
| Signals (positive) | title-overlap, file-overlap, symbol-overlap, error-overlap, anchor-overlap, collaborator-overlap, recency, intent-phrase ("continue", "follow-up", "still", …) |
| Signals (conflict) | tenant-conflict, repo-conflict, error-family-conflict, terminal-state-conflict |
| Weights | Positives sum to 100; conflicts are negative (`tenant: -60, repo: -30, error-family: -25, terminal: -25`) |
| Score range | `[0, 100]` (after clamp) |
| Bands | low < 45, medium < 70, high ≥ 70 |
| Output | `decide() → reuse(doc_id) | create` — a *decision*, not a ranking |
| Self-heal hook | Yes: `weakSignals` (positive signals that fired weakly) drive `selfHeal.ts` to plan a PATCH that fills the gaps |
| Purity | Pure: `scoreCongruence(candidate, request, config)`. No I/O. |

The conflict signals are the killer feature. Even a strong title match gets rejected if the doc mentions tenant `acme` and the request mentions tenant `globex`. Even a high-scoring candidate gets rejected if the doc has `## Outcome` (or any `terminal-state` marker) and the request doesn't read as a continuation. These exist because the cost of incorrectly reusing a closed/done/wrong-tenant doc is much higher than the cost of creating one extra fresh doc.

### 3.3 Why the split, and where it leaks

Both engines share `tokenize()` semantics (same stopwords, same `\p{L}\p{N}_./-` split) and the same `bandFor` cutoff *philosophy* (low/medium/high naming). That's intentional — the Python file's docstring explicitly says it mirrors the TS so divergence stays bounded to *which* signals fire, not *how* tokens are extracted.

But the band cutoffs themselves are different (`0.30/0.65` vs `45/70`), the scales are different, and the conflict signals only exist in one. So:

- A doc that the **fast scorer** ranks `0.72 high` may or may not survive the **smart engine**'s conflict checks.
- The hook will surface that doc to the user as "Related prior work" anyway, because the hook doesn't run the smart engine.
- If the agent then calls `enderai_begin_document` on the same context, the smart engine may decline to reuse — and silently mint a fresh doc.

This is fine for now (discover is a *suggestion*, begin is a *decision*) but it's an actual semantic gap, not a phase-1/phase-2 distinction. Worth documenting somewhere visible.

## 4. Taskforce session pipeline (V2 lifecycle)

```mermaid
sequenceDiagram
  participant Agent
  participant Hooks as Bash hooks
  participant MCP as MCP bridge
  participant API as FastAPI /v2/taskforce
  participant Discover as discover.py
  participant Scorer as scoring.py
  participant Observe as observe.py
  participant Materiality as materiality.py
  participant Summarizer as summarizer.py (Haiku)
  participant Docs as v2_documents core
  participant Metrics as metrics_event

  Note over Agent,Hooks: Path A — Claude Code with hooks installed
  Agent->>Hooks: UserPromptSubmit
  Hooks->>API: POST /discover (prompt, cwd, files, git_branch)
  API->>Discover: discover(actor, request, demo)
  Discover->>Docs: list_v2_documents_for_actor (capped at 200)
  Discover->>Scorer: rank_candidates(docs, request, k, min_score)
  Scorer-->>Discover: ranked candidates (≤K)
  Discover->>Metrics: record_document_consulted (one per match)
  Discover-->>Hooks: matches + query_id
  Hooks-->>Agent: prepends "Related prior work" preamble

  Agent->>Hooks: PostToolUse (every N tool calls)
  Hooks->>API: POST /observe (kind=checkpoint, transcript, harness)

  Agent->>Hooks: Stop
  Hooks->>API: POST /observe (kind=final, ...)

  Note over Agent,MCP: Path B — Codex/Cursor (hookless)
  Agent->>MCP: taskforce_session_start
  MCP->>API: POST /session/start
  API->>Discover: same orchestrator as Path A
  Discover-->>API: matches
  API-->>MCP: session_id + matches + suggested_pin (high band only)

  Agent->>MCP: taskforce_session_observe (with structured fields)
  MCP->>API: POST /observe
  API->>Observe: observe(actor, request, demo)
  Observe->>Materiality: assess (≥3 turns OR ≥1 file OR ≥2 cmds OR pinned)
  alt material
    alt structured payload present
      Observe->>Observe: synthesize SummarizerResult locally (no LLM)
    else transcript only
      Observe->>Observe: check daily $1 cap + managed key present
      Observe->>Summarizer: summarize(transcript, prompt)
      Summarizer-->>Observe: SummarizerResult (parsed JSON)
    end
    Observe->>Docs: apply_v2_document_update OR create new doc
    Docs->>Docs: refresh_v2_document_token_counts (summary, details, rediscovery)
    Observe->>Metrics: tokens.consumed (summarizer) + tokens.consumed (harness) + taskforce.observed
  else not material
    Observe->>Metrics: taskforce.observed (audit-only, action=skipped)
  end
  Observe-->>MCP: action + document_id + patched_fields + shadow flag
```

### Key facts the Codex doc undersold

1. **Two material entry points: hooks and MCP.** They share the same backend orchestrator (`discover.py`, `observe.py`). The MCP path is not "legacy fallback"; it's the only path Codex/Cursor have, and `session_start` (TF-181) is recent.

2. **Shadow mode is opt-out**, not opt-in. `TASKFORCE_OBSERVE_SHADOW` defaults to `1`. So in production today, `/observe` records the audit event and computes the diff but **does not patch the doc**. Flipping that requires a deploy env-var change.

3. **The structured-payload shortcut** (`_has_structured_payload`) is a quiet but important cost lever. If the agent provides `summary_points`/`details_sections`/`decisions`/`outcome` directly, the backend bypasses both the Haiku call *and* the daily $1 cap *and* the managed-key requirement. This is what makes the hookless MCP path viable for users without the managed Anthropic key.

4. **Daily USD cap** ($1/user/day for summarizer) is the only meaningful cost control. It only gates the Haiku call, not the harness `tokens.consumed` event (which is just accounting).

5. **Materiality is deterministic and runs before any LLM call.** ≥3 assistant/tool turns, OR ≥1 file modified, OR ≥2 distinct shell commands, OR `active_document_id` is set. If none of those, the audit row says `skipped: trivial_session` and no money is spent.

## 5. Search subsystem — how the pieces wire up

```mermaid
flowchart TB
  subgraph Lifespan[FastAPI lifespan]
    Boot[app/main.py startup]
    Boot -->|"if OPENAI_API_KEY set"| Sweeper[indexing.run_forever]
  end

  subgraph IndexLoop[indexing.py · async loop]
    Sweeper -->|every SWEEP_INTERVAL| Sweep[sweep_documents_once]
    Sweep --> Drift["SELECT V2Document WHERE<br/>last_indexed_at IS NULL<br/>OR &lt; updated_at<br/>OR index_version != current"]
    Drift -->|"≤ BATCH_SIZE rows"| SourceCall["DocumentSource.fetch_item"]
    SourceCall --> Chunker["build_chunks_from_document<br/>1 summary chunk +<br/>1 per details_markdown_sections[i]<br/>long sections fan to anchor#N"]
    Chunker --> Hash[chunk_version_hash sha256]
    Hash -->|"hash unchanged → skip"| Skip
    Hash -->|"hash changed → embed"| Embed["embed_batch via OpenAI<br/>(managed key only)"]
    Embed --> Upsert["upsert source_item_embedding<br/>(denorm owner/org/visibility/is_demo)"]
    Upsert --> Mark["doc.last_indexed_at = now<br/>doc.index_version = 'documents.v1'"]
  end

  subgraph Query[Request path · POST /v2/search]
    Req[query] --> Tier["tiering.resolve_search_eligibility<br/>(free/pro+BYOK/max/admin)"]
    Tier --> EmbQ[embed_one via OpenAI]
    EmbQ --> Vector["pgvector cosine_distance ORDER BY ASC<br/>JOIN V2Document<br/>WHERE build_v2_document_acl_filter()"]
    Vector --> Hits[SearchHit list]
    Hits --> Answer["answer.stream_answer<br/>citations · token deltas · done"]
    Answer -->|managed route| Claude1[Claude via managed key]
    Answer -->|byok:anthropic| Claude2[Claude via decrypted user key]
    Answer -->|byok:openai| GPT[OpenAI via decrypted user key]
    Answer --> Usage[record_search_usage → tokens.consumed]
  end
```

### Architectural notes the file structure makes obvious

- **`connectors/base.py` defines a `Source` Protocol** with `list_items`, `fetch_item`, `handle_event`. Only `DocumentSource` is wired. There's a `stub_slack.py` placeholder. The connector interface includes a webhook entrypoint, which is dead code today but means adding Slack/GitHub/Gmail wouldn't require reshaping the indexer — only writing a new Source.

- **The indexer is a single asyncio task in the FastAPI process.** No locking, no leader election. The file's own comment flags this as the next thing to fix when the backend goes multi-instance: wrap `sweep_documents_once` in a Postgres advisory lock.

- **ACL is double-enforced.** The `source_item_embedding` row carries denormalized `owner_id`/`organization_id`/`visibility`/`is_demo`. The query also JOINs back to `V2Document` and applies the *same* `build_v2_document_acl_filter` used by the read API. The denorm columns are belt-and-suspenders; the JOIN is the actual gate. This means a doc's ACL can change without re-indexing — the next retrieval picks up the new ACL from the V2Document row.

- **Embeddings are always managed key, even for BYOK users.** This is a hard design call called out in `embeddings.py`: BYOK affects only the *answer* call, never the *index*. Otherwise you'd end up with two embedding spaces and unusable retrieval.

- **Long details sections fan out to `<anchor>#N` chunks** (per `MAX_CHUNK_CHARS=2000`), preserving the anchor-link semantics that Summary segments use via `evidence_anchor_id`. So a search hit on `setup#3` still maps back to the same anchor a Summary paragraph would cite.

- **No FTS, no hybrid.** Phase 1 is vector-only. The `retrieval.py` header explicitly contracts: the `SearchHit` shape won't change when FTS lands.

## 6. Metrics architecture — event-sourced with code-defined registry

```mermaid
flowchart LR
  subgraph Producers[Producers]
    DocOps["v2_documents routes<br/>(created/updated/finished/reused)"]
    UsageRoute["POST /v2/documents/{id}/usage"]
    Discover[discover.py]
    Observe[observe.py]
    SearchRoute[v2_search.py]
  end

  subgraph Emitters[app/core/metrics/events.py]
    RecCreated[record_document_created]
    RecUpdated[record_document_updated]
    RecFinished[record_document_finished]
    RecReused[record_document_reused]
    RecConsulted[record_document_consulted]
    RecUsage[record_usage]
    RecSearch[record_search_usage]
  end

  subgraph Calc["savings.py · pure"]
    Cache[cache_savings]
    Summ[summary_only_savings]
    Reuse[reuse_savings]
  end

  subgraph Storage[Postgres]
    Event[("metrics_event<br/>append-only")]
    Pricing[("model_pricing<br/>snapshot per row")]
    Rollup[("metrics_daily_rollup<br/>materialized")]
  end

  subgraph Reads[Reads]
    Registry["registry.py<br/>code-defined catalog"]
    Queries[queries.py]
    API[v2_metrics route]
  end

  DocOps --> Emitters
  UsageRoute --> RecUsage
  Discover --> RecConsulted
  Observe --> RecUsage
  Observe --> Emitters
  SearchRoute --> RecSearch

  Emitters -->|"price_usage at write time"| Pricing
  Pricing -->|"snapshot id stored on event"| Event
  Emitters -->|"call when applicable"| Calc
  Calc --> Event

  Event -->|"nightly rollup_day(date)"| Rollup
  Registry --> Queries
  Event --> Queries
  Rollup --> Queries
  Queries --> API
```

### What's distinctive about this design

1. **Pricing is snapshotted at write time.** Each `metrics_event` row stores `pricing_id` referencing the `model_pricing` row that was effective at `occurred_at`. So when Anthropic raises Sonnet prices in three months, the historical USD totals on yesterday's events don't move. The plan calls this out as a hard requirement.

2. **The metric *catalog* is code, not data.** `registry.py` is the source of truth. Adding `documents_consulted` was one PR that appended a `MetricDefinition`; both the rollup job and the read API pick it up by iterating the registry. The frontend self-describes via `GET /v2/metrics/definitions`.

3. **Composed metrics defer until read time.** `reuse_rate` and `documents_touched` set `composed=True` and aren't materialized in `metrics_daily_rollup`. They're computed from underlying counts when the read endpoint asks for them. The rollup job skips them via `rollup_metric_names()`.

4. **`document.consulted` smuggles savings through `input_tokens`.** `discover.py` records the consult event with `input_tokens = max(0, rediscovery_cost - summary_tokens_read)`. The `avoided_rediscovery` metric definition then aggregates that field. This is a deliberate choice to avoid a "savings_tokens" column or a per-metric JSONB parse — the registry says "sum input_tokens for kind=document.consulted" and it just works.

5. **Rediscovery cost is cached on the document, not computed at consult time.** `refresh_v2_document_token_counts` runs on every doc mutation (`apply_v2_document_update`) and writes `summary_tokens`, `details_tokens`, `rediscovery_cost_tokens` directly onto the row. Discover reads them with a plain attribute access. So discover stays fast even when the doc is complex.

6. **Demo and live data are rolled up as separate rows.** `is_demo` is part of the rollup primary key tuple. Plan §11 demanded strict isolation — this is how it's enforced.

7. **Five-way `record_*` taxonomy + one cross-cutting `_record_usage_events`.** Every `record_document_*` function takes an optional `TaskforceUsagePayload` and, when present, also writes the paired `tokens.consumed` + `tokens.saved.*` events. So the document lifecycle event and its cost event always commit together (single transaction, caller commits).

## 7. MCP bridge — what it actually is

```mermaid
flowchart TB
  Client[MCP client — Claude Code, Codex, Cursor]
  Client -->|"Authorization: Bearer <agent_mcp JWT>"| HTTP[httpServer.ts]
  HTTP --> Validate["validateIncomingMcpBearerToken<br/>(MCP_BEARER_TOKEN or per-token)"]
  Validate --> Session["Session map keyed by Mcp-Session-Id<br/>{transport, server, tokenRef}"]
  Session --> Transport["WebStandardStreamableHTTPServerTransport<br/>(MCP SDK)"]
  Transport --> Server["createMcpServer<br/>(per session)"]

  Server --> Tools{Tool registry}

  subgraph TaskforceTools[Taskforce tools — TF-174 epic]
    T1[taskforce_session_start]
    T2[taskforce_session_observe]
    T3[taskforce_session_log]
    T4[taskforce_discover]
  end

  subgraph DocTools[V2 document tools — pre-Taskforce]
    D1[enderai_begin_document]
    D2[enderai_update_document]
    D3[enderai_finish_document]
  end

  subgraph Engines[In-process compute]
    CE["congruence engine (scoring/)<br/>12 signals + conflicts"]
    SH[selfHeal.ts]
    AS[active.ts state]
  end

  subgraph LegacyTools[Legacy V1 tools]
    L1[enderai_begin_case]
    L2[enderai_update_case]
    L3[enderai_use_skill]
    L4[enderai_finish_case]
  end

  subgraph Escape[Escape hatches]
    E1[enderai_request]
    E2[enderai_openapi]
    E3[enderai_health_check]
    E4[enderai_session_info]
  end

  Tools --> TaskforceTools
  Tools --> DocTools
  Tools --> LegacyTools
  Tools --> Escape

  DocTools --> CE
  DocTools --> SH
  DocTools --> AS

  TaskforceTools -->|"enderaiFetch<br/>per-session bearer"| Backend[FastAPI backend]
  DocTools -->|"enderaiFetch"| Backend
  LegacyTools -->|"enderaiFetch"| Backend
  Escape -->|"enderaiFetch"| Backend
```

### MCP bridge responsibilities, precisely

The MCP bridge is **not** a service tier. It's a:

1. **Protocol adapter** — translates MCP Streamable HTTP ↔ JSON REST. `enderaiFetch()` is a thin authenticated `fetch` wrapper.
2. **Per-session token holder** — when the client sends a bearer on initialize, the bridge binds it to the session's `tokenRef` and forwards it on every subsequent backend call. Token rotation mid-session is supported (the `tokenRef` getter is mutable).
3. **In-process decision engine** — `enderai_begin_document` runs the 12-signal congruence engine *locally* in the Node process before deciding to call the backend's create vs. PATCH route. This is why the smart engine lives in TypeScript: it's a tool-side decision, not a backend service.
4. **Self-heal planner** — when reuse fires, `selfHeal.ts` plans a PATCH from the doc's weak signals + the new request, also locally in Node. The backend just applies the PATCH it receives.

`mcpServer.ts` is 2780 lines because it registers every tool's schema and dispatches. The actual business logic is in `v2Documents/` and `taskforce/`.

### What's notably absent from the MCP bridge

- No database. Ever. All persistence flows through the backend.
- No LLM calls. All Anthropic/OpenAI traffic is backend-side.
- No caching beyond the per-session active-document state (in `active.ts`, a single `{documentId, title, startedAt, lastUpdatedAt, demo}` object).
- No metrics emission. The backend writes events; the MCP doesn't have a DB connection.

If the MCP process restarts, you lose only the in-flight Streamable HTTP sessions. No durable state is at risk.

## 8. Cross-cutting wiring — how it all connects on one prompt

End-to-end trace for one user prompt in Claude Code with hooks installed:

```mermaid
sequenceDiagram
  participant U as User
  participant CC as Claude Code
  participant UPS as user-prompt-submit.sh
  participant API as FastAPI
  participant DiscPy as discover.py + scoring.py
  participant DB as Postgres
  participant Anthropic
  participant MCP
  participant Smart as Congruence engine (TS)
  participant Obs as observe.py
  participant Hooks2 as post-tool-use.sh / stop.sh

  U->>CC: types prompt
  CC->>UPS: stdin payload {session_id, prompt, cwd, transcript_path}
  UPS->>API: POST /v2/taskforce/discover (4s timeout)
  API->>DiscPy: discover(actor, request, demo)
  DiscPy->>DB: list_v2_documents_for_actor (limit 200)
  DB-->>DiscPy: candidate docs
  DiscPy->>DiscPy: rank_candidates (pure scoring)
  DiscPy->>DB: INSERT document.consulted per match
  DiscPy-->>API: matches + query_id
  API-->>UPS: JSON response
  UPS-->>CC: stdout = "Related prior work" preamble<br/>stderr = "[Taskforce] N docs pulled · ..."
  CC->>Anthropic: prompt with preamble prepended

  Note over CC,MCP: Optional: agent calls enderai_begin_document
  CC->>MCP: enderai_begin_document(request_summary, files, ...)
  MCP->>API: GET candidate docs (filtered)
  API-->>MCP: candidate list
  MCP->>Smart: scoreCongruence + decide()
  alt decide = reuse
    Smart-->>MCP: reuse(doc_id) + weakSignals
    MCP->>MCP: planSelfHeal(doc, request, score)
    MCP->>API: PATCH /v2/documents/{id} (heal patch)
    API->>DB: apply_v2_document_update + refresh_v2_document_token_counts
    API->>DB: record_document_reused + tokens.saved.reuse
  else decide = create
    Smart-->>MCP: create + reason
    MCP->>API: POST /v2/documents/
    API->>DB: insert + refresh_v2_document_token_counts
    API->>DB: record_document_created
  end

  loop every N tool calls
    CC->>Hooks2: PostToolUse
    Hooks2->>API: POST /observe (kind=checkpoint)
    API->>Obs: materiality? cap? key?
    Obs->>Anthropic: Haiku summarize (or skip if structured)
    Obs->>DB: patch doc (unless shadow) + metrics events
  end

  CC->>Hooks2: Stop
  Hooks2->>API: POST /observe (kind=final)
```

Note that the two scoring engines are on different branches of this trace. The hook always runs the fast Python scorer. The smart TS engine only runs if the agent explicitly invokes `enderai_begin_document`.

## 9. Runtime risks and design seams worth knowing

These are things the code calls out explicitly or that fall out of the architecture:

- **Indexer single-instance.** `run_forever()` is a lifespan asyncio task. Two backend instances will both sweep the same drift. The comment in `indexing.py` already names the fix: Postgres advisory lock. Not yet implemented.
- **Two scoring engines, no parity tests.** Both copy the `tokenize()` semantics and `bandFor` cutoff *names*, but there's no test that asserts they produce comparable bands on shared inputs. A doc that reads "high" to the hook may read "low" or "create-fresh" to the begin-document path.
- **Shadow mode is the production default.** Operationally, `/observe` is auditing intent — not mutating documents. Anything that looks at "did the doc get updated by the agent?" needs to check `TASKFORCE_OBSERVE_SHADOW`. Codex's doc mentions this; it's worth re-stating because it changes what the metrics actually mean.
- **Materiality + daily cap are the only safety rails on summarizer spend.** Both are cheap to bypass accidentally (e.g. a runaway harness reporting `active_document_id` on every prompt would mark every session material). Worth monitoring `tokens.consumed.subkind=taskforce_summarizer` per-user.
- **Rediscovery cost is cached only when the doc mutates.** A doc whose structure was estimated under v1 coefficients will stay v1 forever unless someone bumps it. There's no migration step here yet.
- **MCP `enderai_request` is an escape hatch into the full backend API.** It's how agents call arbitrary OpenAPI routes through the bridge. Security-wise this is bounded by the per-session bearer (i.e. the user's own permissions), but it does mean the MCP surface includes anything the backend exposes.
- **Embedding space is locked to one model.** `settings.SEARCH_EMBEDDING_MODEL` (`text-embedding-3-small`, 1536d) is what the entire `source_item_embedding` table assumes. Changing it requires a full reindex driven by bumping `CURRENT_INDEX_VERSION`.

## 10. Reading order for the curious

If you want to internalize this system, read in this order:

1. `app/core/taskforce/scoring.py` — 275 lines, pure, no dependencies.
2. `mcp/src/v2Documents/scoring/signals.ts` — 619 lines but cleanly split per signal. Compare and contrast with #1.
3. `mcp/src/v2Documents/scoring/engine.ts` + `config.ts` — see how weights + `decide()` compose.
4. `app/core/taskforce/discover.py` — the thin orchestrator. Ties scoring to ACL + metrics.
5. `app/core/taskforce/observe.py` — the meaty one. Shadow mode, structured shortcut, daily cap, summarizer dispatch.
6. `app/core/search/indexing.py` — the only thing in this codebase that runs a background loop.
7. `app/core/search/retrieval.py` — short. Shows the ACL JOIN pattern.
8. `app/core/metrics/events.py` + `savings.py` + `registry.py` — read together. Three files, one design.
9. `mcp/src/httpServer.ts` — see how thin the MCP transport layer actually is.
10. `scripts/taskforce-hooks/user-prompt-submit.sh` — read this last; it's the *real* discover client.
