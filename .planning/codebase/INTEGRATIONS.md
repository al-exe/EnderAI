# External Integrations

**Analysis Date:** 2026-03-28

## APIs & External Services

**Internal Service Boundary:**
- EnderAI backend API - Canonical product API consumed by browser clients and the hosted MCP bridge.
  - SDK/Client: direct FastAPI routes in `demo/full-stack-fastapi-template/backend/app/api/routes/*.py`; MCP-side HTTP wrapper in `mcp/enderai-api-mcp/src/http.ts`.
  - Auth: backend-issued bearer tokens validated in `demo/full-stack-fastapi-template/backend/app/api/deps.py`; MCP bridge defaults to `ENDERAI_BASE_URL` and optional `ENDERAI_BEARER_TOKEN` in `mcp/enderai-api-mcp/src/config.ts`.

**Hosted MCP Service:**
- Model Context Protocol HTTP service - Exposes the guided EnderAI tools to local or remote MCP clients.
  - SDK/Client: `@modelcontextprotocol/sdk` in `mcp/enderai-api-mcp/src/mcpServer.ts` and `mcp/enderai-api-mcp/src/httpServer.ts`.
  - Auth: inbound `Authorization: Bearer ...` validated by `mcp/enderai-api-mcp/src/mcpAuth.ts`; optional operator gate via `MCP_BEARER_TOKEN` in `mcp/enderai-api-mcp/src/httpServer.ts`.

**Email Delivery:**
- SMTP server - Password recovery and test-email flows send email through a configured SMTP host.
  - SDK/Client: `emails` plus Jinja templates in `demo/full-stack-fastapi-template/backend/app/utils.py`.
  - Auth: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAILS_FROM_EMAIL`, and `EMAILS_FROM_NAME` from `demo/full-stack-fastapi-template/backend/app/core/config.py`.

**Error Monitoring:**
- Sentry - Optional backend error and tracing export.
  - SDK/Client: `sentry-sdk[fastapi]` initialized in `demo/full-stack-fastapi-template/backend/app/main.py`.
  - Auth: `SENTRY_DSN` from `demo/full-stack-fastapi-template/backend/app/core/config.py`.

## Data Storage

**Databases:**
- PostgreSQL
  - Connection: `POSTGRES_SERVER`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` in `demo/full-stack-fastapi-template/backend/app/core/config.py`.
  - Client: SQLModel plus SQLAlchemy engine creation in `demo/full-stack-fastapi-template/backend/app/core/db.py`; migration management in `demo/full-stack-fastapi-template/backend/app/alembic/env.py` and `demo/full-stack-fastapi-template/backend/app/alembic/versions/*.py`.
  - Runtime tables include `user`, `agent_credential`, `topic`, `case_record`, and `case_event` from `demo/full-stack-fastapi-template/backend/app/models.py`.

**File Storage:**
- Local filesystem only
  - Email templates are read from `demo/full-stack-fastapi-template/backend/app/email-templates/build/` by `demo/full-stack-fastapi-template/backend/app/utils.py`.
  - No S3, GCS, Azure Blob, or other object-storage client imports were detected in `demo/full-stack-fastapi-template/backend/app/` or `mcp/enderai-api-mcp/src/`.

**Caching:**
- None
  - No Redis, Memcached, or cache-client imports were detected in `demo/full-stack-fastapi-template/backend/app/` or `mcp/enderai-api-mcp/src/`.

## Authentication & Identity

**Auth Provider:**
- Custom JWT auth issued and validated by the backend.
  - Implementation: access tokens are created in `demo/full-stack-fastapi-template/backend/app/core/security.py`, exposed at `POST /login/access-token` in `demo/full-stack-fastapi-template/backend/app/api/routes/login.py`, and validated through `OAuth2PasswordBearer` in `demo/full-stack-fastapi-template/backend/app/api/deps.py`.
  - Password hashing uses `pwdlib` with Argon2 and bcrypt in `demo/full-stack-fastapi-template/backend/app/core/security.py`.

**Agent Identity / MCP Tokens:**
- Per-user MCP credentials are issued and rotated by the backend, then reused by the hosted MCP.
  - Implementation: `POST /agent-credentials/`, `POST /agent-credentials/{credential_id}/rotate`, `POST /agent-credentials/validate-mcp-token`, and `DELETE /agent-credentials/{credential_id}` in `demo/full-stack-fastapi-template/backend/app/api/routes/agent_credentials.py`.
  - Hosted MCP validation path: `mcp/enderai-api-mcp/src/mcpAuth.ts` calls `/api/v1/agent-credentials/validate-mcp-token` and reuses the same bearer token for subsequent backend requests.
  - Product guidance for client setup lives in `docs/hosted-mcp-onboarding.md` and `docs/single-token-auto-hydrating-mcp-workflow.md`.

## Monitoring & Observability

**Error Tracking:**
- Sentry
  - Enabled only when `SENTRY_DSN` is set and `ENVIRONMENT != "local"` in `demo/full-stack-fastapi-template/backend/app/main.py`.

**Logs:**
- Python logging
  - `demo/full-stack-fastapi-template/backend/app/utils.py` configures `logging.basicConfig(level=logging.INFO)` and logs SMTP send results.
- Console logging
  - `mcp/enderai-api-mcp/src/httpServer.ts` logs MCP server startup to stdout.
