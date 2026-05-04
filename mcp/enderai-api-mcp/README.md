# EnderAI API MCP Server

Hosted or local MCP server that proxies tool calls to an EnderAI backend.

## Tools

- `enderai_begin_case`: first step for meaningful work; starts a guided Topic/Case workflow, auto-hydrates relevant prior context by default, and syncs matching generated Skills to local markdown when available
- `enderai_use_skill`: explicitly match generated EnderAI Skills for the active case or supplied request signals, then sync the matched Skill markdown locally
- `enderai_update_case`: record material progress during active work
- `enderai_finish_case`: close the active case with a terminal status
- `enderai_session_info`: return session policy, auth model, active case/topic ids, and user summary when available
- `enderai_request`: lower-level HTTP escape hatch for backend endpoints
- `enderai_openapi`: fetch `/api/v1/openapi.json`
- `enderai_health_check`: fetch `/api/v1/utils/health-check/`

## Guided Case Workflow

The intended lifecycle for meaningful work is:

1. call `enderai_begin_case`
2. let EnderAI auto-hydrate relevant prior context and generated Skill matches
3. read any returned `skill_hydration.local_skill_sync.local_skill_files`
4. perform the work
5. call `enderai_update_case` as findings or changes develop
6. call `enderai_finish_case` at the end

If the caller skips a step or tries to switch cases mid-session, the MCP returns a clear sequencing error instead of guessing.

Generated Skill files are advisory workflow guidance. They are written under `ENDERAI_SKILLS_DIR` when set, otherwise under `enderai-skills` relative to the MCP process working directory. The caller should read only the returned file paths for the current task unless the user asks for broader Skill exploration.

## Lower-Level Requests

`enderai_request` is available for endpoints that are not yet covered by guided tools.

Guidance:
- prefer guided case tools for meaningful work
- read-only calls can be used without an active case
- write-like calls require an active case unless `unsafe_write_reason` is supplied explicitly

## Session Info

`enderai_session_info` returns:
- `policy_version`
- `workflow_model`
- `auth_model`
- active case/topic ids
- authenticated user summary when available
- local Skill sync directory and discovery reminder
- readiness to start meaningful work

## Backward-Compatibility Path Rewrites

`enderai_request` still rewrites a few older API paths when needed:

- `/api/v1/me` -> `/api/v1/users/me`
- `/api/v1/runs/*` -> `/api/v1/executions/*`
- `/api/v1/tasks/*` -> `/api/v1/threads/*`
- `/api/v1/library/*` -> `/api/v1/artifacts/*`

## Environment

- `ENDERAI_BASE_URL` (default: `https://enderai-backend.onrender.com`)
- `ENDERAI_BEARER_TOKEN` (optional operator-side fallback bearer token)
- `ENDERAI_SKILLS_DIR` (optional local directory for generated Skill markdown; default: `./enderai-skills`)
- `ENDERAI_TIMEOUT_MS` (default: `30000`)
- `MCP_BEARER_TOKEN` (optional operator-side protection for the MCP service itself)
- `MCP_PATH` (default: `/mcp`)

## Run Locally

```sh
cd mcp/enderai-api-mcp
npm install
npm run build
ENDERAI_BASE_URL=https://enderai-backend.onrender.com npm start
```

## Remote (Streamable HTTP)

```sh
cd mcp/enderai-api-mcp
npm install
npm run build
PORT=8080 MCP_BEARER_TOKEN=dev-token npm run start:http
```

Health endpoint:
- `GET /health`

MCP endpoint:
- `GET|POST|DELETE /mcp`

## Test

```sh
cd mcp/enderai-api-mcp
npm test
```

## Generic Hosted MCP Client

Example config:

```json
{
  "inputs": [
    {
      "type": "promptString",
      "id": "enderai_mcp_token",
      "description": "EnderAI MCP token",
      "password": true
    }
  ],
  "servers": {
    "enderai-api": {
      "type": "http",
      "url": "https://YOUR-MCP-SERVICE.onrender.com/mcp",
      "headers": {
        "Authorization": "Bearer ${input:enderai_mcp_token}"
      }
    }
  }
}
```

## MCP Client TOML Example

Example MCP server config block:

```toml
[mcp_servers.enderai-api]
url = "https://YOUR-MCP-SERVICE.onrender.com/mcp"
bearer_token_env_var = "ENDERAI_MCP_TOKEN"
```

Example shell setup:

```sh
export ENDERAI_MCP_TOKEN="REDACTED"
```

## Minimal Workflow Reminder

```text
If EnderAI tools are available:
- Start meaningful user-initiated work with `enderai_begin_case`.
- Let EnderAI auto-hydrate relevant prior context before work begins.
- Read any `local_skill_files` returned by `skill_hydration` or `enderai_use_skill` before applying generated Skill guidance.
- Use `enderai_update_case` as material progress develops.
- Use `enderai_finish_case` when the work is complete.
- Prefer the guided case tools over raw `enderai_request` calls.
```
