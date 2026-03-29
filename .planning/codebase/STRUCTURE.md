# Codebase Structure

**Analysis Date:** 2026-03-28

## Directory Layout

```text
[project-root]/
├── .github/workflows/                              # CI/deployment workflows
├── .planning/codebase/                             # Generated codebase reference docs
├── demo/full-stack-fastapi-template/backend/       # Python backend application, migrations, and tests
│   ├── app/                                        # Runtime backend package
│   │   ├── api/routes/                             # FastAPI route modules
│   │   ├── core/                                   # Domain, search, demo, auth, DB helpers
│   │   ├── alembic/versions/                       # Alembic migration history
│   │   └── email-templates/src/                    # MJML email source templates
│   ├── scripts/                                    # Lint, test, and prestart shell scripts
│   └── tests/                                      # Pytest suites
├── docs/                                           # Product and architecture notes
├── mcp/enderai-api-mcp/                            # TypeScript MCP bridge package
│   ├── src/                                        # MCP server, HTTP transport, auth, config
│   └── test/                                       # Vitest and smoke coverage for MCP behavior
└── meta/                                           # Supplemental project notes and exports
```

## Directory Purposes

**`demo/full-stack-fastapi-template/backend/app/`:**
- Purpose: Main backend package that FastAPI imports at runtime.
- Contains: `main.py`, `models.py`, `crud.py`, `utils.py`, route packages, core domain helpers, migration config, startup scripts, and email templates.
- Key files: `demo/full-stack-fastapi-template/backend/app/main.py`, `demo/full-stack-fastapi-template/backend/app/models.py`, `demo/full-stack-fastapi-template/backend/app/api/main.py`, `demo/full-stack-fastapi-template/backend/app/core/topics.py`

**`demo/full-stack-fastapi-template/backend/app/api/routes/`:**
- Purpose: One file per HTTP route group.
- Contains: `topics.py`, `cases.py`, `context_packs.py`, `search.py`, `agent_credentials.py`, `login.py`, `users.py`, `utils.py`, plus local-only `private.py`.
- Key files: `demo/full-stack-fastapi-template/backend/app/api/routes/topics.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/cases.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/agent_credentials.py`

**`demo/full-stack-fastapi-template/backend/app/core/`:**
- Purpose: Backend application logic that route modules call.
- Contains: Domain helpers for topics and cases, search logic, demo seeding, DB setup, config loading, and security helpers.
- Key files: `demo/full-stack-fastapi-template/backend/app/core/topics.py`, `demo/full-stack-fastapi-template/backend/app/core/cases.py`, `demo/full-stack-fastapi-template/backend/app/core/search.py`, `demo/full-stack-fastapi-template/backend/app/core/demo.py`, `demo/full-stack-fastapi-template/backend/app/core/db.py`

**`demo/full-stack-fastapi-template/backend/app/alembic/`:**
- Purpose: Alembic migration environment and revision history.
- Contains: `env.py`, migration template `script.py.mako`, and revision scripts under `versions/`.
- Key files: `demo/full-stack-fastapi-template/backend/app/alembic/env.py`, `demo/full-stack-fastapi-template/backend/app/alembic/versions/3c0e5c2e1d12_reset_to_topic_case_contextpack.py`, `demo/full-stack-fastapi-template/backend/app/alembic/versions/c4f5d9e7b2a1_add_demo_mode_seed_columns.py`

**`demo/full-stack-fastapi-template/backend/tests/`:**
- Purpose: Backend test suite organized by area.
- Contains: API tests under `tests/api/`, route-group tests under `tests/api/routes/`, CRUD tests, startup-script tests, and shared fixtures/utilities.
- Key files: `demo/full-stack-fastapi-template/backend/tests/conftest.py`, `demo/full-stack-fastapi-template/backend/tests/api/test_cases_api.py`, `demo/full-stack-fastapi-template/backend/tests/api/test_topic_rollups_api.py`

**`mcp/enderai-api-mcp/src/`:**
- Purpose: Hosted MCP package source.
- Contains: Stdio and HTTP entrypoints, MCP tool definitions, backend HTTP wrapper, auth helpers, config loading, and compatibility path rewrites.
- Key files: `mcp/enderai-api-mcp/src/index.ts`, `mcp/enderai-api-mcp/src/httpServer.ts`, `mcp/enderai-api-mcp/src/mcpServer.ts`, `mcp/enderai-api-mcp/src/http.ts`

