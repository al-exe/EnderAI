# EnderAI — MCP-First Agent Rules (Portable Template)

Last updated: 2026-02-07

This is a clean, MCP-first rules template intended to be imported into new IDEs/agents. It assumes **no repo-specific local memory directories exist** and treats the EnderAI backend (via MCP) as the primary persistence layer.

## IDE Setup (One-Time)
- Configure an MCP server entry that points to your deployed MCP endpoint (example: `https://enderai-mcp.onrender.com/mcp`).
- If the MCP server is protected, configure `Authorization: Bearer enderai1` in your IDE.
- Do a quick sanity check:
  - Visit `https://enderai-mcp.onrender.com/health` and confirm it returns `ok`.
  - Run `enderai_health_check` via the IDE’s MCP tool picker.

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
   - Default MCP endpoint: `https://enderai-mcp.onrender.com/mcp`
   - Default header: `Authorization: Bearer enderai1`
   - This protects the MCP endpoint itself (for example `https://.../mcp`).
2. **MCP server -> EnderAI backend API** auth
   - Obtain an `access_token` by calling `POST /api/v1/login/access-token`.
    - Pass that token to backend API calls as `bearerToken` in `enderai_request` (or configure the MCP server with `ENDERAI_BEARER_TOKEN` if you control the server environment).

Rules:
- Treat backend access tokens as ephemeral session secrets.
- Never store tokens in repo files or in EnderAI Library items.

## Default Start-Of-Task Flow (Context Hydration)
1. Decide on a `workflow_key` (short, stable identifier for the workstream). If unsure, query workflow buckets: `GET /api/v1/library/workflow-keys`.
2. Fetch only the memory you need to avoid noise:
   - Tasks: `GET /api/v1/tasks/?workflow_key=...&q=...`
   - Library: `GET /api/v1/library/?workflow_key=...&q=...&current_only=true`
3. If you need deeper “what happened last time” context:
   - Runs: `GET /api/v1/tasks/{task_id}/runs`, then `GET /api/v1/runs/{run_id}/detail`
4. Inject the retrieved context into the current plan:
   - Summarize the minimal relevant items and include IDs (`task_id`, `run_id`, `library_item.id`) so the user can audit and navigate.

## Memory: What To Write (When User Opts In)
Only write memory when the user explicitly opts in (examples: “log this”, “keep memory updated”).

Preferred write patterns:
- Rename/update task title: `PATCH /api/v1/tasks/{task_id}` with `{ "title": "..." }`
- Create reusable guidance (Library item): `POST /api/v1/library/` (may require elevated permissions)
- Update reusable guidance by superseding: `PUT /api/v1/library/{id}` (creates a new row; never edits in place)

If the backend API does not provide an endpoint for what you want to log (for example: runs, run events, links):
- Do not fall back to direct SQL by default.
- Keep an ephemeral worklog in the chat/IDE scratchpad and propose/implement the missing API endpoint.

## Default End-Of-Task Flow (Promotion)
1. Confirm with the user what should become durable memory (what’s reusable vs task-specific).
2. Prefer “durable, reusable” content in Library items (supersede instead of editing in place).
3. Prefer task hygiene updates that keep navigation easy (rename task titles to match reality).
4. Never store secrets in written memory.

## API Calling Conventions (Via `enderai_request`)
- Always send `path` starting with `/` (never a full URL).
- Use `json` for JSON bodies and `text` for non-JSON (don’t provide both).
- Prefer passing backend auth as `bearerToken` (avoid embedding secrets in headers or stored config).

## Local/Dev Backends (Optional)
- If you run the EnderAI backend locally, the MCP server must point at it (set `ENDERAI_BASE_URL=http://localhost:8000` in the MCP server environment).
- Keep this configuration out of committed files; set it in your deployment/IDE environment.

## Common Failure Modes (MCP Transport)
- A transient `404 Not Found` from the MCP endpoint often indicates a stale session after a redeploy/spin-down. Retry so the client re-initializes.
- If hand-rolling MCP HTTP requests (not recommended), you must use JSON-RPC and include `Accept: application/json, text/event-stream`.
  - Never invent `Mcp-Session-Id` values; initialize first and use the server-issued session id.
