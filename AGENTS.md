# EnderAI — Agent Rules (Layer 0, Portable)

Last updated: 2026-02-07

This file is the **single canonical ruleset** for agents working in this repo. It is written to be copy/pasted into other IDEs/agents as a starting template.

Optional local overrides (keep secret-free): `architecture/0-agents/agents.override` (template: `architecture/0-agents/agents.override.example`).

## IDE Integration Notes
- **Cursor:** add this file’s content to your Cursor project rules, or create a small `.cursor/rules/*.mdc` rule that instructs the agent to read and follow `AGENTS.md`.
- **Other IDE agents:** ensure your agent loads `AGENTS.md` at session start (or paste it into the IDE’s “default agent rules” setting).

## MCP Defaults (This Repo)
- MCP endpoint: `https://enderai-mcp.onrender.com/mcp`
- MCP auth header: `Authorization: Bearer enderai1`

## Core Priorities (Highest First)
1. **User control + least privilege**
   - Default to read-only actions.
   - Ask before risky/irreversible actions: deploys, pushing branches, opening PRs, deleting data/files, schema changes, DB writes, and any prod-like operations.
2. **Ground truth + audit trail**
   - Don’t guess. Anchor important claims in: code, tests, tool output, or recorded artifacts.
   - Keep an execution log during debugging (commands, key outputs, hypotheses, next check, and a clearly labeled **BREAKTHROUGH** when it starts working).
3. **Use EnderAI Memory via API (prefer MCP)**
   - Replace direct Postgres reads/writes with HTTP API calls (ideally through the MCP server).
   - Treat direct DB access as last-resort and require explicit user approval.
4. **Secrets never go in the repo or memory**
   - Don’t write backend passwords/access tokens/DB URLs to files, logs, or Library items. Redact and reference only.
   - The MCP demo token above is intentionally low-sensitivity for development; rotate it before any real deployment.

## Memory Model (Local + Remote)
### Local Library (Repo Files)
These are always available offline and should be treated as “local library”:
- **Layer 1 (Ground Truth):** `architecture/1-ground-truth/`
- **Layer 2 (Knowledge Base):** `architecture/2-knowledge-base/` (curated; update only after task completion)
- **Layer 3 (Task Context):** `architecture/3-task-context/` (live scratchpad / debug log)

Retention/hygiene:
- Layer 2/3 should include `Created` + `Last used`/`Last reviewed` timestamps.
- Prune or refresh Layer 2/3 content not used in the last ~7 days.

### Remote Library (EnderAI Backend)
EnderAI’s DB-backed memory is exposed via the backend API:
- **Tasks**: `GET /api/v1/tasks/`, `GET /api/v1/tasks/{task_id}`, `PATCH /api/v1/tasks/{task_id}`
- **Runs**: `GET /api/v1/tasks/{task_id}/runs`, `GET /api/v1/runs/{run_id}`, `GET /api/v1/runs/{run_id}/detail`
- **Library items**: `GET /api/v1/library/`, `GET /api/v1/library/{id}`, `GET /api/v1/library/workflow-keys`
  - Writes: `POST /api/v1/library/` and `PUT /api/v1/library/{id}` (may require superuser)

If a desired write isn’t supported by the API yet (for example: create run, append run_event, create run<->library link):
- Log it in Layer 3 `.mdc` and propose/implement the missing endpoint.
- Don’t default to direct SQL.

## MCP (Recommended Connector)
When configured, prefer using these MCP tools to access the backend:
- `enderai_health_check`
- `enderai_openapi`
- `enderai_request` (generic HTTP call; requires `path` starting with `/`)

Auth model (do not confuse these):
- **Client -> MCP server** auth: whatever your IDE config uses (for example `Authorization: Bearer <MCP_BEARER_TOKEN>` to `https://…/mcp`).
- **MCP server -> backend API** auth:
  - Obtain an `access_token` via `POST /api/v1/login/access-token`, then pass it as `bearerToken` on `enderai_request`, or
  - Set `ENDERAI_BEARER_TOKEN` in the MCP server environment.

Local backend instance:
- If you’re running EnderAI locally, set `ENDERAI_BASE_URL` to your local server (example: `http://localhost:8000`).

## Default “Start Of Task” Flow (Context Hydration)
1. Pick/confirm a `workflow_key` (short, stable identifier for the work stream).
2. Read remote memory first (minimal, targeted):
   - Tasks: `GET /api/v1/tasks/?workflow_key=...&q=...`
   - Library: `GET /api/v1/library/?workflow_key=...&q=...&current_only=true`
   - If needed: load runs for a candidate task, then `GET /api/v1/runs/{run_id}/detail` for audit trail + memory links.
3. Read local ground truth (Layer 1) and the most relevant Layer 2 entries.
4. Create/update a Layer 3 working log as you execute (especially in debug loops).
5. Execute the work. Keep changes reversible and evidence-backed.

## Default “End Of Task” Flow (Promotion)
1. Ensure Layer 1 and Layer 3 are up to date and reproducible.
2. Only after user confirms the task is done: promote stable learnings into Layer 2 (or into the remote Library via API, depending on desired persistence).
