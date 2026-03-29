# Codebase Concerns

**Analysis Date:** 2026-03-28

## Tech Debt

**Backend Domain Orchestration:**
- Issue: Topic visibility, rollup generation, match scoring, context-pack building, demo gating, and legacy ownership repair are concentrated in `demo/full-stack-fastapi-template/backend/app/core/topics.py`, with route-level orchestration duplicated across `demo/full-stack-fastapi-template/backend/app/api/routes/topics.py` and `demo/full-stack-fastapi-template/backend/app/api/routes/cases.py`.
- Files: `demo/full-stack-fastapi-template/backend/app/core/topics.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/topics.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/cases.py`, `demo/full-stack-fastapi-template/backend/app/core/search.py`
- Impact: small changes can regress visibility, rollups, matching, search, and read/write semantics at the same time.
- Fix approach: split ownership/visibility, rollups, topic matching, context-pack building, and search into separate modules with direct unit tests around each boundary.

**MCP Server Monolith:**
- Issue: tool schemas, session context, audit policy, request rewriting, compatibility behavior, and tool handlers are all implemented in `mcp/enderai-api-mcp/src/mcpServer.ts`.
- Files: `mcp/enderai-api-mcp/src/mcpServer.ts`, `mcp/enderai-api-mcp/src/httpServer.ts`, `mcp/enderai-api-mcp/src/deprecatedPathRewrite.ts`
- Impact: protocol fixes and product changes require touching a large, tightly coupled file with broad blast radius.
- Fix approach: extract tool-specific handlers, audit utilities, and session-context management into separate modules before adding more tools or auth modes.

**Template And Documentation Drift:**
- Issue: the backend still carries template-heavy operational docs, while architecture docs and workflows reference a frontend layout that is not present in this repo.
- Files: `demo/full-stack-fastapi-template/backend/README.md`, `docs/architecture-overview.md`, `.github/workflows/deploy-frontend-pages.yml`
- Impact: onboarding and deployment instructions are misleading, and dead automation paths can survive unnoticed.
- Fix approach: rewrite `demo/full-stack-fastapi-template/backend/README.md` for this repo, remove or fix stale frontend references, and align architecture docs with actual tracked directories.

## Known Bugs

**Backend Test Bootstrap Depends On Required Env Vars:**
- Symptoms: backend settings are instantiated at import time in `demo/full-stack-fastapi-template/backend/app/core/config.py`, so a clean test environment must provide `PROJECT_NAME`, `POSTGRES_SERVER`, `POSTGRES_USER`, `FIRST_SUPERUSER`, and `FIRST_SUPERUSER_PASSWORD` before the suite can start reliably.
- Files: `demo/full-stack-fastapi-template/backend/app/core/config.py`, `demo/full-stack-fastapi-template/backend/tests/conftest.py`, `demo/full-stack-fastapi-template/backend/README.md`
- Trigger: running the backend suite from a clean shell or CI job without a populated env/bootstrap step.
- Workaround: preload the required environment manually from an untracked local env file or CI secret set; no tracked example env file exists.

**Frontend Deploy Workflow Targets A Missing Directory:**
- Symptoms: `.github/workflows/deploy-frontend-pages.yml` uses `demo/full-stack-fastapi-template/frontend`, but `demo/full-stack-fastapi-template/frontend` does not exist.
- Files: `.github/workflows/deploy-frontend-pages.yml`, `docs/architecture-overview.md`
- Trigger: any GitHub Pages workflow run or any operator following the documented frontend structure.
- Workaround: none in this repo; the workflow and docs need to be corrected or removed.

## Security Considerations

**Shared MCP Token Can Collapse User Scoping:**
- Risk: `mcp/enderai-api-mcp/src/mcpAuth.ts` accepts `MCP_BEARER_TOKEN` without establishing a per-user identity, and downstream requests can still fall back to the operator token configured in `mcp/enderai-api-mcp/src/config.ts`.
- Files: `mcp/enderai-api-mcp/src/mcpAuth.ts`, `mcp/enderai-api-mcp/src/sessionAuth.ts`, `mcp/enderai-api-mcp/src/config.ts`, `mcp/enderai-api-mcp/src/httpServer.ts`, `mcp/enderai-api-mcp/src/mcpServer.ts`
- Current mitigation: docs recommend per-user MCP tokens and describe the shared token as optional.
- Recommendations: disallow shared-token mode on public deployments or fail fast when `MCP_BEARER_TOKEN` and `ENDERAI_BEARER_TOKEN` are both set.

**Audit Redaction Is Key-Name Based Only:**
- Risk: `redactSecrets()` preserves arbitrary string values, while `enderai_request` persists free-form `headers`, `json`, `text`, and `response` payloads into case events.
- Files: `mcp/enderai-api-mcp/src/mcpServer.ts`
- Current mitigation: a fixed sensitive-key allowlist and payload truncation via `capJson()`.
- Recommendations: redact by value patterns in addition to key names, avoid logging raw `text` bodies, and switch to explicit allowlisted audit fields.

