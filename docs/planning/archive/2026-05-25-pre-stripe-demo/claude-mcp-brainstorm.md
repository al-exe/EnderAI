# Taskforce MCP — Brainstorm: rethinking the flow (v2, ticketable)
_Date: 2026-05-21 · Author: alexlee + Claude Opus 4.7 · Status: 5/6 phases shipped; soak + tool rename remaining_

> Premise: the current `enderai_begin_document` / `_update_document` / `_finish_document` workflow is friction-heavy, easy for the agent to skip, and the savings model (cache + summary-only + reuse) is a mechanical accounting trick rather than a defensible "Taskforce saved you X" story. Let's start over.

> **What changed in v2:** open questions in §10 of v1 were resolved by alexlee. v2 folds those decisions into the design and expands each phase into ticketable detail.

> **What changed in v3 (2026-05-21):** §13 captures the shipped state. 5 of 6 phases merged across 9 PRs in a single push. Hooks installed and validated locally; metrics endpoint shows `documents_consulted: 3, avoided_rediscovery: 97,349 tokens, $0.49 USD` from the smoke run. Tool-name rename (§7.6) and Anthropic key + shadow-off flip are the remaining moves.

> **What changed in v4 (2026-05-21, late):** §15 adds a three-tier model for agents without Claude Code's hook surface (Codex, Cursor, plain API). Phases 7–8 (TF-181 + TF-182) propose `taskforce_session_start` + `taskforce_session_observe` MCP tools and a `taskforce-cli` so any agent can plug into the same backend + metrics. The §0–§13 design isn't deprecated — Tier 1 (Claude Code hooks) stays the gold standard. §15 is what we ship for everyone else.

## Reading guide

