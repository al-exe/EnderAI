# Architecture

**Analysis Date:** 2026-03-28

## Pattern Overview

**Overall:** Modular monolith backend with a separate hosted MCP bridge.

**Key Characteristics:**
- `demo/full-stack-fastapi-template/backend/app/main.py` mounts one FastAPI app, and `demo/full-stack-fastapi-template/backend/app/api/main.py` composes the entire HTTP surface from route modules.
- Route handlers in `demo/full-stack-fastapi-template/backend/app/api/routes/` stay thin and delegate topic, case, search, and demo behavior into `demo/full-stack-fastapi-template/backend/app/core/`.
- `demo/full-stack-fastapi-template/backend/app/models.py` is both the persistence schema hub and the API contract hub. SQLModel tables and public request/response models live in the same module.
- `mcp/enderai-api-mcp/src/mcpServer.ts` is a standalone TypeScript service layer that turns MCP tool calls into backend HTTP requests instead of sharing Python code directly.
- Runtime state is split between persisted product state in Postgres and ephemeral MCP session state held in memory inside `mcp/enderai-api-mcp/src/httpServer.ts` and `mcp/enderai-api-mcp/src/mcpServer.ts`.
- Browser UI code is not present in this checkout. `docs/architecture-overview.md` and `.github/workflows/deploy-frontend-pages.yml` reference a frontend surface, but no `frontend/` directory exists in the repository tree.

## Layers

**Backend HTTP Layer:**
- Purpose: Expose authenticated REST endpoints under `/api/v1`.
- Location: `demo/full-stack-fastapi-template/backend/app/main.py`, `demo/full-stack-fastapi-template/backend/app/api/main.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/`
- Contains: FastAPI app setup, router composition, dependency injection, request validation, HTTP error mapping.
- Depends on: `demo/full-stack-fastapi-template/backend/app/api/deps.py`, `demo/full-stack-fastapi-template/backend/app/core/`, `demo/full-stack-fastapi-template/backend/app/models.py`, `demo/full-stack-fastapi-template/backend/app/utils.py`, `demo/full-stack-fastapi-template/backend/app/crud.py`
- Used by: Direct product clients and the hosted MCP bridge in `mcp/enderai-api-mcp/src/`

**Domain/Application Layer:**
- Purpose: Implement Topic, Case, ContextPack, search, and demo-workspace behavior.
- Location: `demo/full-stack-fastapi-template/backend/app/core/`
- Contains: `topics.py`, `cases.py`, `search.py`, `demo.py`, plus config, DB, and security helpers.
- Depends on: `demo/full-stack-fastapi-template/backend/app/models.py`, SQLModel session access from `demo/full-stack-fastapi-template/backend/app/core/db.py`, and shared helper functions across `topics.py` and `cases.py`
- Used by: Route modules in `demo/full-stack-fastapi-template/backend/app/api/routes/` and bootstrap scripts such as `demo/full-stack-fastapi-template/backend/app/initial_data.py`

**Persistence and Schema Layer:**
- Purpose: Define database tables, public DTOs, database connectivity, and migrations.
- Location: `demo/full-stack-fastapi-template/backend/app/models.py`, `demo/full-stack-fastapi-template/backend/app/core/db.py`, `demo/full-stack-fastapi-template/backend/app/alembic/`
- Contains: SQLModel tables for `User`, `AgentCredential`, `Topic`, `CaseRecord`, and `CaseEvent`; API payload models such as `TopicPublic`, `CasePublic`, and `ContextPackBuildResult`; the SQLAlchemy engine; Alembic environment and version scripts.
- Depends on: Settings from `demo/full-stack-fastapi-template/backend/app/core/config.py`
- Used by: Route modules, core helpers, CRUD helpers, bootstrap scripts, and Alembic migrations

**Auth and Support Layer:**
- Purpose: Authenticate requests, issue tokens, hash passwords, send email, and perform basic user CRUD.
- Location: `demo/full-stack-fastapi-template/backend/app/api/deps.py`, `demo/full-stack-fastapi-template/backend/app/core/security.py`, `demo/full-stack-fastapi-template/backend/app/utils.py`, `demo/full-stack-fastapi-template/backend/app/crud.py`
- Contains: JWT decoding, OAuth2 dependency setup, agent credential validation, password hashing, reset-token helpers, email rendering/sending, and `User` CRUD.
- Depends on: `demo/full-stack-fastapi-template/backend/app/core/config.py` and `demo/full-stack-fastapi-template/backend/app/models.py`
- Used by: `demo/full-stack-fastapi-template/backend/app/api/routes/login.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/users.py`, and `demo/full-stack-fastapi-template/backend/app/api/routes/agent_credentials.py`

