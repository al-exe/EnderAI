# EnderAI Architecture Overview

## Purpose

This document is the current cross-repo map of EnderAI as it exists today.

It explains:

- which repository owns which runtime surface
- how the web app, backend, database, and hosted MCP service fit together
- which names are internal implementation terms versus user-facing product terms
- where the main productionization seams still are

This is a living architecture note, not a final design spec.

## Repositories and Responsibilities

### `EnderAI`

This repo currently owns the backend and hosted MCP integration.

Primary areas:

- `demo/full-stack-fastapi-template/backend`
  - FastAPI backend
  - SQLModel models and Alembic migrations
  - REST API routes for auth, items, agent credentials, threads, executions, artifacts, and workflow buckets
- `mcp/enderai-api-mcp`
  - hosted MCP bridge for EnderAI backend access
  - streamable HTTP MCP server
  - auth validation, session handling, and path compatibility logic
- `docs`
  - product, onboarding, and architecture notes

### `EnderAI-frontend`

This repo owns the browser application.

Primary areas:

- `src/routes`
  - TanStack Router route tree
- `src/components`
  - page and UI components
- `src/api`
  - handwritten API wrappers for domain screens
- `src/client`
  - generated OpenAPI client code
- `.github/workflows/deploy-frontend-pages.yml`
  - GitHub Pages deployment workflow

The frontend is the repo that serves the Pages-hosted UI.

## System Context

```text
browser user
  -> EnderAI-frontend (GitHub Pages static app)
  -> EnderAI backend API
  -> Postgres

local or remote agent client
  -> hosted EnderAI MCP service
  -> EnderAI backend API
  -> Postgres
```

The browser and MCP client both converge on the same backend API. The frontend is a UI client. The hosted MCP service is an agent-oriented API bridge, not a separate source of truth.

## Runtime Surfaces

### Web App Flow

1. A user opens the static frontend deployed from `EnderAI-frontend`.
2. The frontend authenticates against the backend login endpoints.
3. The frontend reads and mutates backend resources over `/api/v1/...`.
4. The backend persists state in Postgres.
5. The frontend presents translated product language on top of some still-legacy route and API names.

### Hosted MCP Flow

1. A user gets a user-scoped agent credential from EnderAI.
2. The frontend shows setup snippets for generic MCP clients and Codex CLI.
3. For Codex CLI, the currently recommended persistent setup stores the token in `~/.enderai_mcp_token`, protects it with `chmod 600`, and loads it into the shell from `~/.bashrc`.
4. The agent client sends `Authorization: Bearer <mcp token>` to the hosted MCP service.
5. The hosted MCP validates that token with the backend and reuses the resulting identity for backend API calls.
6. When execution-scoped auditing is provided, MCP-originated backend calls can be appended to the execution timeline.

This file-based local token setup is the current supported operator guidance and should remain intact until it is intentionally replaced by a different auth flow.

## Current Backend Shape

The backend currently exposes these major route groups:

- `/login` and user management
- `/agent-credentials`
- `/items`
- `/artifacts`
- `/workflow-buckets`
- `/threads`
- `/executions`
- `/utils`

The most important currently persisted product-adjacent records are:

- `Item`
  - separate demo/app data surface
- `AgentCredential`
  - user-scoped credential metadata for hosted MCP access
- `WorkflowBucket`
  - workflow grouping metadata
- `Thread`
  - current stored parent record for what the UI now raises as a `Topic`
- `Execution`
  - current stored work-session record for what the UI now raises as a `Case`
- `Event`
  - execution timeline/audit entries
- `Artifact`
  - saved memory/knowledge objects that are still API-level artifacts today

## Current Frontend Shape

The frontend now raises the following primary navigation concepts:

- `Dashboard`
- `Items`
- `Topics`
- `Cases`

Notes remain contextual rather than a primary top-level sidebar concept.

Important implementation detail: the user-facing copy has moved faster than the internal route names. Today that means:

- the Topics screen still lives on the `tasks` route
- the Cases screen still lives on the `executions` route
- the Notes screen still lives on the `library` route

That compatibility layer is acceptable for now, but it is intentionally temporary.

## Product Language vs Implementation Language

### Current user-facing language

The current intended product language is:

- `Topic`
- `Case`
- `Note` as contextual content, not a primary navigation object

### Current implementation language

Large parts of the backend and frontend API surface still use:

- `Thread`
- `Execution`
- `Artifact`

### Working translation

```text
Thread    -> Topic
Execution -> Case
Artifact  -> Note or case/topic memory, depending on presentation
```

This translation is what allows the UI and docs to move toward the target product model without forcing an unsafe one-shot backend rename.

## Target Model Direction

The intended direction remains the Topic / Case / ContextPack model.

In that model:

- `Topic` is the reusable area of work
- `Case` is a bounded work session under a topic
- `ContextPack` is synthesized hydration context for a new case
- note-like memory should support the work, but does not need to become a primary navigation primitive

The detailed model draft lives in `docs/topic-case-contextpack-model.md`.

## Important Current Seams

### 1. Naming drift between UI and backend

The UI is already raising Topics and Cases, while the stored/API model is still mostly Threads and Executions.

### 2. Schema lifecycle debt

Some memory-related table creation and backfill logic still lives in startup scripts rather than fully in migrations and operator runbooks.

### 3. Onboarding complexity is concentrated in one place

The Connect Agent flow is valuable, but its implementation and explanatory burden are still concentrated in a relatively large frontend surface.

### 4. MCP compatibility shims still exist

The hosted MCP layer still carries compatibility helpers such as deprecated path rewriting while the backend/API naming transition is incomplete.

## Recommended Near-Term Principles

- Keep one source of truth for persisted state: the backend database.
- Treat the hosted MCP service as a transport and auth bridge, not as an independent domain layer.
- Continue raising `Topic` and `Case` to users.
- Keep `Note` contextual and out of the main sidebar unless the product model changes.
- Preserve the current `chmod 600` token-file setup until a deliberate replacement is designed and shipped.
- Remove compatibility debt in phases rather than with a big-bang rename.

## Related Docs

- `docs/topic-case-contextpack-model.md`
- `docs/hosted-mcp-onboarding.md`
- `mcp/enderai-api-mcp/README.md`
- `demo/full-stack-fastapi-template/backend/README.md`
