> ⚠️ **ARCHIVED 2026-06-21 — historical; NOT current product direction.**
> Superseded by [`../../taskforce-northstar.md`](../../taskforce-northstar.md). Retained for reference only. Future agents: do not treat this as current guidance.

# Taskforce Codebase Audit — cut / add / no-regret essentials

*2026-05-30. Grounds the thesis (`thesis.md`, Addenda A–C) and competitor research (`research/`) against what's actually built. Repos: `~/dev/EnderAI` (backend + MCP), `~/dev/EnderAI-frontend`. Backend lives awkwardly under `EnderAI/demo/full-stack-fastapi-template/backend/` (abbreviated `backend/` below).*

> **One-line verdict:** the **metrics ledger is the crown jewel and is already thesis-shaped** (append-only, versioned pricing, measured-vs-estimated). The single highest-leverage move — good under *every* competitive axis — is to **extend that ledger with a cross-vendor provenance envelope.** The biggest cut is the **V1 topic-case-contextpack layer**, which carries most of the tech debt and looks superseded by V2 documents.

---

## What we have (inventory)
- **Backend:** modular-monolith FastAPI + SQLModel + Postgres/Alembic (forked from full-stack-fastapi-template). Routes: `v2_documents`, `v2_metrics`, `cases`, `topics`, `context_packs`, `skills`, `search`, `organizations`, `agent_credentials`, `billing`, `login`, `users`.
- **The metrics engine** (`backend/app/core/metrics/`: `events.py`, `savings.py`, `pricing.py`, `registry.py`, `rollup.py`, `queries.py`, `tokens.py`) — append-only event log + daily rollup + versioned pricing. **This is the ROI ledger from the thesis, already built.**
- **Two product generations:**
  - **V1 (legacy): topic → case → context-pack.** `Topic`/`CaseRecord`/`CaseEvent`/`Skill` models; `core/topics.py`+`cases.py`+`search.py`; MCP `enderai_begin_case` workflow; frontend `routes/_layout/{cases,topics,skills}`.
  - **V2 (current): documents + metrics.** `V2Document` (+ folders, shares, favorites), `MetricsEvent`; MCP `taskforce_begin_document`; frontend `routes/v2/{agents,library,metrics,search}` with a full UI (Agents detail/invocations/linked-knowledge, Metrics cards/breakdown/trend/methodology, Search chat+citations+BYOK, Library folders).
- **MCP bridge** (`mcp/enderai-api-mcp`, TypeScript): turns tool calls into backend HTTP; hosted (streamable HTTP) + stdio; per-user agent tokens. This is the **capture path / "sensor."**
- **Org + auth + billing:** Organizations (members admin/member, invitations), Firebase auth + JWT, per-user `AgentCredential` (rotating MCP tokens), full Stripe billing wired onto `User`.

## The crown jewel — keep & protect (it's already right)
`MetricsEvent` (`backend/app/models.py:1170`) + `savings.py` + `pricing.py` already embody the thesis:
- **Append-only event log** — emitters insert, never delete; they don't even commit (compose with the doc txn). `MetricsEvent` docstring literally says "Append-only." ✅ matches Addendum A (no hard delete).
- **Versioned pricing → reproducible USD** — every USD event FKs `ModelPricing(effective_from/to)`; "historical figures stay reproducible across price changes." ✅ the auditable property.
- **Measured vs estimated, cleanly separated** (`savings.py`): `cache_savings` + `summary_only_savings` = *measured*; `reuse_savings` = *estimated* (bootstrap = `min(20k, summary+details)`). ✅ **this is exactly the proven/estimated line from §5 / Addendum A5 — already quarantined.** The "naive reuse number" you flagged turn one is real, but it's correctly labeled estimated and capped.
- **Self-describing metric registry** (`registry.py`) — code-defined metrics, `GET /v2/metrics/definitions`. Clean.
- **Org-scoped reads** — `MetricsResponse.scope ∈ {personal, organization}`. ✅ partial cross-person already.

**Don't break these.** This is the most defensible code in the repo.