**Hosted MCP Layer:**
- Purpose: Expose EnderAI as MCP tools over stdio or streamable HTTP and proxy those tools to the backend API.
- Location: `mcp/enderai-api-mcp/src/`
- Contains: Stdio entrypoint in `mcp/enderai-api-mcp/src/index.ts`, HTTP server in `mcp/enderai-api-mcp/src/httpServer.ts`, tool implementation in `mcp/enderai-api-mcp/src/mcpServer.ts`, backend HTTP client in `mcp/enderai-api-mcp/src/http.ts`, and auth/session helpers in `mcp/enderai-api-mcp/src/mcpAuth.ts` and `mcp/enderai-api-mcp/src/sessionAuth.ts`
- Depends on: Backend `/api/v1/*` routes, `@modelcontextprotocol/sdk`, and runtime config from `mcp/enderai-api-mcp/src/config.ts`
- Used by: Agent clients connecting over stdio or HTTP

**Documentation and Planning Layer:**
- Purpose: Capture architecture intent, onboarding guidance, and planning artifacts outside runtime code.
- Location: `docs/`, `meta/`, `.planning/codebase/`
- Contains: Domain-model notes in `docs/topic-case-contextpack-model.md`, hosted MCP guidance in `docs/hosted-mcp-onboarding.md`, repo-level architecture notes in `docs/architecture-overview.md`, and generated planner docs under `.planning/codebase/`
- Depends on: Current runtime behavior in backend and MCP code
- Used by: Humans, planning workflows, and downstream execution agents

## Data Flow

**Backend Product Request Flow:**

1. `demo/full-stack-fastapi-template/backend/app/main.py` creates the FastAPI app and mounts `demo/full-stack-fastapi-template/backend/app/api/main.py` under `settings.API_V1_STR`.
2. `demo/full-stack-fastapi-template/backend/app/api/deps.py` opens a `Session(engine)` and resolves `CurrentUser` by decoding a JWT or agent credential token.
3. Route modules such as `demo/full-stack-fastapi-template/backend/app/api/routes/topics.py` and `demo/full-stack-fastapi-template/backend/app/api/routes/cases.py` validate request bodies using models from `demo/full-stack-fastapi-template/backend/app/models.py`.
4. Route handlers delegate work to `demo/full-stack-fastapi-template/backend/app/core/topics.py`, `demo/full-stack-fastapi-template/backend/app/core/cases.py`, `demo/full-stack-fastapi-template/backend/app/core/search.py`, or `demo/full-stack-fastapi-template/backend/app/core/demo.py`.
5. Core helpers read and write `Topic`, `CaseRecord`, and `CaseEvent` rows, update derived JSON rollups and hydration snapshots, and return public DTOs back through the route layer.

**Guided MCP Workflow Flow:**

1. `mcp/enderai-api-mcp/src/index.ts` or `mcp/enderai-api-mcp/src/httpServer.ts` creates a server from `mcp/enderai-api-mcp/src/mcpServer.ts`.
2. For HTTP transport, `mcp/enderai-api-mcp/src/httpServer.ts` validates the inbound bearer token through `mcp/enderai-api-mcp/src/mcpAuth.ts`, which calls backend route `/api/v1/agent-credentials/validate-mcp-token`.
3. `mcp/enderai-api-mcp/src/mcpServer.ts` handles `enderai_begin_case` by looking up or creating a topic through `/api/v1/topics/`, matching reusable topics through `/api/v1/topics/match`, optionally building a context pack through `/api/v1/context-packs/build`, and creating the case through `/api/v1/cases/`.
4. `enderai_update_case` and `enderai_finish_case` patch `/api/v1/cases/{case_id}` and append `/api/v1/cases/{case_id}/events`, while `enderai_request` proxies arbitrary backend endpoints through `mcp/enderai-api-mcp/src/http.ts`.
5. The MCP layer stores only the active `case_id` and `topic_id` in memory and reconciles them against the backend before later calls.

**Demo Workspace Flow:**