If you only have 2 minutes, read **§0** (the picture), **§5.7** (the dashboard story), **§11.1** (resolved decisions), **§13** (what's shipped), and **§15** (hookless agents). If you're picking up a phase to implement, jump to **§7.x** for that phase — it has goal, files, API, tests, and a draft ticket.

---

## 0. What "good" looks like

Picture a user sending a request to the agent:

1. **Discovery is automatic.** Before the model sees the prompt, Taskforce has already searched the library for related prior work. If anything's relevant, the prompt arrives with a short "you've seen this before" preamble offering **the top 1–3 matches**.
2. **Context is pulled, not asked for.** The relevant docs' Summaries land in context. Details stay on disk; the agent reads them only when actually needed.
3. **The user sees what was pulled.** A one-line "Taskforce: 2 matches pulled" banner in the terminal; a `/taskforce` slash command for the full preview; a "Recent activity" widget on enderai.xyz. We're never silently injecting context.
4. **The agent just works.** It doesn't have to remember `enderai_begin_document`. It doesn't have to know its own token counts. It doesn't have to call `enderai_finish_document` either.
5. **Knowledge accretes automatically.** Every N tool calls *and* at session end, Taskforce decides whether the work was material. If it was, the active document (or a new one) is updated with the delta. If not, nothing happens.
6. **Savings has one headline and a story.** "Without Taskforce, rediscovering this would have cost ≈ N tokens. Taskforce gave it to you for M (consult + summarizer cost). Net saved: N−M." We show both numbers and the ratio: Taskforce should look obviously cheap relative to what it avoids.

No more agent-mediated lifecycle. No more `usage` payloads the LLM can't actually compute. No more three-way savings buckets that mean nothing to a CFO.

**Caveat:** the picture above describes the **Claude Code with hooks** path. Codex, Cursor, plain API users, and anything else without a UserPromptSubmit/Stop contract get a parallel "explicit-call" path that uses the same backend + the same metrics — see §15.

---

## 1. Where today's design hurts

| Friction | Why it bites |
|---|---|
| Agent must call `enderai_begin_document` to enter the workflow at all. | Most "agent work" never goes through the doc tools; it's raw Bash + Edit. Metrics dashboard reads zero even when work is happening. |
| Agent must call `enderai_update_document` to log progress. | Same problem, plus it's an extra round-trip that competes with "just doing the work". |
| Agent must self-report `usage` with per-turn token counts. | The LLM doesn't see its own post-response usage. The harness (Claude Code, Codex) does, but only sometimes injects it. So `usage` is silently `undefined` most of the time. |
| Savings split across `cache_read`, `summary_only`, `reuse_on_begin`. | Each bucket has a wonky interpretation. "Summary only" requires the agent to honestly report `view_consulted="summary"`, which it can't really know. |
| `forwardUsage` swallows backend errors. | When the metrics POST 422s, the tool call still returns success. There's no signal that metrics are broken. |

The thread through all of these: **we're asking the model to do work the model can't reliably do**. The model can't see its own tokens. It can't always remember to call the doc tools. It can't honestly report which view of the doc it consulted. It can't tell whether the work it just did was "material" enough to log.

So: stop asking it.

---

## 2. The proposed flow

### 2.1 Picture

```text
user prompt
    │
    ▼
[UserPromptSubmit hook]
    │   POST /taskforce/discover { prompt, cwd, files, git_branch }
    │   ←  { matches: [{ doc, score, summary }, …] (1–3 above τ) }
    │   formats preamble + writes one-line banner to user's terminal
    ▼
model (no tool calls required; doc context is already in the prompt)
    │
    │   model does whatever it does: Bash, Edit, Read, gh, …
    │   if it really wants to, it can call taskforce_pin(doc_id) to commit to
    │   a specific doc; otherwise the hook tracks the top match as the
    │   implicit active doc.
    │
    │   every N tool calls:
    │       [PostToolUse hook]
    │           POST /taskforce/observe { active_doc_id?, transcript_delta, kind: "checkpoint" }
    │           server-side summarizer materializes the delta into the doc
    ▼
[Stop hook]
    │   POST /taskforce/observe { active_doc_id?, transcript_digest, kind: "final" }
    │   server-side summarizer finalizes:
    │     - "was this material?"   (yes if N tool calls / commands / file mods)
    │     - "what changed?"        (decisions, commands, files, outcome)
    │   if active_doc_id is set     → PATCH /v2/documents/{id} with the delta
    │   elif material               → POST /v2/documents/ with synthesized body
    │   else                        → no-op
```

The model is no longer a participant in the lifecycle. Hooks do everything. The model only sees context arrive and naturally consumes it; everything else is bookkeeping that happens before the prompt, between tool calls, and after the Stop event.

### 2.2 What the user types changes nothing

Hard constraint: the user types `claude` (or `codex`, or whatever) and starts working. They don't add `--taskforce` or `--use-doc=…`. The hooks are registered globally in `~/.claude/settings.json`. From the user's POV, prior work just shows up — with a visible banner so they know it happened.

### 2.3 What the agent sees

A typical augmented prompt looks like:

```text
─── Related prior work (Taskforce) ──────────────────
[TF-156 polish — last touched 2026-05-20 by you, 0.74 confidence]
  Summary: copy cleanup on the metrics page. USD Saved → USD Offset.
  Open questions: none. Outcome: shipped in PR #107.

[Library tickets queue — last touched 2026-05-19 by you, 0.58 confidence]
  Summary: 16 LIBRARY tickets (TF-141..TF-172) tracked in Jira.

(Type `taskforce show <id>` to expand details.)
─── End related prior work ──────────────────────────

<actual user prompt>
```

The model is free to ignore the preamble (in which case the savings story is "we still showed you, you chose not to use it") or to lean on it (in which case the savings story is "you didn't re-research this").

### 2.4 What the user sees

The hook also writes a single line to stderr that Claude Code surfaces in its UI:

```text
[Taskforce] 2 related docs pulled · TF-156 (0.74), Library queue (0.58) · /taskforce for details
```

A `/taskforce` slash command (Phase 2.3) shows the full preamble and session log. The web UI (Phase 4.5) adds a persistent "Recent activity" widget.

The invariant we want: **the user is never surprised by what Taskforce injected**. If it shows up in context, it shows up in the banner.

---

## 3. The discovery service (Phase 1)

### 3.1 Endpoint

```
POST /api/v1/taskforce/discover
body: {
  prompt: string                   // the user prompt verbatim
  cwd?: string                     // working directory; helps with repo affinity
  files?: string[]                 // files the harness already knows the user is touching
  git_branch?: string              // branch name; can imply ticket id
  recent_commands?: string[]       // last N shell commands the hook saw
  k?: number                       // max matches to return; default 3, hard cap 3
  min_score?: number               // hide matches below this; default 0.3
  demo?: boolean
}
response: {
  matches: Array<{
    document_id: string
    title: string
    score: number                   // 0..1, normalized
    confidence_band: "high" | "medium" | "low"
    match_reasons: string[]         // human-readable; reused from scoring/engine.ts
    summary_markdown: string        // doc.ai_generated_summary (preferred) or first 800 chars of main_body
    last_touched_at: string         // ISO
    outcome?: string                // populated for finished docs
    rediscovery_cost_tokens: number // see §5
    consult_token_cost: number      // size of summary_markdown in tokens
  }>
  // Returned even when matches is empty, so the hook can emit a stable banner.
  query_id: string                  // UUID; the hook echoes this back on consult events
}
```

### 3.2 What it does internally

1. Pulls candidate docs for the user via the existing actor-scoped query (`list_v2_documents_for_actor`), capped to **the last 200 docs by `updated_at` desc** for latency budget.
2. Runs them through the existing `scoring/engine.ts` congruence logic — same logic that backs `enderai_begin_document`'s auto branch today. It already understands files, symbols, errors, recency, conflicts.
3. Returns the top-`k` above `min_score`, hard-capped at 3 (per resolved decision §11.1).
4. **Inserts one `document.consulted` metrics event per returned match** (new event kind, see §5). The hook later issues a `taskforce_acknowledge` if it actually injected (we drop events for matches the hook ended up suppressing for budget).

### 3.3 Selection among 1–3 options

Per resolved decision §11.1.1: discovery returns up to 3, the **hook picks how many to inject** under a token budget (default 1,500 tokens). Priority order:

1. **Top match always**, regardless of budget — we'd rather truncate the summary than drop the best hit.
2. **Subsequent matches** included if score > 0.5 AND the next one fits in the remaining budget.
3. **Agent can override** via `taskforce_pin(doc_id)` mid-session if it disagrees with the auto-pin. The pin survives until session end.

The agent doesn't "pick" among the 3 in a single decision — it just reads what the preamble shows. The hook is deterministic. If we later add explicit human-in-the-loop selection (e.g. for ambiguous matches), we'll surface a `/taskforce pick` interactive prompt — out of scope for v2.

### 3.4 Preamble formatting (token budget aware)

Token budget per preamble: **≤ 1,500 tokens** by default, configurable per-user later. The hook fits as many matches as it can under that budget, dropping the lowest-scored first. Each match contributes ~400 tokens (title + summary + outcome). Below the budget, the hook truncates the summary itself.

The hook never injects Details. Those are gated behind `taskforce show <id>` (an MCP read tool or even a shell helper). Keeping Details out of the default preamble is what makes the savings math defensible — see §5.

### 3.5 Surfacing to the user (Phase 2.2 / 2.3)

Three surfaces, additive:

| Surface | Where | When |
|---|---|---|
| **One-line banner** | stderr from the UserPromptSubmit hook | Every prompt that has matches |
| **`/taskforce` slash command** | Claude Code prompt → MCP tool `taskforce_session_log` | On demand |
| **Web "Recent activity" widget** | enderai.xyz/v2/metrics or a new "Activity" sub-tab | Always-on for the user's browser session |

Both the banner and the slash command list the same matches with the same scores, so the user has parity between "what I saw in my terminal" and "what's in the durable record".

---

## 4. The observation service (Phase 4)

### 4.1 Why server-side and not agent-side

The hook captures the transcript and ships it to the backend. The backend runs the summarization. Doing it server-side gets us:

- One canonical summarizer prompt → consistent doc shape
- One model + one pricing snapshot → consistent USD math
- Centralized auth + DB write → no agent permissions tangle
- Easy to rev: change the summarizer model in one place

The harness just has to forward the transcript (or a redacted digest).

### 4.2 Endpoint

```
POST /api/v1/taskforce/observe
body: {
  kind: "checkpoint" | "final"              // see §4.5
  prompt: string                            // the original user request that started this run
  transcript: Array<{role, content}>        // assistant + tool messages, redacted of secrets
  active_document_id?: string               // if the hook pinned one
  pinned_query_id?: string                  // from the /discover response, if any
  cwd?: string
  files_touched?: string[]
  commands_run?: Array<{cmd, exit_code}>
  diff_summary?: string                     // git diff --stat or similar
  duration_ms: number
  harness: {                                 // self-reported by the hook; see §5.4
    model_id: string
    total_input_tokens?: number
    total_output_tokens?: number
    total_cache_read_tokens?: number
    total_cache_write_tokens?: number
  }
  checkpoint_index?: number                  // 1-based; null on "final"
}
response: {
  action: "updated" | "created" | "skipped"
  document_id?: string
  patched_fields?: string[]
  reason: string                            // human-readable
  metrics_events_recorded: string[]          // event ids
  summarizer_usd_cost: string                 // Decimal; what this observation just cost
}
```

### 4.3 Materiality check

Fast deterministic check, runs **before** the summarizer is invoked. The session is material if **any** of:

- ≥ 3 tool calls in the transcript
- ≥ 1 file modified (`files_touched` non-empty)
- ≥ 2 distinct shell commands in `commands_run`
- agent explicitly pinned a doc via `taskforce_pin`

If none of these hold, skip with `action="skipped", reason="trivial session"`. This is the cost short-circuit — we don't pay for summarization on a single "what time is it" prompt.

### 4.4 Summarization

When material:

1. Render the transcript through a fixed prompt template (`core/taskforce/summarizer_prompt.md`, versioned).
2. Send to claude-haiku-4-5 at temperature 0. Token budget: input ≤ 20k, output ≤ 2k. Bigger transcripts get sliced by recency.
3. Parse the JSON response: `{ decisions, commands_of_interest, files_touched, outcome, open_questions, summary_points, details_sections, materiality_score }`.
4. Record an `agent_session_cost` line item (see §5.4) for the summarizer call.

If `active_document_id` is set, PATCH it with the delta. Else POST a new doc with the summary as the seed body.

### 4.5 Mid-session checkpoints (per resolved decision §11.1.2)

Two hooks, two cadences:

| Hook | Fires when | Body kind | Default cadence |
|---|---|---|---|
| **PostToolUse** | After every tool call | `kind: "checkpoint"` | Every 10 tool calls OR every 5 minutes of wall time, whichever first |
| **Stop** | Session ends (user kills terminal, agent stops) | `kind: "final"` | Always, exactly once per session |
| **PreCompact** *(stretch)* | Context fills up and is about to be compacted | `kind: "checkpoint"` | Whenever Claude Code fires the hook |

The PostToolUse hook tracks a small counter in `~/.taskforce/session-state.json`. Each checkpoint ships only the transcript delta since the last observe, not the whole transcript. The backend deduplicates by `checkpoint_index` per session.

The Stop hook always ships the full session digest as `kind: "final"`. The backend can reconcile against earlier checkpoints by querying the session's prior observe rows (we keep a `taskforce_session_observe` audit table for this).

### 4.6 Privacy + cost

- The transcript can be big. The hook redacts obvious secrets (env vars, `Authorization:` headers, JWT-shaped strings, lines matching `(api[_-]?key|password|secret|token)\s*[:=]`) and truncates per-tool-call output to ~2KB. Total payload ≤ ~50KB typical.
- Summarization with haiku at $0.80/Mtok input, $4/Mtok output → typically < $0.005 per session. Acceptable.
- The materiality short-circuit keeps cost near zero for trivial sessions.
- Per-user daily cost cap (default $1/day) — the backend skips summarization with `reason="cost_capped"` if exceeded.

---

## 5. The savings model

### 5.1 The problem with today's model

Today we count tokens-not-sent: cache reads, "summary-only" decisions, "you reused this doc". The third category is the only one a user really cares about, and it's the one the agent has to honestly self-report. The other two are mechanically true but trivially small — they don't tell a savings story.

### 5.2 The new model — "rediscovery cost"

Every document carries an estimated **rediscovery cost** in tokens: roughly, "what would it take an agent to redo this investigation from scratch". When that doc gets consulted, the savings is the rediscovery cost minus what the consultation actually cost in tokens.

**Naive formula v1** (good enough to start, will tune from real data per §11.1.3):

```python
rediscovery_cost_tokens =
    1_500  * num_commands
  + 2_500  * num_files_inspected
  +    500 * num_decisions
  + 3_000  * num_details_sections
  + 1_000  * num_summary_points
  +    0   * num_open_questions
  +    0   * num_changes_recorded     # changes are downstream of decisions; don't double-count
```

Numbers come from rough averages:

- A shell command and its output ≈ 1k–3k tokens to re-read.
- A file read ≈ 2k–5k tokens depending on file size.
- A decision wasn't "free" — it took some back-and-forth. Allocate 500 tokens of conversation to each.
- A Details section is the durable knowledge — 3k tokens of investigation distilled.
- A summary point is a claim that took back-and-forth to phrase — 1k.

These are **deliberately round numbers**. We tune coefficients quarterly once we have a few weeks of real data. Until then, the formula is "best-effort estimate" and we mark it as such on the methodology page.

### 5.3 Consultation event

```
metrics_event(kind="document.consulted") with payload:
  - source: "user_prompt_hook" | "agent_explicit"
  - score: 0..1
  - query_id: uuid                    // from /discover; correlates banner ↔ event
  - summary_tokens: int                // size of what got injected into context
  - rediscovery_cost_tokens: int       // snapshot of the doc's cached value
  - net_saved_tokens: int              // max(0, rediscovery_cost - summary_tokens)
  - net_saved_usd: Decimal             // priced at agent's model rate
  - acknowledged: bool                 // hook confirmed it injected into the prompt (vs dropped for budget)
```

### 5.4 Taskforce's own cost (resolved decision §11.1.4)

Per alexlee's note: **show Taskforce's cost as a positive signal**. Taskforce being cheap *is the story*.

Two new event subkinds under `tokens.consumed`:

- `tokens.consumed.taskforce_summarizer` — what /observe paid haiku to summarize. Recorded automatically by the backend after each summarization.
- `tokens.consumed.taskforce_discovery` — recorded if we ever introduce LLM-based scoring; today's scoring is deterministic and free, so this stays at zero.

The agent's own session cost (`tokens.consumed.agent_session`) is reported by the hook from `harness.total_*_tokens`. This is the only place we trust the harness for token counts — it's reporting its own meter, not the model self-reporting.

Three displayed totals on the dashboard:

| Card | What it shows | How |
|---|---|---|
| **Avoided Rediscovery** | Sum of `net_saved_tokens` across `document.consulted` events | Headline |
| **Taskforce Cost** | Sum of `taskforce_summarizer + taskforce_discovery` tokens & USD | Sidekick (small, intentionally) |
| **Net Saved** | `Avoided Rediscovery − Taskforce Cost` | Headline (right side) |

If Taskforce is doing its job, **Taskforce Cost << Avoided Rediscovery**. The ratio (e.g. "Taskforce returned 47× its cost this week") is the most quotable number on the page.

### 5.5 Sanity bounds

- A consulted doc with `rediscovery_cost_tokens < summary_tokens` reports zero savings (`max(0, …)`).
- A consultation that the agent never actually used (we can heuristically detect via: did Details get expanded? did the next tool call reference the doc's symbols/files?) records the consult with `net_saved_tokens = 0` and `acknowledged=true, used_inferred=false`. We don't yet refund the saving, but we tag it for future tuning.
- Per-doc cap on `rediscovery_cost_tokens` of **50,000 tokens**. Documents bigger than that are outliers and probably gameable.
- Per-day cap on `net_saved_tokens` per user of **5,000,000 tokens** ($25 at Opus rates). Above that, we record but don't display — a runaway hook shouldn't make the dashboard look ridiculous.

### 5.6 What we lose by dropping today's categories

- Cache hits: still real but trivially small; the user doesn't care about cache. **We keep the events as `tokens.saved.cache` for backwards compatibility** but stop showing them on the main page (methodology page only).
- Summary-only: replaced by "your doc had N details_tokens cached; you read M summary_tokens; saved N−M". Same idea, no agent self-report.
- Reuse-on-begin: replaced entirely by consultation events. "Reuse" was always "I consulted this doc and chose to keep working on it" — that's exactly what consultation events capture.

We don't delete the old event kinds (existing data stays valid). We just stop emitting them from the new flow.

### 5.7 The dashboard story

Three rows of cards, top-to-bottom in importance:

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Net Saved (USD)              Avoided Rediscovery        Taskforce Cost       │
│ $4.27 (-0.09)                 142k tokens / $4.36       2.4k tokens / $0.09  │
│ "Taskforce returned 47× its cost this week"                                  │
└──────────────────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────────────────┐
│ Documents Consulted    Documents Touched    Reuse Rate                       │
│ 8                      14                   62%                              │
└──────────────────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────────────────┐
│ Tokens saved per day  (existing chart, now wired to rediscovery only)        │
└──────────────────────────────────────────────────────────────────────────────┘
```

The methodology page explains the formula, links to the registry definitions, and shows the per-source breakdown (rediscovery, cache, summary-only) so anyone curious can audit.

### 5.8 Worked example

Suppose a doc captures: 5 commands, 3 files inspected, 2 decisions, 3 details sections, 4 summary points.

```
rediscovery_cost = 5×1500 + 3×2500 + 2×500 + 3×3000 + 4×1000
                = 7500 + 7500 + 1000 + 9000 + 4000
                = 29,000 tokens
```

Later, the user starts a session about that work. The hook discovers the doc and injects an 800-token summary. Net saved = max(0, 29000 − 800) = **28,200 tokens**. At opus-4-7 rates (~$30/Mtok input output blended → call it $5/Mtok averaged), that's **≈ $0.14** of value for a consultation that cost maybe $0.002 in summarizer fees.

That's the kind of multiplier we want to be reporting weekly.

---

## 6. The MCP tool surface, after

The MCP shrinks dramatically. Today we have `enderai_begin_document`, `_update_document`, `_finish_document` plus the legacy case-based tools. After:

| Tool | Purpose | Who calls it |
|---|---|---|
| `taskforce_discover` | The discovery service. Same as the HTTP endpoint, exposed as MCP for harnesses that don't have hook support. | Hook (preferred) or agent (fallback) |
| `taskforce_read` | Read a specific document by id. Returns Summary + Details. | Agent, when it wants more than the preamble |
| `taskforce_pin` | Pin a specific document as the active doc for this session. Optional — the hook can do this automatically based on top match. | Agent |
| `taskforce_observe` | The observation service. | Stop hook + PostToolUse hook |
| `taskforce_session_log` | Return the current session's discovery + observe history. Powers the `/taskforce` slash command. | Agent or user |
| `taskforce_acknowledge` | Tell the backend which discovery matches actually made it into the prompt (vs dropped for budget). | Hook |
| `taskforce_request` | The existing escape hatch (raw HTTP). | Agent, rare |

We delete `begin_document`, `update_document`, `finish_document` once hooks prove out. We keep them deprecated for one release cycle so existing CLAUDE.md guidance doesn't break.

The case-based tools (`enderai_begin_case` etc.) can go away or stay — orthogonal to this brainstorm.

---

## 7. Migration plan (per-phase tickets)

Six phases, each independently shippable. The acceptance criteria are intentionally concrete so they can be the bottom of a Jira ticket.

### 7.1 Phase 1 — Discovery endpoint + MCP tool

**Goal:** expose the existing scoring engine as a first-class HTTP endpoint, with a paired MCP tool for harnesses without hook support. No behavior changes yet — this is the foundation.

**Files touched (backend):**
- new: `app/api/routes/taskforce.py` — `POST /api/v1/taskforce/discover`
- new: `app/core/taskforce/discover.py` — pulls candidates, calls scoring engine, formats response
- edit: `app/models.py` — add `METRICS_EVENT_DOCUMENT_CONSULTED = "document.consulted"`
- edit: `app/core/metrics/events.py` — new `record_document_consulted` emitter
- edit: `app/core/metrics/registry.py` — new `documents_consulted` count metric (composed=True)
- edit: `app/api/main.py` — wire the new router

**Files touched (MCP):**
- edit: `mcp/enderai-api-mcp/src/mcpServer.ts` — register `taskforce_discover` tool with `TaskforceDiscoverArgsSchema`
- new: `mcp/enderai-api-mcp/src/taskforce/discover.ts` — thin client around `/api/v1/taskforce/discover`

**Files touched (frontend):**
- none in this phase

**API contract:** §3.1 above.

**Tests:**
- backend unit: scoring engine still produces same matches given identical input as it does inside `enderai_begin_document`
- backend integration: `POST /taskforce/discover` returns matches, inserts `document.consulted` events
- MCP unit: zod accepts/rejects the schema correctly
- MCP integration: `taskforce_discover` tool, end-to-end through `createMcpServer`

**Acceptance:**
- `curl -X POST $API/api/v1/taskforce/discover -d '{"prompt":"…"}'` returns matches within 500ms p95
- Database has one `document.consulted` event per returned match
- `documents_consulted` metric available at `GET /v2/metrics?metrics=documents_consulted`

**Risk:** Low — additive.

**Ticket draft:**
> **Title:** TF-XXX: Phase 1 — Taskforce discovery endpoint + MCP tool
> **Summary:** Stand up `POST /api/v1/taskforce/discover` and a paired `taskforce_discover` MCP tool that returns the top 1–3 V2 documents related to a user prompt. Reuses the existing scoring engine. Records `document.consulted` events. No behavior changes elsewhere.
> **Acceptance:** see above.

---

### 7.2 Phase 2 — UserPromptSubmit hook + user-visible preamble

**Goal:** auto-inject related docs into the prompt and show the user what was injected.

**Files touched (new repo path):**
- new: `scripts/taskforce-hooks/user-prompt-submit.sh` — calls /discover, formats preamble, writes to stdout (for prompt injection) + stderr (for user banner)
- new: `scripts/taskforce-hooks/lib/format-preamble.sh` — token-budget-aware preamble formatter
- new: `scripts/taskforce-hooks/lib/auth.sh` — pulls bearer token from env or `~/.taskforce/credentials`
- new: `scripts/taskforce-hooks/install.sh` — copies hooks into `~/.claude/hooks/`, writes settings.json snippet

**Files touched (MCP):**
- new: `mcp/enderai-api-mcp/src/taskforce/sessionLog.ts` — handler for `taskforce_session_log` tool
- edit: `mcp/enderai-api-mcp/src/mcpServer.ts` — register the new tool

**Files touched (docs):**
- edit: `~/dev/CLAUDE.md` — replace V2 doc tool guidance with a "Taskforce hooks are installed; you don't need to do anything" section
- new: `~/dev/docs/taskforce-hooks-install.md` — setup instructions for new users

**Hook contract:**
- Claude Code's `UserPromptSubmit` hook gets `{ session_id, prompt, cwd }` on stdin and is expected to write either the modified prompt or empty string to stdout. Verified against Claude Code v0.20+.
- The hook is idempotent: if `/discover` returns no matches, it writes empty stdout and the user prompt is unchanged.

**User-visible surfaces (resolved decision §11.1.5):**
- **Banner** — one line to stderr: `[Taskforce] N related docs pulled · <titles> · /taskforce for details`
- **Slash command** — `/taskforce` invokes `taskforce_session_log` which returns the full preamble for the current session
- **Web widget** — deferred to Phase 4.5 (the "Recent activity" widget)

**Tests:**
- shell tests (`bats`) that drive the hook with fixture stdin and assert stdout/stderr shape
- integration test: a local Claude Code session with the hook installed, fixture `/discover` server, asserts preamble appears in agent context

**Acceptance:**
- A user with the hook installed runs `claude` in a repo with a related TF document, types a prompt, and sees:
  - The agent acts as if it knows about the related doc
  - The stderr banner appears in their terminal
  - `/taskforce` in the same session shows the preamble that was injected

**Risk:** Medium — depends on Claude Code's `UserPromptSubmit` hook surface staying stable. If Anthropic ships a breaking change, the hook breaks silently. Mitigation: hook prints `[Taskforce] hook schema mismatch — please update from <link>` on contract drift.

**Ticket draft:**
> **Title:** TF-XXX: Phase 2 — UserPromptSubmit hook + user-visible preamble
> **Summary:** Ship a reference Claude Code hook that calls /discover on every user prompt, injects up to 1500 tokens of related-work preamble into the prompt, and writes a one-line banner to stderr so the user knows what happened. Add a `taskforce_session_log` MCP tool to power a `/taskforce` slash command for on-demand inspection.

---

### 7.3 Phase 3 — Rediscovery cost column + new savings metric

**Goal:** add the structural `rediscovery_cost_tokens` to V2Document and ship the `avoided_rediscovery` metric. Dashboard remains visually unchanged in this phase (feature flag).

**Files touched (backend):**
- new alembic migration: `add_rediscovery_cost_to_v2_document.py` — `ALTER TABLE v2_document ADD COLUMN rediscovery_cost_tokens INTEGER NOT NULL DEFAULT 0;` + index
- edit: `app/models.py` — add `rediscovery_cost_tokens: int = 0` to `V2Document`
- new: `app/core/taskforce/rediscovery.py` — `compute_rediscovery_cost(doc) -> int` with the v1 formula
- edit: `app/core/v2_documents.py` — call `compute_rediscovery_cost` from `refresh_v2_document_token_counts` (so any path that updates tokens also updates rediscovery cost)
- edit: `app/core/metrics/registry.py` — add `avoided_rediscovery` MetricDefinition (composed)
- edit: `app/core/metrics/queries.py` — add bespoke aggregator for `avoided_rediscovery` summing `net_saved_tokens` from `document.consulted` event payloads
- edit: `app/core/metrics/events.py` — `record_document_consulted` now computes + writes `net_saved_tokens` into the event

**Files touched (frontend):**
- edit: `src/components/V2/Metrics/MetricsPage.tsx` — add a new "Avoided Rediscovery" card behind `feature_flags.taskforce_savings_v2`
- edit: `src/api/v2Metrics.ts` — type the new metric
- new: `src/components/V2/Metrics/MetricsMethodology.tsx` (or extend the existing methodology page) — show the formula with worked example

**Tests:**
- unit: rediscovery formula on fixture docs with known structure
- migration: forward + rollback
- integration: consult event records correct net_saved_tokens
- frontend: snapshot test of the new card

**Acceptance:**
- Every existing `v2_document` row has a non-null `rediscovery_cost_tokens` (backfill in migration: same compute as live path)
- `GET /v2/metrics?metrics=avoided_rediscovery` returns the new metric
- Behind feature flag, the dashboard renders a third card with the value

**Risk:** Medium — schema migration. Mitigation: column has a default; backfill is computed deterministically; rollback drops the column.

**Ticket draft:**
> **Title:** TF-XXX: Phase 3 — Rediscovery cost column + avoided_rediscovery metric
> **Summary:** Add `rediscovery_cost_tokens` to v2_document with a deterministic formula, record `net_saved_tokens` per `document.consulted` event, and expose `avoided_rediscovery` via /v2/metrics. New dashboard card is behind a feature flag until Phase 4 lands.

---

### 7.4 Phase 4 — Observe endpoint + Stop hook + PostToolUse hook

**Goal:** server-side summarizer + transcript ingestion, with mid-session checkpoints and final commit. **This is the phase that actually changes how the system feels.**

**Files touched (backend):**
- new: `app/api/routes/taskforce.py` — `POST /api/v1/taskforce/observe` (add to the file from Phase 1)
- new: `app/core/taskforce/observe.py` — orchestrator: materiality → summarize → persist
- new: `app/core/taskforce/summarizer.py` — calls haiku, parses structured output
- new: `app/core/taskforce/summarizer_prompt.md` — the fixed canonical prompt, versioned (`# version: 2026-05-21.1`)
- new: `app/core/taskforce/materiality.py` — deterministic check
- new: `app/core/taskforce/redaction.py` — deny-list-based secrets redaction
- new alembic migration: `add_taskforce_session_observe_audit.py` — audit table for checkpoint reconciliation
- edit: `app/core/metrics/events.py` — emit `tokens.consumed.taskforce_summarizer` after each summarization

**Files touched (MCP):**
- edit: `mcp/enderai-api-mcp/src/mcpServer.ts` — register `taskforce_observe` tool
- new: `mcp/enderai-api-mcp/src/taskforce/observe.ts` — thin client

**Files touched (hooks):**
- new: `scripts/taskforce-hooks/post-tool-use.sh` — tracks counter, fires `/observe` with `kind: "checkpoint"` every 10 tool calls or 5 minutes
- new: `scripts/taskforce-hooks/stop.sh` — fires `/observe` with `kind: "final"` exactly once per session
- edit: `scripts/taskforce-hooks/install.sh` — also installs these
- new: `scripts/taskforce-hooks/lib/state.sh` — read/write `~/.taskforce/session-state.json`
- new: `scripts/taskforce-hooks/lib/transcript.sh` — extract a redacted transcript delta since last observe

**Tests:**
- backend unit: materiality, redaction, summarizer prompt parsing
- backend integration: synthetic transcript → /observe → doc updated/created as expected
- backend integration: cost cap kicks in after $1/day
- backend integration: shadow mode (env var `TASKFORCE_OBSERVE_SHADOW=1`) — logs intent, doesn't write
- hook tests: PostToolUse counter, Stop dedup

**Rollout sequence (one week minimum):**
1. **Day 0–3**: ship behind shadow mode for the dev org. Log what we would have created/updated. Manually inspect a sample of decisions for quality.
2. **Day 4–6**: enable real writes for dev org only.
3. **Day 7+**: enable for all users.

**Acceptance:**
- A real Claude Code session that runs 12+ tool calls produces:
  - 1 checkpoint observe call after the 10th tool call (mid-session)
  - 1 final observe call at session end
  - The active document has fresh summary points / details sections reflecting the session work
- A real session that runs 1 tool call produces a "skipped: trivial session" response
- The methodology page shows the summarizer cost line item

**Risk:** High — this is where real behavior change happens. Mitigation: shadow mode, dev-org-only rollout, per-user daily cost cap, manual review of first 50 observations.

**Ticket draft:**
> **Title:** TF-XXX: Phase 4 — Observation endpoint, mid-session checkpoints, Stop hook
> **Summary:** Ship `POST /api/v1/taskforce/observe`, server-side haiku summarizer, materiality short-circuit, secrets redaction, and PostToolUse + Stop hooks. Rollout: shadow mode → dev org → all users.

---

### 7.5 Phase 5 — Deprecate legacy doc tools

**Goal:** stop telling agents to call `enderai_begin/update/finish_document`. Leave the tools functional one release cycle for backwards compat.

**Files touched:**
- edit: `mcp/enderai-api-mcp/src/mcpServer.ts` — prepend `[DEPRECATED — use Taskforce hooks instead]` to the descriptions of the three tools
- edit: `~/dev/CLAUDE.md` — remove the V2 doc workflow guidance (the bullet list under "Taskforce V2 Document Tools"); replace with "Taskforce hooks handle this automatically. See `taskforce-hooks-install.md`."
- edit: `~/dev/AGENTS.md` — same treatment
- edit: any other doc that mentions begin/update/finish_document — there are a handful

**Tests:**
- regression: legacy tools still functional (no behavior change in this phase, just deprecation labels)

**Acceptance:**
- CLAUDE.md and AGENTS.md no longer mention `enderai_begin_document` as the preferred path
- The legacy tools still work for any user who hasn't installed the hooks

**Risk:** Low.

**Ticket draft:**
> **Title:** TF-XXX: Phase 5 — Deprecate `enderai_*_document` tools
> **Summary:** Update CLAUDE.md / AGENTS.md to point at Taskforce hooks. Mark the legacy MCP tools as deprecated in their schema descriptions. Keep them functional for one release cycle.

---

### 7.6 Phase 6 — Rename `enderai-api` → `taskforce`

**Goal:** rebrand the MCP. Cosmetic but matters for adoption.

**Files touched:**
- rename: `mcp/enderai-api-mcp/` → `mcp/taskforce-mcp/` (or just rename the published name in package.json + the deploy config without moving the directory — cheaper)
- edit: all `enderai_*` MCP tool names → `taskforce_*` with aliases ("`enderai_begin_case` is now `taskforce_begin_case`; the old name is an alias for one release")
- edit: Render deploy config — service name, env vars referring to `ENDERAI_*` get `TASKFORCE_*` aliases
- edit: frontend / dashboard / docs / CLAUDE.md / AGENTS.md mentions
- edit: alexlee's `~/.claude/settings.json` (the actual config that lists MCP servers)

**Tests:**
- existing tests pass after rename (mostly mechanical search/replace)

**Acceptance:**
- `taskforce_*` tool names are the canonical ones in tool listings
- `enderai_*` aliases continue to work for one release
- One PR with a clear changelog and breaking-changes note

**Risk:** Low. Pure cosmetic.

**Ticket draft:**
> **Title:** TF-XXX: Phase 6 — Rename `enderai-api` MCP to `taskforce`
> **Summary:** Single PR rebrand. Tool names → `taskforce_*` with `enderai_*` aliases. Env vars → `TASKFORCE_*` with aliases. Update docs.

---

## 8. What can go wrong

- **Hook contract churn.** Claude Code's hook surface is still young. If `UserPromptSubmit` changes shape, the hook breaks silently. Mitigation: hook prints `[Taskforce] hook schema mismatch — please update from <link>` on contract drift; version the hook script and pin a min Claude Code version.
- **Discovery latency.** /discover has to return in < 500ms or the user feels lag before every prompt. The scoring engine today is fast (deterministic, in-memory after list query). The list query is unpaginated; in Phase 1 we cap at the last 200 docs by `updated_at` desc. If that's not enough, add a recency window or pre-warm a per-user cache.
- **Preamble pollution.** If discovery has poor precision, every prompt arrives with noise. Mitigation: aggressive `min_score`, log false-positive rates from `document.consulted` events that never lead to an outcome, tune τ from real data.
- **Stop-hook secrets.** Transcripts contain whatever the agent saw. We MUST redact obvious secrets before shipping the transcript. Use a deny-list (env-var names, `Authorization:` headers, JWT-shaped strings) — not perfect, but catches the 90% case. Document the leak surface in CLAUDE.md. Surface a `taskforce_redaction_test` MCP tool that takes a string and shows what the redactor would do, so users can verify before trusting it with sensitive sessions.
- **Summarizer divergence.** Different runs of the summarizer on the same transcript produce different deltas. Mitigation: fixed temperature 0, fixed prompt, version the prompt, write the version into the metrics_event payload so we can correlate doc quality regressions to prompt revs.
- **Cost of observation.** A user with a Claude Code in heavy use could trigger /observe 100× a day. At $0.005 per summarization that's $0.50/day per user, mostly burned on trivial sessions. The materiality short-circuit (don't summarize trivial sessions) is what keeps this affordable. Plus the per-user $1/day cap (§4.6).
- **Rediscovery cost gaming.** If the formula is mechanical, agents can inflate it by padding docs with empty commands or files. Mitigation: cap per-doc rediscovery_cost_tokens at 50k tokens. Re-tune coefficients quarterly from real data.
- **Checkpoint dedup races.** Two PostToolUse hooks fire in quick succession; both ship a checkpoint with the same index. Backend dedups by `(session_id, checkpoint_index)` on insert. Worst case we drop the later one.
- **Banner spam.** If every prompt gets a banner, even ones with no matches, the user banner-blinds. Solution: hook writes the banner **only when matches were injected**; silent on empty.

---

## 9. What stays out of scope here

- Org-scope metrics. The current personal-only design is fine for now; org rollup is a fan-out problem orthogonal to this redesign.
- Folder discovery (search folders by name). Discovery is doc-centric for now.
- Multi-user collaboration on a single doc during a live session. Today docs are owned by a user; sharing is read/write but isn't real-time-coauthor.
- The legacy case-based tools (`enderai_begin_case` and friends). They can coexist with this design; deciding their fate is a separate conversation.
- Vectorized / semantic search for discovery. Today's scoring is feature-based (tokens, files, symbols). Embeddings would help; later phase.

---

## 10. Concrete walkthrough (end-to-end)

Pulling §0 + §5.8 + the phase mechanics into one timeline:

```text
T+0      user: "fix the metrics card that says tokens used"

T+10ms   UserPromptSubmit hook fires
         POST /taskforce/discover {prompt: "fix the metrics card…", cwd: ".../EnderAI-frontend"}
         → 200 OK in 180ms
         → 2 matches: TF-156 (0.81), Library queue (0.42; below τ=0.5, dropped)

T+200ms  hook formats 400-token preamble for TF-156, writes to stdout
         hook writes "[Taskforce] 1 related doc pulled · TF-156 (0.81)" to stderr
         hook inserts `document.consulted` event (acknowledged=true, summary_tokens=400)

T+500ms  model receives augmented prompt; sees TF-156 summary
         model decides to read the metrics page code; runs Edit, Bash, etc.

T+12s    after 10th tool call: PostToolUse hook fires
         POST /taskforce/observe {kind: "checkpoint", transcript_delta: …, active_document_id: TF-156}
         → 200 OK in 1.2s; backend summarizes the delta, PATCHes TF-156

T+45s    user accepts the agent's change; agent stops

T+45.1s  Stop hook fires
         POST /taskforce/observe {kind: "final", transcript: full session, active_document_id: TF-156}
         → 200 OK; backend finalizes TF-156 with the Outcome, records summarizer cost

T+45.5s  metrics show:
         - 1 `document.consulted` (net_saved_tokens: 28200)
         - 2 `document.updated` (TF-156, twice)
         - 2 `tokens.consumed.taskforce_summarizer` (total ≈ 8k tokens)
         - net saved this session: 28,200 − 8,000 = 20,200 tokens (≈ $0.10)
         - Taskforce cost this session: $0.005
         - ratio: 20× cost recouped
```

That's the whole loop. The user typed one prompt; the model worked normally; the dashboard moved.

---

## 11. Decisions

### 11.1 Resolved (alexlee, 2026-05-21)

1. **Top 1–3 options, deterministic selection.** Discovery returns up to 3 above threshold. Hook auto-picks under token budget; agent can override via `taskforce_pin`. No human-in-the-loop selection step in v2.
2. **Mid-session + final checkpoints.** PostToolUse hook fires every 10 tool calls or 5 minutes (whichever first); Stop hook always fires once. PreCompact treated as a stretch goal in Phase 4.
3. **Use best-estimate coefficients now; tune quarterly.** Formula in §5.2 ships as-is. We log the inputs to every consultation so a future tuning pass can do regression against real "would-have-cost" labels (collected by hand from a sample).
4. **Keep `tokens.consumed`; show it as a positive.** Renamed sub-kinds (`taskforce_summarizer`, `taskforce_discovery`, `agent_session`). Dashboard headline includes "Taskforce returned Nx its cost" ratio.
5. **Show the preamble to the user.** Three surfaces: stderr banner (immediate), `/taskforce` slash command (on-demand), web "Recent activity" widget (durable).

### 11.2 Still open

- Should checkpoints PATCH the doc body live (visible to anyone with the doc open) or stage in a draft until Stop confirms? Probably live + tagged-as-tentative; final commit clears the tag.
- Do we want a per-doc privacy override ("never use this doc as discovery context", e.g. for a security incident write-up)? Easy to add later via a `discoverable: bool` column.
- Do we surface "Taskforce considered this but didn't inject" matches anywhere? Useful for tuning τ but might be noise.
- What's the right Claude Code hook contract version we pin against? Need to test against the current shipping version and write the schema-mismatch warning.
- How do we handle a session that spans multiple Claude Code invocations on the same active doc (user kills terminal, comes back an hour later)? Probably: `session_id` from the hook is per-invocation; `active_document_id` persists in `~/.taskforce/session-state.json` keyed by cwd + branch.

---

## 12. Why this is better, in one paragraph

Today, Taskforce asks the model to do things the model can't reliably do, and we're surprised when the dashboard reads zero. Tomorrow, Taskforce sits at the edges of the conversation — before the prompt with discovery, between tool calls and after Stop with observation — and the model just does its job. Savings becomes one number with a defensible story ("avoided rediscovery"), backed by structural properties of the document itself rather than the model's honesty about its own token counts. The user sees what Taskforce did on their behalf, every time, so trust accretes. The whole stack gets smaller, harder to misuse, and easier to explain.

---

## 13. Shipped state (2026-05-21)

Five of six phases merged in a single push across the EnderAI backend + MCP + EnderAI-frontend repos. The hooks are installed and validated locally; the smoke run moved the dashboard for the first time.

### 13.1 Phase status

| # | Phase | Status | PRs | Notes |
|---|---|---|---|---|
| 1 | Discovery endpoint + MCP tool | ✅ Done | `EnderAI#67` (backend) · `EnderAI#68` (MCP tool) | `POST /v2/taskforce/discover` live; 200ms p95 locally; `documents_consulted` metric exposed. |
| 2 | UserPromptSubmit hook + preamble + `taskforce_session_log` | ✅ Done | `EnderAI#70` (backend + MCP + scripts + docs) · `EnderAI#73` (installer fix) | Hook injects up to 1500-token preamble; stderr banner; `session_id` persisted on consult events; `GET /v2/taskforce/session-log` filters by session. |
| 3 | Rediscovery cost column + `avoided_rediscovery` metric | ✅ Done | `EnderAI#69` (backend + migration) · `EnderAI-frontend#122` (card + methodology) | `v2_document.rediscovery_cost_tokens` backfilled (rows show 8k–50k cap range); USD priced at claude-opus-4-7. Dashboard card behind `taskforce.flags.savings_v2` localStorage flag. |
| 4 | Observe endpoint + Stop + PostToolUse hooks | ✅ Done | `EnderAI#71` | Defaults to `TASKFORCE_OBSERVE_SHADOW=1`. Haiku summarizer (`claude-haiku-4-5`, prompt v `2026-05-21.1`). Per-user $1/day cost cap. Audit event `taskforce.observed`. |
| 5 | Deprecate legacy `enderai_*_document` tools | ✅ Done | `EnderAI#72` | `[DEPRECATED — …]` prefix on the three tool descriptions; tools still functional for one release. |
| 6 | Rename `enderai-api` → `taskforce` | 🟡 Partial | `EnderAI#72` (env vars + docs) | Env vars accept `TASKFORCE_*` (canonical) with `ENDERAI_*` fallback. **Tool-name renames deferred** to a follow-up — every existing user config still references `enderai_*`. |

### 13.2 Smoke run, end-to-end

After installing the hooks via `bash scripts/taskforce-hooks/install.sh`, three quick curls to the deployed backend on Render confirmed the chain:

```
discover → 200 — query_id returned, 3 matches with score + rediscovery_cost
observe  → 202 — gracefully skipped with reason: "no_managed_anthropic_key" (shadow mode default)
metrics  → 200 — documents_consulted: 3, avoided_rediscovery: 97,349 tokens, $0.49 USD
```

This is the first time the **Avoided Rediscovery** card moved off zero. The §0 picture is real.

### 13.3 Open items (in priority order)

1. **Set `ANTHROPIC_API_KEY` in the Render backend service env** so the observe endpoint's haiku summarizer can run. Until then, every `/observe` POST returns `reason: "no_managed_anthropic_key"` regardless of shadow mode.
2. **Flip `TASKFORCE_OBSERVE_SHADOW=0`** on Render once #1 is in and a manual review of the first 50 audit events (with `payload.would_patch_document_id` + `payload.would_patch_fields`) looks right. Per §7.4: shadow mode → dev-org only → all users, over ~7 days.
3. **Tune the scoring thresholds.** The default `min_score: 0.3` returned 0 matches against a literal prompt that should have been a strong hit. Either lower the default to ~0.15, or re-weight in `WEIGHTS` once enough consult data is logged to do real regression. Track in a new ticket.
4. **Phase 6 actual tool rename.** Add `taskforce_*` aliases for every `enderai_*` tool in the MCP. Low risk if done as a strict alias-and-keep-old; one-PR change. Deferred from the original sweep because it's the most surface-touching for the smallest user-visible value.
5. **Watch the `documents_consulted` precision.** First batch of three matches were all confidence-band `"low"` — that's fine for proof-of-life, but if we ship the dashboard to other users we want a healthier mix. Probably needs the §11.2 question on "show 'considered but didn't inject' matches" to get answered so we can tune τ from real data.
6. **Frontend `/taskforce` slash command.** Backend `taskforce_session_log` is wired and the MCP tool is exposed, but Claude Code doesn't have a built-in way to register a slash command from an MCP tool yet. Either the user types `taskforce_session_log({session_id: ...})` literally, or we wait for Claude Code's slash-command-from-MCP support to land. Leaving the MCP tool in place so future-Claude-Code can pick it up automatically.

### 13.4 Concrete files in the repo

If you're picking up the rest, these are the load-bearing pieces:

- `~/dev/EnderAI/scripts/taskforce-hooks/` — the three hooks + idempotent installer + README
- `~/dev/EnderAI/demo/full-stack-fastapi-template/backend/app/core/taskforce/` — `discover.py`, `scoring.py`, `rediscovery.py`, `materiality.py`, `redaction.py`, `summarizer.py` + `summarizer_prompt.md`, `observe.py`
- `~/dev/EnderAI/demo/full-stack-fastapi-template/backend/app/api/routes/taskforce.py` — `/discover`, `/observe`, `/session-log`
- `~/dev/EnderAI/mcp/enderai-api-mcp/src/taskforce/` — `discover.ts`, `sessionLog.ts` (thin clients)
- `~/dev/EnderAI/mcp/enderai-api-mcp/src/mcpServer.ts` — `TaskforceDiscoverArgsSchema`, `TaskforceSessionLogArgsSchema`, tool registrations
- `~/dev/EnderAI-frontend/src/components/V2/Metrics/MetricsPage.tsx` — feature-flagged Phase 3 card row
- `~/dev/EnderAI-frontend/src/components/V2/Metrics/methodology.md` — Phase 3 worked example
- `~/dev/EnderAI-frontend/src/hooks/usePersistentState.ts` — localStorage hook (also used for the savings_v2 feature flag)

### 13.5 What needed in-flight design changes

Two judgment calls during implementation that weren't in the original §7 plan:

- **Scoring engine port (§7.1)**. The plan assumed "reuses the existing scoring engine" — but that engine lives in TypeScript inside the MCP. For the HTTP endpoint to be callable from the shell hook, scoring had to be in Python. Shipped a pragmatic Python port (token jaccard + corpus overlap + file/symbol substring + 30-day recency decay) and explicitly skipped the conflict signals (tenant/repo/error-family) for v1. The TS engine still backs the deprecated `enderai_begin_document`. Divergence documented in `EnderAI#67`.
- **Tool-name renames (§7.6) deferred**. Every user's existing config references `enderai_*` names — flipping in a single PR would force an immediate config migration for every install. Shipped env-var aliases only; the actual tool-name rename is the only piece of v3 not yet in main.


---

## 14. v3.1 update (2026-05-21, post-§13)

Phase 6 closed via `EnderAI#74` — `taskforce_*` aliases now exist for all 11 lifecycle tools, dispatcher normalizes both names to the same handler. §13.1's Phase 6 row should now read **✅ Done**. Epic TF-174 transitioned to Done; all six children closed.

The one practical change that still wants doing — separate from this epic — is setting `ANTHROPIC_API_KEY` on the Render backend env and then flipping `TASKFORCE_OBSERVE_SHADOW=0`. That's the unlock for the observe-side haiku summarizer to actually patch documents instead of dry-running into audit events.

---

## 15. Hookless agents (Codex, Cursor, plain API)

The §0–§13 design optimizes for Claude Code's hook surface. Other agents need a parallel path that uses the same backend + the same metrics but doesn't depend on UserPromptSubmit / Stop / PostToolUse hooks. Without that path the dashboard only sees Claude Code traffic, which is a precision problem (we'd be measuring one harness instead of the actual value of Taskforce).

### 15.1 Three tiers

| Tier | Harness | UX | Mechanism | Status |
|---|---|---|---|---|
| 1 (best) | Claude Code with hooks | Fully automatic — agent does nothing special | Hooks (TF-176, TF-178) | ✅ Shipped |
| 2 (good) | Codex, Cursor, anything that supports MCP | Agent-driven explicit calls; ~2 tool calls per session | `taskforce_session_start` + `taskforce_session_observe` MCP tools | 📐 Planned (TF-181) |
| 3 (manual) | Pure Anthropic SDK, ChatGPT, custom harness | User-driven via a CLI wrapper | `taskforce-cli` binary | 📐 Planned (TF-182) |

Every tier hits the same backend endpoints, records to the same `metrics_event` table, and shows up on the same Avoided Rediscovery card. The differences are *who initiates* the calls and *how much UX polish* the agent gets.

### 15.2 Tier 2 — agent contract

Two MCP tools, two calls per session. The agent's system prompt (AGENTS.md, or whatever Codex/Cursor uses) reads:

> Before you start meaningful work on a user request, call `taskforce_session_start` with the user's prompt. The response gives you a `session_id` (remember it) and up to 3 related prior documents. Read them as context before responding.
>
> When the work is complete (or you're pausing), call `taskforce_session_observe` with that `session_id` and `kind: "final"`. The backend handles the document update; you do NOT need to call `enderai_begin_document` / `_update_document` / `_finish_document` separately.

That's the whole contract. Two tool calls per meaningful session, replacing the entire enderai_*_document lifecycle.

### 15.3 New MCP tools (TF-181)

**`taskforce_session_start({prompt, cwd?, files?, git_branch?, recent_commands?})`**

Returns:
```json
{
  "session_id": "uuid",
  "matches": [
    {"document_id": "...", "title": "...", "score": 0.74, "summary_markdown": "...", "rediscovery_cost_tokens": 17000}
  ],
  "suggested_pin": "<document_id of top match if confidence_band == 'high'>"
}
```

Internally:
- Mints a UUID for `session_id`.
- Calls `/v2/taskforce/discover` with the supplied context.
- Persists the optional `suggested_pin` as the session's active document (for Tier 2 there's no hook to do this).

**`taskforce_session_observe({session_id, kind, transcript?, files_touched?, commands_run?, summary_points?, decisions?, outcome?, harness_usage?})`**

Returns the standard `TaskforceObserveResponse` shape (action, document_id, patched_fields, reason, summarizer_usd_cost, shadow).

Two important differences from the hook-driven `/observe`:
- **Structured fields are first-class.** Tier 2 agents are unlikely to ship a full transcript blob; they'll provide `summary_points`, `decisions`, `files_touched` directly. When `transcript` is empty AND structured fields are present, the backend **skips the haiku summarizer** and uses the structured fields directly. Cheaper, no LLM call.
- **`harness_usage`** is the agent's self-reported token count for the session. Recorded as `tokens.consumed` with `subkind: "agent_session"`. Codex CAN see its own token usage end-of-turn; Cursor likely can too.

### 15.4 Tier 3 — `taskforce-cli`

For harnesses without MCP support (anyone calling Anthropic / OpenAI SDK directly, ChatGPT browser sessions with copy-paste, custom Python scripts):

```bash
# Discovery before a session
$ taskforce-cli discover --prompt "fix the metrics card" --cwd $PWD
{
  "session_id": "f3e7…",
  "matches": [...]
}

# Observation after
$ taskforce-cli observe --session-id f3e7… --kind final \
    --summary-points-file summary.txt \
    --files-touched src/foo.py,src/bar.py
{
  "action": "updated",
  "document_id": "...",
  "summarizer_usd_cost": "0.0023"
}
```

CLI is a thin Node binary (or shell + jq + curl, like the existing hooks). Same auth as the hooks (`~/.enderai_mcp_token`). Same JSON in/out as the MCP tools.

### 15.5 What's the same across tiers

- Backend endpoints (`/discover`, `/observe`, `/session-log`)
- Metrics events (`document.consulted`, `taskforce.observed`, `tokens.consumed` subkinds)
- Dashboard (Avoided Rediscovery card, methodology page)
- Document model (no schema change)
- Rediscovery cost formula
- Audit + shadow-mode mechanics

### 15.6 What's different

| Aspect | Tier 1 (hooks) | Tier 2 (MCP) | Tier 3 (CLI) |
|---|---|---|---|
| Discovery firing | Every prompt automatically | Once at `session_start` | Once when user runs the CLI |
| Observation firing | Every N tool calls + Stop | Once at `session_observe` | Once per CLI invocation |
| User sees preamble | stderr banner + augmented prompt | Agent decides whether to surface | Up to the harness |
| `session_id` source | Provided by Claude Code | Minted by `taskforce_session_start` | User-provided or generated by CLI |
| Transcript shipped | Yes (full session JSONL slice) | Optional (structured fields preferred) | Optional |
| Token usage reporting | Harness rollup (most accurate) | Agent self-report (degraded) | None unless user pipes it in |
| LLM cost on the backend | Haiku per observe call | Haiku only if transcript is supplied | Same as Tier 2 |

### 15.7 Compliance risk + mitigations

Tier 2 is less reliable than Tier 1 because the agent has to remember to call the tools.

- **Strong AGENTS.md instructions** ("call these two tools before/after meaningful work") — the same kind of contract that CLAUDE.md has had for enderai_begin_document, but smaller (2 tools instead of 4).
- **Per-harness compliance metric.** The dashboard surfaces a "sessions with both start + observe / sessions with start only" rate per `agent_session_cost.payload.model_id`. If a particular agent (e.g. Codex) skips observe a lot, we know.
- **`reminder` field.** The `taskforce_session_start` response includes an optional `reminder: "call taskforce_session_observe when you're done"` string the agent can echo to the user if it wants to keep them in the loop.

Tier 3 is fully manual; metric coverage is whatever the user is willing to run. That's fine — Tier 3 is for power users and one-off scripts, not the primary product surface.

### 15.8 Migration order

| Phase | Ticket | What | Why now |
|---|---|---|---|
| 7 | TF-181 | `taskforce_session_start` + `taskforce_session_observe` MCP tools, AGENTS.md update | Unblocks Codex + Cursor; small surface, ~1 day |
| 8 | TF-182 | `taskforce-cli` Node binary | Long tail; ~2 days |
| (open) | — | Codex-specific hooks if Codex adds a hook surface | Wait for Codex to ship a hook contract before designing |

### 15.9 Open questions

- **Should Tier 2's `taskforce_session_observe` deprecate the legacy `enderai_*_document` tools entirely?** They serve the same purpose for the same audience (hookless agents). Probably yes once Tier 2 soaks; remove a release after.
- **`session_id` lifecycle for Tier 2.** If the agent forgets to call observe, the session_id is orphaned. We could add a TTL ("sessions older than 30 days with no observe → auto-skipped") but that's noise. Easier: just let them dangle.
- **How does Tier 2 detect "no good match"?** If `taskforce_session_start` returns `matches: []`, the agent should still proceed normally. AGENTS.md needs to make this explicit ("empty matches is fine; just continue").