## The gap that defines the work (and the #1 no-regret add)
`MetricsEvent` provenance = `user_id, organization_id, document_id, model_id, pricing_id` only. **There is no vendor / harness / agent / repo / commit / session field**, and `TaskforceUsagePayload` is **Anthropic-shaped** (`cache_creation_input_tokens`, etc.). So the ledger is **single-tool by construction**, and the reuse atom (`document.reused`) is keyed to a Taskforce-owned `V2Document` — the same single-system pattern every competitor has (see `research/README.md`).

➡️ **No-regret essential #1: add the cross-vendor provenance envelope to `MetricsEvent` + the capture path** (vendor, harness/agent_credential_id, repo, commit, session, plus source-vs-consumer identity on reuse). This is the one change that converts a good single-tool metrics engine into the **cross-vendor reuse ledger that is the entire moat** — and it's good under *all three* competitive edges (Mem0=be the ledger, Letta=be neutral/cross-vendor, xMemory=extend provenance). Everything else is downstream of this.

---

## CUT
1. **V1 topic-case-contextpack layer** *(biggest, needs your sign-off)*. `Topic`/`CaseRecord`/`Skill` + `core/topics.py`/`cases.py`/`context_packs.py`/`search.py` + MCP `enderai_begin_case` + frontend `routes/_layout/{cases,topics,skills}`. It is **superseded by V2 documents** and carries the **bulk of `CONCERNS.md` tech debt**: JSONB-blob domain state (`owner_ids`, `rollup_data`, `case_data`), Python-bound listing with a hard-coded `10_000` cap, a **legacy-claim bridge that scans all topics during normal reads**, and **read routes with commit side-effects**. → *Decision: confirm V1 is deprecated; if yes, freeze then delete. This single cut removes most of the codebase's fragility.*
2. **Fork/template cruft.** The `demo/full-stack-fastapi-template/` nesting itself; template `email-templates/`, `items` boilerplate, `routes/private.py`; the **dead `.github/workflows/deploy-frontend-pages.yml`** (targets a nonexistent `frontend/` dir) and drifted template README (`CONCERNS.md` §Template Drift).
3. **Demo-mode side-effects in hot paths.** `ensure_demo_workspace()` / `claim_legacy_orphan_topics_for_owner()` commit during GETs/search (`CONCERNS.md` §Fragile Areas). Move seeding/repair to explicit admin/migration tasks; keep reads pure.
4. **Skills** *(evaluate, lean cut/defer)*. `Skill`/`GeneratedSkill` + `core/skills.py` + `SkillsPage`. Only keep if "reusable skill artifact" is on the chosen axis; otherwise it's surface area that dilutes the document+ledger story.

