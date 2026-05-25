# Technology Stack

**Analysis Date:** 2026-03-28

## Languages

**Primary:**
- Python 3.10+ - FastAPI backend code, SQLModel models, Alembic migrations, and backend scripts live under `demo/full-stack-fastapi-template/backend/app/`, `demo/full-stack-fastapi-template/backend/app/alembic/`, and `demo/full-stack-fastapi-template/backend/scripts/`. The production image is pinned to `python:3.10` in `demo/full-stack-fastapi-template/backend/Dockerfile`.
- TypeScript - Hosted MCP bridge code lives under `mcp/enderai-api-mcp/src/` and compiles to `mcp/enderai-api-mcp/dist/` via `tsc` declared in `mcp/enderai-api-mcp/package.json`.

**Secondary:**
- Bash - Container entrypoints and maintenance scripts live in `demo/full-stack-fastapi-template/backend/entrypoint.sh` and `demo/full-stack-fastapi-template/backend/scripts/*.sh`.
- Markdown and YAML - Product and ops docs live in `docs/*.md`; GitHub Actions config lives in `.github/workflows/deploy-frontend-pages.yml`.

## Runtime

**Environment:**
- Python 3.10 container runtime for the backend in `demo/full-stack-fastapi-template/backend/Dockerfile`.
- Node.js `>=18` for the MCP service in `mcp/enderai-api-mcp/package.json`.
- GitHub Actions uses Node 20 for the frontend Pages workflow in `.github/workflows/deploy-frontend-pages.yml`.

**Package Manager:**
- `uv` - Python dependency and virtualenv manager documented in `demo/full-stack-fastapi-template/backend/README.md` and used by `demo/full-stack-fastapi-template/backend/Dockerfile`.
- Lockfile: present as `demo/full-stack-fastapi-template/backend/uv.lock`.
- `npm` - Node package manager for the MCP bridge in `mcp/enderai-api-mcp/package.json`.
- Lockfile: present as `mcp/enderai-api-mcp/package-lock.json`.

## Frameworks

**Core:**
- FastAPI `>=0.114.2,<1.0.0` - Backend API framework declared in `demo/full-stack-fastapi-template/backend/pyproject.toml` and bootstrapped in `demo/full-stack-fastapi-template/backend/app/main.py`.
- SQLModel `>=0.0.21,<1.0.0` - ORM/model layer declared in `demo/full-stack-fastapi-template/backend/pyproject.toml` and implemented in `demo/full-stack-fastapi-template/backend/app/models.py`.
- Alembic `>=1.12.1,<2.0.0` - Schema migration tool declared in `demo/full-stack-fastapi-template/backend/pyproject.toml`; migration scripts live in `demo/full-stack-fastapi-template/backend/app/alembic/versions/`.
- Pydantic v2 and `pydantic-settings` - Request models and environment-backed settings in `demo/full-stack-fastapi-template/backend/app/models.py` and `demo/full-stack-fastapi-template/backend/app/core/config.py`.
- Model Context Protocol SDK `^1.0.0` - MCP server implementation in `mcp/enderai-api-mcp/src/mcpServer.ts` and `mcp/enderai-api-mcp/src/httpServer.ts`.

**Testing:**
- Pytest - Backend test runner configured in `demo/full-stack-fastapi-template/backend/pyproject.toml` and executed by `demo/full-stack-fastapi-template/backend/scripts/test.sh`.
- Coverage - Backend coverage reporting configured in `demo/full-stack-fastapi-template/backend/pyproject.toml` and `demo/full-stack-fastapi-template/backend/scripts/test.sh`.
- Vitest `^2.1.8` - MCP unit and smoke tests in `mcp/enderai-api-mcp/test/*.ts`, declared in `mcp/enderai-api-mcp/package.json`.

**Build/Dev:**
- `tsx` `^4.19.2` - Local TypeScript execution for `npm run dev` and smoke scripts in `mcp/enderai-api-mcp/package.json`.
- TypeScript `^5.7.3` - MCP compile step in `mcp/enderai-api-mcp/package.json` with config in `mcp/enderai-api-mcp/tsconfig.json`.
- Ruff - Backend lint and formatting checks in `demo/full-stack-fastapi-template/backend/pyproject.toml` and `demo/full-stack-fastapi-template/backend/scripts/lint.sh`.
- MyPy - Backend static typing in `demo/full-stack-fastapi-template/backend/pyproject.toml` and `demo/full-stack-fastapi-template/backend/scripts/lint.sh`.
- `fastapi run` - Backend process launcher in `demo/full-stack-fastapi-template/backend/entrypoint.sh`.

## Key Dependencies

