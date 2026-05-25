# EnderAI Architecture Overview

## Purpose

This document is the current cross-repo map of EnderAI.

It explains:

- which repository owns which runtime surface
- how the frontend, backend, database, and hosted MCP service fit together
- which concepts are user-facing versus internal
- which deployment and operational boundaries matter today

## Repositories and Responsibilities

### `EnderAI`

This repo owns the backend, database migrations, hosted MCP bridge, and product docs.

Primary areas:

- `demo/full-stack-fastapi-template/backend`
  - FastAPI backend
  - SQLModel models and Alembic migrations
  - canonical Topic / Case / ContextPack API
  - auth, users, and agent credential flows
- `mcp/enderai-api-mcp`
  - hosted MCP bridge for EnderAI backend access
  - streamable HTTP MCP server
  - session handling and per-user backend auth forwarding
- `docs`
  - architecture, onboarding, and product notes

### `EnderAI-frontend`

This repo owns the browser application.

Primary areas:

- `src/routes`
  - TanStack Router route tree
- `src/components`
  - page and UI components
- `src/api`
  - handwritten API wrappers for product screens
- `src/client`
  - generated OpenAPI client code for shared auth/admin flows
- `.github/workflows/deploy-frontend-pages.yml`
  - GitHub Pages deployment workflow

The frontend repo serves the Pages-hosted UI.

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

The browser and MCP client converge on the same backend API. The frontend is the product UI. The hosted MCP service is an agent-oriented API bridge, not a separate source of truth.

## Product Surface

The user-facing product surface is now:

- `Dashboard`
- `Topics`
- `Cases`

There is no product-facing parallel top-level object model outside Dashboard, Topics, and Cases.

## Canonical Domain Model

### `Topic`

A Topic is the reusable area of work.

It groups related cases, tracks accumulated rollup knowledge, and anchors context selection.

### `Case`

A Case is a bounded work session under a Topic.

It carries the current summary, evidence, hypotheses, commands, changes, and the per-case hydration snapshot.

### `ContextPack`

A ContextPack is synthesized hydration context for a Case.

It is built from the Topic plus relevant prior cases and persisted as a case snapshot so the agent can reconstruct why a case started with a given context.

## Backend API Surface

The canonical product/domain endpoints are:

- `/api/v1/topics`
- `/api/v1/topics/{topic_id}`
- `/api/v1/topics/{topic_id}/rollup`
- `/api/v1/topics/match`
- `/api/v1/cases`
- `/api/v1/cases/{case_id}`
- `/api/v1/cases/{case_id}/memo`
- `/api/v1/cases/{case_id}/hydration`
- `/api/v1/cases/{case_id}/events`
- `/api/v1/context-packs/build`

Additional non-domain route groups remain for platform concerns such as:

- login
- users
- agent credentials
- utils

## Persistence Shape

The canonical domain tables are:

- `topic`
- `case_record`
- `case_event`

These are the only active product-domain tables the runtime depends on.

## Frontend Shape

The frontend uses:

- `/topics` for Topic browsing and detail
- `/cases` for Case browsing and detail
- `Dashboard` as the entry view

The main app shell should not surface any retired demo-template concepts.

## Hosted MCP Shape

The hosted MCP service exposes two guided workflows:

Taskforce V2 document workflow (preferred for V2-enabled users):

- `enderai_begin_document`
- `enderai_update_document`
- `enderai_finish_document`

Legacy V1 Topic/Case workflow (fallback when V2 is not enabled):

- `enderai_begin_case`
- `enderai_use_skill`
- `enderai_update_case`
- `enderai_finish_case`

Cross-cutting:

- `enderai_session_info` (returns the active V2 document handle and the active V1 case/topic ids)
- `enderai_request`
- `enderai_openapi`
- `enderai_health_check`

The V2 workflow is aligned to the per-user Taskforce V2 document model. `enderai_begin_document` runs deterministic congruence scoring against the user's documents and either reuses + self-heals a strong match or creates a fresh document. The V1 workflow is aligned to the Topic / Case / ContextPack model; `enderai_begin_case` and `enderai_use_skill` also sync matched generated Skills to local markdown files so agents can read task-specific workflow guidance before acting.

## Auth and Token Flow

The current hosted MCP token flow remains supported as-is:

- the user stores the MCP token locally in `~/.enderai_mcp_token`
- the file is protected with `chmod 600`
- shell startup loads it into the local environment for MCP-capable AI clients
- the hosted MCP validates that token and reuses the corresponding backend identity

This file-based setup remains the current supported guidance until intentionally replaced.