**Hosted MCP Request Body Handling Is Unbounded:**
- Risk: `tryParseJsonBody()` buffers the entire request body in memory and the HTTP layer has no built-in rate or size limits.
- Files: `mcp/enderai-api-mcp/src/httpServer.ts`
- Current mitigation: session id validation and auth checks.
- Recommendations: add request-size limits in `httpServer.ts` and enforce upstream reverse-proxy limits and rate limiting for public deployments.

## Performance Bottlenecks

**Topic Listing And Counting Are Python-Bound:**
- Problem: `list_topic_models()` loads matching topics, filters owner/demo visibility in Python, and `count_topics()` repeats the same path with a hard-coded `10_000` limit.
- Files: `demo/full-stack-fastapi-template/backend/app/core/topics.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/topics.py`
- Cause: ownership is stored in JSONB arrays and visibility/count logic is not pushed into SQL.
- Improvement path: normalize ownership into queryable relations and replace Python-side counting with SQL-native filters and counts.

**Case Listing And Search Materialize Broad Tables:**
- Problem: `read_cases()` and `search_topics_and_cases()` load large case sets and score/filter them in Python after fetching related topics.
- Files: `demo/full-stack-fastapi-template/backend/app/api/routes/cases.py`, `demo/full-stack-fastapi-template/backend/app/core/search.py`, `demo/full-stack-fastapi-template/backend/app/models.py`
- Cause: view-model assembly and queryable state are mixed into JSONB-heavy records.
- Improvement path: add SQL-level owner scoping, indexes for common filters, and dedicated search/index structures instead of whole-table scans.

**Legacy Claim Bridge Runs In Normal Read Paths:**
- Problem: `claim_legacy_orphan_topics_for_owner()` can scan all topics and all topic-local cases during list, match, and context-pack requests.
- Files: `demo/full-stack-fastapi-template/backend/app/core/topics.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/topics.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/context_packs.py`
- Cause: compatibility cleanup is performed opportunistically during user traffic instead of in a one-time migration or admin task.
- Improvement path: move legacy claiming into an operator-only repair command or migration and remove the bridge from normal request paths.

**Agent Auth Turns Reads Into Writes:**
- Problem: `validate_agent_credential_token()` updates `last_used_at` and commits on every agent-authenticated request.
- Files: `demo/full-stack-fastapi-template/backend/app/api/deps.py`
- Cause: usage tracking is embedded directly in the request authentication dependency.
- Improvement path: debounce usage updates, batch them asynchronously, or record them at lower frequency.

## Fragile Areas

**Read Routes With Side Effects:**
- Files: `demo/full-stack-fastapi-template/backend/app/api/routes/topics.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/cases.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/search.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/context_packs.py`, `demo/full-stack-fastapi-template/backend/app/core/demo.py`, `demo/full-stack-fastapi-template/backend/app/core/topics.py`
- Why fragile: `ensure_demo_workspace()` and `claim_legacy_orphan_topics_for_owner()` can commit during GET, search, match, and hydration-building flows, so reads are not side-effect free.
- Safe modification: separate repair/demo-seeding from read APIs before adding caching, pagination improvements, or replica-based reads.
- Test coverage: `demo/full-stack-fastapi-template/backend/tests/api/test_demo_mode_api.py` and `demo/full-stack-fastapi-template/backend/tests/api/test_topic_rollups_api.py` cover happy paths, but not concurrency or repeated-read idempotency.

**JSONB-Centric Domain State:**
- Files: `demo/full-stack-fastapi-template/backend/app/models.py`, `demo/full-stack-fastapi-template/backend/app/core/cases.py`, `demo/full-stack-fastapi-template/backend/app/core/topics.py`
- Why fragile: `owner_ids`, `aliases`, `rollup_data`, `case_data`, and `context_pack_snapshot` carry behavior-critical state in schemaless blobs.
- Safe modification: move stable/queryable fields to first-class columns or join tables before expanding filtering, analytics, or authorization logic.
- Test coverage: endpoint serialization is covered, but schema-evolution and query-performance regressions are not.

**MCP Workflow State Machine:**
- Files: `mcp/enderai-api-mcp/src/mcpServer.ts`, `mcp/enderai-api-mcp/src/httpServer.ts`, `mcp/enderai-api-mcp/src/deprecatedPathRewrite.ts`
- Why fragile: active-case tracking, backward-compat path rewrites, audit recursion guards, and transport/session handling are interdependent.
- Safe modification: keep process-level compatibility tests around initialize flows, token rotation, rewritten paths, and active-case enforcement before refactoring.
- Test coverage: `mcp/enderai-api-mcp/test/caseWorkflowTools.test.ts` covers tool behavior, but there is no dedicated test suite for `mcp/enderai-api-mcp/src/httpServer.ts` behavior itself.

## Scaling Limits