**`mcp/enderai-api-mcp/test/`:**
- Purpose: MCP package verification.
- Contains: Unit tests, workflow tests, and smoke probes against required backend/MCP behavior.
- Key files: `mcp/enderai-api-mcp/test/caseWorkflowTools.test.ts`, `mcp/enderai-api-mcp/test/http.test.ts`, `mcp/enderai-api-mcp/test/streamableHttpSmoke.ts`

**`docs/`:**
- Purpose: Human-facing architecture, onboarding, and product-model notes.
- Contains: Canonical domain-model docs, hosted MCP onboarding docs, and repo-level architecture summaries.
- Key files: `docs/architecture-overview.md`, `docs/topic-case-contextpack-model.md`, `docs/single-token-auto-hydrating-mcp-workflow.md`

**`meta/`:**
- Purpose: Supplemental planning and exported artifacts that are not runtime code.
- Contains: Markdown notes, chat exports, and architecture metadata files.
- Key files: `meta/architecture.mdc`, `meta/application.mdc`, `meta/yc-ai-coding-highlights.md`

## Key File Locations

**Entry Points:**
- `demo/full-stack-fastapi-template/backend/app/main.py`: FastAPI application object and top-level middleware/router setup.
- `demo/full-stack-fastapi-template/backend/entrypoint.sh`: Container runtime entrypoint that migrates the database and starts FastAPI workers.
- `demo/full-stack-fastapi-template/backend/scripts/prestart.sh`: Dev/container prestart hook that waits for the DB, runs migrations, and seeds the initial user.
- `demo/full-stack-fastapi-template/backend/app/backend_pre_start.py`: Python DB-readiness probe used by prestart scripts.
- `demo/full-stack-fastapi-template/backend/app/initial_data.py`: Seeds initial application data through `init_db`.
- `mcp/enderai-api-mcp/src/index.ts`: MCP stdio entrypoint.
- `mcp/enderai-api-mcp/src/httpServer.ts`: MCP streamable HTTP entrypoint.

**Configuration:**
- `demo/full-stack-fastapi-template/backend/app/core/config.py`: Backend environment settings and derived values like CORS origins and DB URI.
- `demo/full-stack-fastapi-template/backend/pyproject.toml`: Python dependencies, mypy, Ruff, and coverage configuration.
- `demo/full-stack-fastapi-template/backend/alembic.ini`: Alembic configuration.
- `mcp/enderai-api-mcp/src/config.ts`: MCP environment loading for backend base URL, bearer token, and timeout.
- `mcp/enderai-api-mcp/package.json`: Node scripts for build, dev, start, smoke, and test.
- `mcp/enderai-api-mcp/tsconfig.json`: TypeScript compiler config for the MCP package.

**Core Logic:**
- `demo/full-stack-fastapi-template/backend/app/models.py`: Shared table definitions and API DTOs.
- `demo/full-stack-fastapi-template/backend/app/core/topics.py`: Topic identity, rollup, matching, context-pack building, and visibility rules.
- `demo/full-stack-fastapi-template/backend/app/core/cases.py`: Case normalization, patching, memo/hydration views, and event helpers.
- `demo/full-stack-fastapi-template/backend/app/core/search.py`: Cross-topic and cross-case search scoring.
- `demo/full-stack-fastapi-template/backend/app/core/demo.py`: Demo seed catalog and user demo-workspace bootstrap.
- `demo/full-stack-fastapi-template/backend/app/crud.py`: `User` CRUD and authentication helpers.
- `mcp/enderai-api-mcp/src/mcpServer.ts`: Guided MCP workflow and low-level request bridge.
- `mcp/enderai-api-mcp/src/http.ts`: Shared outbound backend fetch wrapper.
- `mcp/enderai-api-mcp/src/mcpAuth.ts`: Hosted MCP bearer-token validation.

**Testing:**
- `demo/full-stack-fastapi-template/backend/tests/conftest.py`: Shared backend test fixtures and client setup.
- `demo/full-stack-fastapi-template/backend/tests/api/`: API-level coverage for cases, topics, search, demo mode, and hook routes.
- `demo/full-stack-fastapi-template/backend/tests/api/routes/`: Focused tests for auth and user-management route groups.
- `mcp/enderai-api-mcp/test/caseWorkflowTools.test.ts`: Main guided-workflow contract test for MCP tools.
- `mcp/enderai-api-mcp/test/smoke.ts`: Stdio smoke test.
- `mcp/enderai-api-mcp/test/streamableHttpSmoke.ts`: HTTP transport smoke test.