## ADD — no-regret essentials (good under any axis)
1. **Cross-vendor provenance envelope** (the #1 above) — `MetricsEvent` + capture fields for vendor/harness/agent/repo/commit/session; generalize `TaskforceUsagePayload` beyond Anthropic's shape.
2. **Cross-tool / cross-person reuse event** — a reuse atom that records *source provenance ≠ consumer provenance* (the flagship metric no single vendor can show). Builds directly on #1; `organization_id` already gives a head start on the cross-person half.
3. **Secret/PII scrub at the capture boundary** — `CONCERNS.md` flags audit redaction is *key-name only* (`redactSecrets()` keeps arbitrary values; raw `text`/`json` persisted). This is **literally the thesis's "scrub secrets at the boundary"** (Addendum A3) — redact by value pattern, allowlist audit fields. Security *and* thesis-required.
4. **MCP capture hardening** — kill the shared-token scoping collapse (per-user identity only), add session eviction/body-size/rate limits, and split the `mcpServer.ts` monolith. Capture is the moat edge under every axis; it's currently the most fragile, least-tested surface (`CONCERNS.md` §Security, §Scaling, §Test gaps).
5. **Table-stakes hygiene** — backend/MCP **CI** (none exists today), a tracked **`.env.example`** (config is import-time-required, breaks clean test bootstrap), and **migration safety rails** (a tracked migration drops legacy tables with `cascade` and no data-preserving path).

## Already-right — protect, don't regress
Append-only event log · versioned pricing/reproducible USD · measured-vs-estimated split · org-scoped metrics · the self-describing metric registry · `CaseEvent.supersedes_event_id` (supersession instinct already present even in V1).

---

## Decisions (resolved 2026-05-30)
- ✅ **V1 (topics/cases/context-packs) is DEPRECATED** — cut it. (Alex, 2026-05-30.) Execution plan: `taskforce-v1-deprecation-and-defork-plan.md`.
- ✅ **De-fork the `demo/full-stack-fastapi-template/` nesting** — approved. (Alex, 2026-05-30.)
- ⏸️ **Skills — keep or cut?** Still open. Likely folds into the V1 cut if Skills source from Topics/Cases (tracing this).

## How this maps to the axes (thesis Addendum C)
The provenance envelope + cross-tool reuse event + vendor-neutral capture are **no-regret precisely because they serve all three edges**: they make us the *neutral record + ledger* (vs Mem0), enable *cross-vendor capture* (vs Letta the harness), and *extend provenance to priced cross-org reuse* (vs xMemory). Build the envelope first; sequence the rest behind whichever edge you wedge on.

## Design critique (`docs/design/mockups/`)
*Read the `expressive` landing + metrics variants through the thesis lens. (There's also a `Taskforce UI Critique.html` I didn't cross-reference — this critique is specifically about thesis-alignment.)*

**What's already strong (keep):**
- **Cross-vendor is on the landing** — *"reads what your team did in Cursor and Claude Code"* + a live "Cursor + Taskforce MCP" terminal. That's the neutrality edge (vs Letta) made visible. ✅
- **Cross-person is on the metrics page** — *"128 reuses · 7 specialists · 5 engineers,"* and a "Where savings came from" leaderboard attributing reuse to docs **and people** (@alex·billing, @ana·infra). ✅
- **Provenance instinct** — terminal cites linkable anchors (*"see anchor §3," "tax-rates rollout §5"*), and the pitch is *"distills decisions into linkable documents"* (record framing, not raw memory). ✅
- **Counterfactual framing** — *"vs cold start 5.6×," "0 tokens spent on rediscovery."* ✅

**The core miss (both surfaces): they sell the *claim*, not the *proof*.**
1. **No single-instance auditability — the #1 gap.** The metrics page leads with *"You saved 412,840 tokens this week"* and aggregate panels — i.e., exactly the dashboard every competitor ships (`research/README.md`). There's **no drill-down from a number to ONE verifiable reuse event** (which doc, which commit, which agent, surfaced→used→provenance). That drill-down *is* the moat (Addendum A5: "a skeptic can drill into ONE instance and verify"). Add it and the page stops looking like Mem0's.
2. **Proven-vs-estimated is hidden — expose it.** The backend cleanly separates *measured* (cache/summary) from *estimated* (reuse-bootstrap, 20k cap); the UI collapses both into one "412K" number. That's the move that makes everyone's numbers untrustworthy. **Surface the split** ("318K measured · 94K estimated — adjust assumptions →") and make the estimate buyer-adjustable. Honesty-as-differentiation, straight at the benchmark-credibility war.
3. **Lead with the record/ledger, not "memory."** The landing eyebrow is *"AI work memory"* and H1 *"Stop re-explaining your codebase"* — the commodity noun (Addendum C). Keep the great cross-vendor terminal, but headline the **neutral system-of-record + provable ROI**, and name the **neutrality** explicitly ("works across every tool, owned by none").
4. **Fix the dollar framing.** *"≈ $7.84 saved"* this week actively undercuts the pitch — looks trivial. Annualize/project it, or shift the buyer denomination to throughput/incidents ("tokens prove, throughput prices," §5).
5. **Surface cross-*tool* reuse, not just cross-person.** The leaderboard shows people/areas; add the **tool dimension** — "written in Claude Code, reused in Cursor by a different engineer" is the flagship number no single vendor can show. It's the most differentiated thing you could put on screen and it's currently absent.

**Net:** the mockups have the right *ingredients* (cross-vendor, cross-person, citations, counterfactual) but plate them as a conventional savings dashboard. Re-rank the hierarchy around **auditability + the cross-boundary reuse event + proven-vs-estimated honesty**, and demote the raw aggregate token number from hero to supporting — that's the difference between "another memory tool's dashboard" and "the neutral ROI ledger nobody else can show."