**Hosted MCP Session Store:**
- Current capacity: one process-local `Map` in `mcp/enderai-api-mcp/src/httpServer.ts`; no TTL, eviction, or shared store.
- Limit: horizontal scaling requires sticky sessions, and abandoned sessions accumulate until the process exits.
- Scaling path: add session expiry/eviction plus shared storage or enforce single-replica sticky routing explicitly.

**Topic And Case Discovery:**
- Current capacity: list/search/match paths depend on in-memory filtering and explicit caps like the `10_000` topic scan in `demo/full-stack-fastapi-template/backend/app/core/topics.py` and `demo/full-stack-fastapi-template/backend/app/core/search.py`.
- Limit: larger datasets will degrade list, count, match, and context-pack build latency quickly.
- Scaling path: move visibility/count/search work into indexed SQL queries and precomputed search/rollup structures.

**Agent Usage Tracking:**
- Current capacity: one DB write per MCP-authenticated backend request via `demo/full-stack-fastapi-template/backend/app/api/deps.py`.
- Limit: frequent agent polling or chatty tool use will turn read-heavy traffic into write-heavy load.
- Scaling path: batch, sample, or asynchronously persist usage updates.

## Dependencies at Risk

**`@modelcontextprotocol/sdk`:**
- Risk: `mcp/enderai-api-mcp/src/httpServer.ts` already contains client-specific transport workarounds and a `globalThis.crypto` shim, so SDK or client behavior changes can break initialization or request routing.
- Impact: hosted MCP compatibility regressions across supported clients.
- Migration plan: pin upgrades deliberately and add dedicated tests around `mcp/enderai-api-mcp/src/httpServer.ts` before bumping SDK versions.

**`sqlmodel` Plus JSONB-First Modeling:**
- Risk: core behavior in `demo/full-stack-fastapi-template/backend/app/models.py` and `demo/full-stack-fastapi-template/backend/app/core/topics.py` depends on app-layer filtering instead of relational constraints and indexed joins.
- Impact: harder migrations, weaker query performance, and more brittle authorization logic as data grows.
- Migration plan: normalize ownership and search-critical fields first, then tighten query boundaries around the new schema.

## Missing Critical Features

**Backend CI Pipeline:**
- Problem: the repo only tracks `.github/workflows/deploy-frontend-pages.yml`; there is no backend or MCP test workflow.
- Blocks: automated regression detection for `demo/full-stack-fastapi-template/backend` and `mcp/enderai-api-mcp`.

**Environment Bootstrap Example:**
- Problem: `demo/full-stack-fastapi-template/backend/app/core/config.py` requires multiple env vars, but there is no tracked `.env.example`, `.env.sample`, or equivalent setup file.
- Blocks: reproducible local setup, backend CI provisioning, and reliable test bootstrapping.

**Hosted MCP Session Hardening:**
- Problem: `mcp/enderai-api-mcp/src/httpServer.ts` lacks session eviction, body-size limits, and rate limiting.
- Blocks: safe public multi-tenant deployment and predictable memory usage.

**Migration Safety Rails:**
- Problem: `demo/full-stack-fastapi-template/backend/app/alembic/versions/3c0e5c2e1d12_reset_to_topic_case_contextpack.py` drops legacy tables with `cascade` and recreates canonical tables without a tracked data-preserving upgrade path.
- Blocks: confident production schema evolution and rollback planning.

## Test Coverage Gaps

**HTTP Server Deployment Path:**
- What's not tested: auth flow, invalid session handling, body-size behavior, session eviction, and shared-token/operator-token combinations in `mcp/enderai-api-mcp/src/httpServer.ts`.
- Files: `mcp/enderai-api-mcp/src/httpServer.ts`, `mcp/enderai-api-mcp/src/mcpAuth.ts`, `mcp/enderai-api-mcp/src/config.ts`
- Risk: deploy-time regressions can slip past the green Vitest suite.
- Priority: High

**Backend Bootstrapping And Config Validation:**
- What's not tested: a tracked, repeatable setup path for required env vars and database initialization.
- Files: `demo/full-stack-fastapi-template/backend/app/core/config.py`, `demo/full-stack-fastapi-template/backend/tests/conftest.py`, `demo/full-stack-fastapi-template/backend/README.md`
- Risk: developers and CI can fail before the application tests even start.
- Priority: High

**Large-Dataset Performance Regressions:**
- What's not tested: list/search/context-pack performance under many topics, many cases, or heavy demo data.
- Files: `demo/full-stack-fastapi-template/backend/app/core/topics.py`, `demo/full-stack-fastapi-template/backend/app/core/search.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/cases.py`
- Risk: scaling regressions will surface only after tenant data grows in production.
- Priority: Medium

**Documentation And Workflow Consistency:**
- What's not tested: whether tracked docs and workflows point to real paths and runnable commands.
- Files: `.github/workflows/deploy-frontend-pages.yml`, `docs/architecture-overview.md`, `demo/full-stack-fastapi-template/backend/README.md`
- Risk: onboarding and release automation can fail even while application tests are green.
- Priority: Medium

---

*Concerns audit: 2026-03-28*