- Case/event audit trail
  - The MCP bridge records workflow and low-level request events back into backend case events from `mcp/enderai-api-mcp/src/mcpServer.ts`; this is product-level audit data, not a third-party observability sink.

## CI/CD & Deployment

**Hosting:**
- Backend service
  - Packaged as a Docker image in `demo/full-stack-fastapi-template/backend/Dockerfile`.
  - Runtime command is `alembic upgrade head` followed by `fastapi run --workers 4 app/main.py` from `demo/full-stack-fastapi-template/backend/entrypoint.sh`.
- Hosted MCP service
  - Default documentation targets a Render-hosted endpoint in `mcp/enderai-api-mcp/README.md` and `mcp/enderai-api-mcp/src/config.ts`.
  - Streamable HTTP endpoint wiring lives in `mcp/enderai-api-mcp/src/httpServer.ts`.
- Frontend delivery
  - GitHub Pages deployment is defined in `.github/workflows/deploy-frontend-pages.yml`.
  - `docs/architecture-overview.md` says the browser app lives in a separate `EnderAI-frontend` repository; the workflow path `demo/full-stack-fastapi-template/frontend` is not present in this repository snapshot.

**CI Pipeline:**
- GitHub Actions
  - `.github/workflows/deploy-frontend-pages.yml` installs Node 20, requires `VITE_API_URL`, builds a frontend bundle, and deploys to GitHub Pages.
- Not detected
  - No checked-in backend CI workflow, MCP deploy workflow, `render.yaml`, or other platform deployment manifest was detected in this repository snapshot.

## Environment Configuration

**Required env vars:**
- Backend core: `PROJECT_NAME`, `SECRET_KEY`, `POSTGRES_SERVER`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `FIRST_SUPERUSER`, and `FIRST_SUPERUSER_PASSWORD` from `demo/full-stack-fastapi-template/backend/app/core/config.py`.
- Backend optional integration vars: `FRONTEND_HOST`, `BACKEND_CORS_ORIGINS`, `ENVIRONMENT`, `SENTRY_DSN`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAILS_FROM_EMAIL`, and `EMAILS_FROM_NAME` from `demo/full-stack-fastapi-template/backend/app/core/config.py`.
- MCP service: `ENDERAI_BASE_URL`, `ENDERAI_BEARER_TOKEN`, `ENDERAI_TIMEOUT_MS`, `MCP_BEARER_TOKEN`, `MCP_PATH`, and `PORT` from `mcp/enderai-api-mcp/src/config.ts` and `mcp/enderai-api-mcp/src/httpServer.ts`.
- Frontend deploy workflow: `VITE_API_URL` from `.github/workflows/deploy-frontend-pages.yml`.

**Secrets location:**
- Backend settings are loaded from process env and optionally `../.env` through `demo/full-stack-fastapi-template/backend/app/core/config.py`; no `.env*` files were detected in the repository snapshot.
- MCP server settings are loaded from process env in `mcp/enderai-api-mcp/src/config.ts` and `mcp/enderai-api-mcp/src/httpServer.ts`.
- User-side MCP token storage guidance lives in `docs/architecture-overview.md`, `docs/hosted-mcp-onboarding.md`, and `mcp/enderai-api-mcp/README.md`, which reference local client env usage such as `ENDERAI_MCP_TOKEN`.

## Webhooks & Callbacks

**Incoming:**
- Backend HTTP endpoints used by the MCP bridge:
  - `POST /api/v1/agent-credentials/validate-mcp-token` from `demo/full-stack-fastapi-template/backend/app/api/routes/agent_credentials.py`.
  - `GET /api/v1/users/me` from `demo/full-stack-fastapi-template/backend/app/api/routes/users.py`.
  - `GET/POST/PATCH` flows for `/api/v1/topics/*`, `/api/v1/cases/*`, and `POST /api/v1/context-packs/build` from `demo/full-stack-fastapi-template/backend/app/api/routes/topics.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/cases.py`, and `demo/full-stack-fastapi-template/backend/app/api/routes/context_packs.py`.
- Hosted MCP endpoints:
  - `GET /health` and `GET|POST|DELETE /mcp` from `mcp/enderai-api-mcp/src/httpServer.ts` and `mcp/enderai-api-mcp/README.md`.
- Password reset loop:
  - Recovery email links point to `FRONTEND_HOST/reset-password?token=...` from `demo/full-stack-fastapi-template/backend/app/utils.py`.
  - The backend consumes reset submissions at `POST /reset-password/` in `demo/full-stack-fastapi-template/backend/app/api/routes/login.py`.
- No third-party webhook receiver routes or callback handlers were detected. The only `hook` references are internal MCP contract tests in `demo/full-stack-fastapi-template/backend/tests/api/test_hook_routes_api.py` and `mcp/enderai-api-mcp/test/hookHealth.ts`.

**Outgoing:**
- SMTP email delivery from `demo/full-stack-fastapi-template/backend/app/utils.py`.
- MCP outbound HTTP calls to the backend API from `mcp/enderai-api-mcp/src/http.ts`, `mcp/enderai-api-mcp/src/mcpAuth.ts`, and `mcp/enderai-api-mcp/src/mcpServer.ts`.
- Sentry event export from `demo/full-stack-fastapi-template/backend/app/main.py` when `SENTRY_DSN` is configured.
- No outbound webhook dispatchers or third-party REST API clients were detected in `demo/full-stack-fastapi-template/backend/app/` or `mcp/enderai-api-mcp/src/`.

---

*Integration audit: 2026-03-28*
