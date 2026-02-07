# EnderAI — MCP-First Agent Rules (Portable Template)

Last updated: 2026-02-07

This is a clean, MCP-first rules template intended to be imported into new IDEs/agents. It assumes **no repo-specific local memory directories exist** and treats the EnderAI backend (via MCP) as the primary persistence layer.

## Top Priorities (Highest First)
1. **User control + least privilege**
   - Default to read-only actions.
   - Require explicit user confirmation before risky/irreversible actions: deploys, pushing branches, opening PRs, deleting data/files, schema changes, and any writes to production-like systems.
2. **Ground truth + auditability**
   - Don’t guess. If accuracy matters, validate with tool output (API responses, logs, tests).
   - When debugging, keep a step-by-step log: commands/requests, key outputs/errors, hypotheses, next check, and a clearly labeled **BREAKTHROUGH** when something starts working.
3. **MCP-first memory**
   - Read and write “memory” through the EnderAI backend API (preferably via MCP tools).
   - Do not connect directly to Postgres or run ad-hoc SQL unless the user explicitly approves it.
4. **Secrets never persist**
   - Never write passwords/tokens/DB URLs to files, tickets, or memory objects.
   - Redact secrets in any stored content; store references only.

## Required MCP Tools
Use these MCP tools (names may vary by client, but the intent is the same):
- `enderai_health_check`
- `enderai_openapi`
- `enderai_request` (generic HTTP request to the EnderAI backend)

## Auth Model (Do Not Confuse These)
There are two independent auth layers:
1. **IDE/Client -> MCP server** auth
   - Configured in the IDE MCP settings (example: `Authorization: Bearer <MCP_BEARER_TOKEN>`).
   - This protects the MCP endpoint itself (for example `https://.../mcp`).
2. **MCP server -> EnderAI backend API** auth
   - Obtain an `access_token` by calling `POST /api/v1/login/access-token`.
   - Pass that token to backend API calls as `bearerToken` in `enderai_request` (or configure the MCP server with `ENDERAI_BEARER_TOKEN` if you control the server environment).

Rules:
- Treat backend access tokens as ephemeral session secrets.
- Never store tokens in repo files or in EnderAI Library items.

## Memory: What To Read First (Context Hydration)
At the start of any task:
1. `enderai_health_check` to confirm connectivity.
2. `enderai_openapi` if you need to confirm endpoints/schemas.
3. Query existing memory:
   - Tasks: `GET /api/v1/tasks/` with filters (`workflow_key`, `q`, `status`, `skip`, `limit`)
   - Library: `GET /api/v1/library/` with filters (`workflow_key`, `kind`, `q`, `current_only`, `skip`, `limit`)
   - Workflow buckets: `GET /api/v1/library/workflow-keys`
4. If you need deeper audit context:
   - Runs for a task: `GET /api/v1/tasks/{task_id}/runs`
   - Full run detail: `GET /api/v1/runs/{run_id}/detail`

Injection rule:
- Summarize the minimal relevant items and include object IDs (`task_id`, `run_id`, `library_item.id`) so the user can audit and navigate.

## Memory: What To Write (When User Opts In)
Only write memory when the user explicitly opts in (examples: “log this”, “keep memory updated”).

Preferred write patterns:
- Rename/update task title: `PATCH /api/v1/tasks/{task_id}` with `{ "title": "..." }`
- Create reusable guidance (Library item): `POST /api/v1/library/` (may require elevated permissions)
- Update reusable guidance by superseding: `PUT /api/v1/library/{id}` (creates a new row; never edits in place)

If the backend API does not provide an endpoint for what you want to log (for example: runs, run events, links):
- Do not fall back to direct SQL by default.
- Keep an ephemeral worklog in the chat/IDE scratchpad and propose/implement the missing API endpoint.

## API Calling Conventions (Via `enderai_request`)
- Always send `path` starting with `/` (never a full URL).
- Use `json` for JSON bodies and `text` for non-JSON (don’t provide both).
- Prefer passing backend auth as `bearerToken` (avoid embedding secrets in headers or stored config).

## Common Failure Modes (MCP Transport)
- A transient `404 Not Found` from the MCP endpoint often indicates a stale session after a redeploy/spin-down. Retry so the client re-initializes.
- If hand-rolling MCP HTTP requests (not recommended), you must use JSON-RPC and include `Accept: application/json, text/event-stream`.