**Critical:**
- `fastapi[standard]` - Request routing and application runtime in `demo/full-stack-fastapi-template/backend/app/main.py` and `demo/full-stack-fastapi-template/backend/app/api/main.py`.
- `sqlmodel` and `psycopg[binary]` - Postgres-backed persistence in `demo/full-stack-fastapi-template/backend/app/core/db.py` and `demo/full-stack-fastapi-template/backend/app/core/config.py`.
- `pyjwt` - JWT issuance and validation in `demo/full-stack-fastapi-template/backend/app/core/security.py`, `demo/full-stack-fastapi-template/backend/app/api/deps.py`, and `demo/full-stack-fastapi-template/backend/app/utils.py`.
- `pwdlib[argon2,bcrypt]` - Password hashing and verification in `demo/full-stack-fastapi-template/backend/app/core/security.py`.
- `@modelcontextprotocol/sdk` - Tool registration and streamable HTTP transport in `mcp/enderai-api-mcp/src/mcpServer.ts` and `mcp/enderai-api-mcp/src/httpServer.ts`.
- `zod` - MCP tool argument validation in `mcp/enderai-api-mcp/src/mcpServer.ts`.

**Infrastructure:**
- `sentry-sdk[fastapi]` - Optional error reporting initialized in `demo/full-stack-fastapi-template/backend/app/main.py`.
- `emails` and `jinja2` - SMTP email composition and template rendering in `demo/full-stack-fastapi-template/backend/app/utils.py` and `demo/full-stack-fastapi-template/backend/app/email-templates/build/*.html`.
- `python-multipart` and `email-validator` - Form parsing and email validation used by auth and user flows in `demo/full-stack-fastapi-template/backend/pyproject.toml` and `demo/full-stack-fastapi-template/backend/app/models.py`.

## Configuration

**Environment:**
- Backend settings are centralized in `demo/full-stack-fastapi-template/backend/app/core/config.py` via `BaseSettings`.
- The backend loads `../.env` relative to `demo/full-stack-fastapi-template/backend/app/core/config.py` if present; no `.env*` files were detected in the repository snapshot during this mapping pass.
- Required backend configuration comes from `PROJECT_NAME`, `SECRET_KEY`, `POSTGRES_SERVER`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `FIRST_SUPERUSER`, and `FIRST_SUPERUSER_PASSWORD` in `demo/full-stack-fastapi-template/backend/app/core/config.py`.
- Optional backend configuration comes from `ENVIRONMENT`, `FRONTEND_HOST`, `BACKEND_CORS_ORIGINS`, `SENTRY_DSN`, `SMTP_*`, `EMAILS_FROM_*`, and `EMAIL_TEST_USER` in `demo/full-stack-fastapi-template/backend/app/core/config.py`.
- MCP runtime configuration comes from `ENDERAI_BASE_URL`, `ENDERAI_BEARER_TOKEN`, `ENDERAI_TIMEOUT_MS`, `MCP_BEARER_TOKEN`, `MCP_PATH`, and `PORT` in `mcp/enderai-api-mcp/src/config.ts` and `mcp/enderai-api-mcp/src/httpServer.ts`.

**Build:**
- Python project metadata and tool config live in `demo/full-stack-fastapi-template/backend/pyproject.toml`.
- Backend container build config lives in `demo/full-stack-fastapi-template/backend/Dockerfile`.
- MCP package metadata and scripts live in `mcp/enderai-api-mcp/package.json`.
- MCP TypeScript compiler settings live in `mcp/enderai-api-mcp/tsconfig.json`.
- The only checked-in CI workflow is `.github/workflows/deploy-frontend-pages.yml`.
- No checked-in `docker-compose*.yml`, `render.yaml`, `railway.json`, `fly.toml`, `.nvmrc`, or `.python-version` files were detected in this repository snapshot.

## Platform Requirements

**Development:**
- Backend work assumes Python 3.10-compatible tooling with `uv sync` from `demo/full-stack-fastapi-template/backend/README.md`.
- Backend startup expects a reachable Postgres instance and runs migrations before serving in `demo/full-stack-fastapi-template/backend/entrypoint.sh` and `demo/full-stack-fastapi-template/backend/scripts/prestart.sh`.
- MCP development assumes Node 18+ with `npm install`, `npm run build`, and a reachable EnderAI backend URL as documented in `mcp/enderai-api-mcp/README.md`.
- Optional local integrations include SMTP for outbound email and Sentry for error reporting, both configured via `demo/full-stack-fastapi-template/backend/app/core/config.py`.

**Production:**
- The backend is packaged as a Dockerized FastAPI service that runs `alembic upgrade head` and then `fastapi run --workers 4 app/main.py` from `demo/full-stack-fastapi-template/backend/entrypoint.sh`.
- The hosted MCP is designed as an HTTP service exposing `/mcp` and `/health` from `mcp/enderai-api-mcp/src/httpServer.ts`.
- Default hosted URLs point at Render-hosted services in `mcp/enderai-api-mcp/src/config.ts` and `mcp/enderai-api-mcp/README.md`.
- GitHub Pages deployment is configured in `.github/workflows/deploy-frontend-pages.yml`, but the workflow target `demo/full-stack-fastapi-template/frontend` is not present in this repository snapshot; `docs/architecture-overview.md` states the browser app lives in a separate `EnderAI-frontend` repository.

---

*Stack analysis: 2026-03-28*