1. Routes that accept `demo=true` call `demo/full-stack-fastapi-template/backend/app/core/demo.py:ensure_demo_workspace`.
2. `ensure_demo_workspace` seeds demo `Topic` and `CaseRecord` rows for the current user when `User.demo_seeded_at` is still null.
3. Subsequent topic, case, match, and search operations filter visibility through demo-mode checks in `demo/full-stack-fastapi-template/backend/app/core/topics.py`.

**State Management:**
- Durable state lives in Postgres through SQLModel and Alembic, using tables defined in `demo/full-stack-fastapi-template/backend/app/models.py`.
- Derived state is stored inline in JSON-capable columns, especially `Topic.rollup_data`, `CaseRecord.case_data`, `CaseRecord.context_pack_snapshot`, and `CaseEvent.data` in `demo/full-stack-fastapi-template/backend/app/models.py`.
- Session-scoped MCP state is in-memory only, using `auditState` inside `mcp/enderai-api-mcp/src/mcpServer.ts` and the `sessions` map inside `mcp/enderai-api-mcp/src/httpServer.ts`.

## Key Abstractions

**Topic and Rollup:**
- Purpose: Represent a reusable area of work plus its aggregated memory.
- Examples: `demo/full-stack-fastapi-template/backend/app/models.py`, `demo/full-stack-fastapi-template/backend/app/core/topics.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/topics.py`
- Pattern: A normalized `Topic` row stores stable identity and owner metadata, while `demo/full-stack-fastapi-template/backend/app/core/topics.py` recomputes rollup summaries and canonical file/symbol/error lists from related cases.

**Case and Event Trail:**
- Purpose: Represent a bounded work session and its append-only event log.
- Examples: `demo/full-stack-fastapi-template/backend/app/models.py`, `demo/full-stack-fastapi-template/backend/app/core/cases.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/cases.py`
- Pattern: Scalar narrative fields such as `title`, `status`, `input_summary`, and `summary_current` stay on `CaseRecord`, while flexible evidence fields stay inside `case_data`; separate `CaseEvent` rows capture progress and MCP audit events.

**ContextPack Snapshot:**
- Purpose: Capture the hydration payload that a case started with.
- Examples: `demo/full-stack-fastapi-template/backend/app/models.py`, `demo/full-stack-fastapi-template/backend/app/core/topics.py`, `demo/full-stack-fastapi-template/backend/app/core/cases.py`
- Pattern: A context pack is built on demand from matched topics and ranked prior cases, then normalized into `CaseRecord.context_pack_snapshot` so later reads do not have to recompute the original hydration context.

**Ownership and Demo Visibility:**
- Purpose: Keep user data partitioned and separate live data from demo data.
- Examples: `demo/full-stack-fastapi-template/backend/app/core/topics.py`, `demo/full-stack-fastapi-template/backend/app/core/demo.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/topics.py`
- Pattern: Visibility is enforced in helper functions such as `_topic_visible_to_owner`, `_case_visible_to_owner`, and `_topic_matches_demo_mode`, with a compatibility path for claiming older ownerless topics.

**Hosted MCP Session Context:**
- Purpose: Keep one MCP session attached to one active case/topic pair.
- Examples: `mcp/enderai-api-mcp/src/mcpServer.ts`, `mcp/enderai-api-mcp/src/httpServer.ts`
- Pattern: The bridge stores active ids in memory, reconciles them against backend state before use, and prevents cross-case mutation until `enderai_finish_case` clears the session context.

## Entry Points

**Backend ASGI App:**
- Location: `demo/full-stack-fastapi-template/backend/app/main.py`
- Triggers: `fastapi run app/main.py`, container startup from `demo/full-stack-fastapi-template/backend/entrypoint.sh`
- Responsibilities: Create the FastAPI app, configure Sentry and CORS, and mount the API router under `/api/v1`

**Backend Container Startup:**
- Location: `demo/full-stack-fastapi-template/backend/entrypoint.sh`
- Triggers: Docker `CMD` from `demo/full-stack-fastapi-template/backend/Dockerfile`
- Responsibilities: Set `PYTHONPATH`, run Alembic migrations, and start the backend with four FastAPI workers