**Referenced but Missing Paths:**
- `.github/workflows/deploy-frontend-pages.yml`: References `demo/full-stack-fastapi-template/frontend` as a Pages build directory.
- `docs/architecture-overview.md`: Describes a separate frontend repo rather than frontend code stored in this checkout.
- `demo/full-stack-fastapi-template/frontend`: Not detected in the repository tree. Do not place new code there unless that directory is intentionally restored first.

## Naming Conventions

**Files:**
- Backend Python modules use `snake_case.py`: `demo/full-stack-fastapi-template/backend/app/core/topics.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/agent_credentials.py`
- MCP TypeScript modules use lower camel-case or compound transport names: `mcp/enderai-api-mcp/src/httpServer.ts`, `mcp/enderai-api-mcp/src/sessionAuth.ts`
- Migration files use Alembic revision prefixes plus descriptive snake case: `demo/full-stack-fastapi-template/backend/app/alembic/versions/6f2b5e6c3a11_backfill_case_summary_current.py`
- Planner documents use uppercase names under `.planning/codebase/`: `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/STRUCTURE.md`

**Directories:**
- Backend runtime code is grouped by responsibility, not by bounded context: `api/routes`, `core`, `alembic`, `tests`
- Tests mirror the backend split by layer: `tests/api/`, `tests/api/routes/`, `tests/crud/`, `tests/scripts/`
- MCP package follows a standard Node package split: `src/` for source and `test/` for verification

## Where to Add New Code

**New Backend Feature:**
- Primary code: Add HTTP handlers in `demo/full-stack-fastapi-template/backend/app/api/routes/`, place orchestration and data-shaping logic in `demo/full-stack-fastapi-template/backend/app/core/`, and extend request/response models in `demo/full-stack-fastapi-template/backend/app/models.py`.
- Persistence: If the feature adds stored fields or tables, update `demo/full-stack-fastapi-template/backend/app/models.py` and add a matching Alembic revision in `demo/full-stack-fastapi-template/backend/app/alembic/versions/`.
- Tests: Add API coverage in `demo/full-stack-fastapi-template/backend/tests/api/` or `demo/full-stack-fastapi-template/backend/tests/api/routes/` depending on the scope.

**New MCP Capability:**
- Implementation: Add the tool schema and execution path in `mcp/enderai-api-mcp/src/mcpServer.ts`.
- Transport/auth support: Add helper modules beside the existing files in `mcp/enderai-api-mcp/src/` when the behavior is transport-specific or shared across tools.
- Tests: Add unit or workflow coverage under `mcp/enderai-api-mcp/test/`.

**Shared Utilities:**
- Backend shared helpers: Prefer `demo/full-stack-fastapi-template/backend/app/core/` for domain-aware helpers and `demo/full-stack-fastapi-template/backend/app/utils.py` only for generic email/token utilities already following that pattern.
- Auth and password utilities: Extend `demo/full-stack-fastapi-template/backend/app/core/security.py` or `demo/full-stack-fastapi-template/backend/app/api/deps.py` instead of scattering JWT logic through route modules.
- Documentation: Put runtime-facing product or onboarding notes under `docs/`, and generated planner references under `.planning/codebase/`.

## Special Directories

**`.planning/codebase/`:**
- Purpose: Generated architecture, stack, convention, testing, and concern docs for planning workflows.
- Generated: Yes
- Committed: Yes

**`demo/full-stack-fastapi-template/backend/app/alembic/versions/`:**
- Purpose: Database migration history.
- Generated: Yes, but revision files are maintained as source after generation.
- Committed: Yes

**`demo/full-stack-fastapi-template/backend/app/email-templates/src/`:**
- Purpose: MJML source templates that are converted into built HTML email templates.
- Generated: No
- Committed: Yes

**`mcp/enderai-api-mcp/test/`:**
- Purpose: Package-local verification for MCP behavior, transport behavior, and smoke checks.
- Generated: No
- Committed: Yes

**`meta/`:**
- Purpose: Supplemental notes and exports that inform humans but are not runtime code.
- Generated: Mixed
- Committed: Yes

---

*Structure analysis: 2026-03-28*