**Backend Prestart and Seed Scripts:**
- Location: `demo/full-stack-fastapi-template/backend/scripts/prestart.sh`, `demo/full-stack-fastapi-template/backend/app/backend_pre_start.py`, `demo/full-stack-fastapi-template/backend/app/initial_data.py`
- Triggers: Local/dev startup scripts and container prestart flows
- Responsibilities: Wait for the database, run migrations, and create the initial superuser

**MCP Stdio Server:**
- Location: `mcp/enderai-api-mcp/src/index.ts`
- Triggers: `npm run dev` or `npm start` inside `mcp/enderai-api-mcp`
- Responsibilities: Start a stdio MCP server for local agent integrations

**MCP Streamable HTTP Server:**
- Location: `mcp/enderai-api-mcp/src/httpServer.ts`
- Triggers: `npm run dev:http` or `npm run start:http` inside `mcp/enderai-api-mcp`
- Responsibilities: Expose `/health` plus a streamable HTTP MCP endpoint, validate tokens, create per-client sessions, and bind each session to a backend bearer token

**Pages Deployment Workflow:**
- Location: `.github/workflows/deploy-frontend-pages.yml`
- Triggers: Pushes to `main` affecting `frontend/**` or manual dispatch
- Responsibilities: Build and deploy a GitHub Pages frontend, but the referenced working directory `demo/full-stack-fastapi-template/frontend` is not present in this checkout

## Error Handling

**Strategy:** Validate early at the transport boundary, return explicit HTTP or MCP errors, and keep audit/event recording best-effort.

**Patterns:**
- Route modules such as `demo/full-stack-fastapi-template/backend/app/api/routes/topics.py` and `demo/full-stack-fastapi-template/backend/app/api/routes/cases.py` raise `HTTPException` for ownership, validation, and not-found conditions.
- Helper modules return `None` or raise `ValueError` for lookup/build failures, and the route layer translates those outcomes into HTTP responses. `demo/full-stack-fastapi-template/backend/app/api/routes/context_packs.py` is the clearest example.
- `mcp/enderai-api-mcp/src/http.ts` rejects unsafe paths, enforces timeouts, and normalizes JSON-versus-text request bodies before any outbound fetch.
- `mcp/enderai-api-mcp/src/mcpServer.ts` converts backend failures into tool errors with backend status details and redacts secret-like fields before persisting audit events.
- Audit writes in `mcp/enderai-api-mcp/src/mcpServer.ts` use best-effort helpers such as `tryCreateRunEvent` so a failed audit append does not fail the primary tool call.

## Cross-Cutting Concerns

**Logging:** Minimal process logging lives in `demo/full-stack-fastapi-template/backend/app/backend_pre_start.py`, `demo/full-stack-fastapi-template/backend/app/initial_data.py`, and `demo/full-stack-fastapi-template/backend/app/utils.py`. The Node HTTP server logs startup in `mcp/enderai-api-mcp/src/httpServer.ts` and writes uncaught errors to stderr in `mcp/enderai-api-mcp/src/index.ts`.

**Validation:** Backend request and response validation is centralized in `demo/full-stack-fastapi-template/backend/app/models.py` through SQLModel and Pydantic. MCP input validation is centralized in `mcp/enderai-api-mcp/src/mcpServer.ts` through Zod schemas.

**Authentication:** Backend auth is JWT-based in `demo/full-stack-fastapi-template/backend/app/core/security.py` and enforced through `demo/full-stack-fastapi-template/backend/app/api/deps.py`. Agent tokens are issued and rotated in `demo/full-stack-fastapi-template/backend/app/api/routes/agent_credentials.py`. Hosted MCP validates incoming tokens in `mcp/enderai-api-mcp/src/mcpAuth.ts` and forwards the same token to backend calls through `mcp/enderai-api-mcp/src/sessionAuth.ts`.

**Configuration:** Backend settings load from environment in `demo/full-stack-fastapi-template/backend/app/core/config.py`. MCP settings load from environment in `mcp/enderai-api-mcp/src/config.ts`. Startup scripts and Docker files treat those config modules as the only runtime configuration sources.

**Schema Evolution:** Database schema changes are versioned in `demo/full-stack-fastapi-template/backend/app/alembic/versions/` and wired through `demo/full-stack-fastapi-template/backend/app/alembic/env.py`. New persistent backend fields require updates to `demo/full-stack-fastapi-template/backend/app/models.py` plus a migration file in that directory.

---

*Architecture analysis: 2026-03-28*
