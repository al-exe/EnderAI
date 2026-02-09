# EnderAI API MCP Server

Local MCP server that proxies tool calls to an EnderAI backend (for example the Render deployment).

## Tools

- `enderai_request`: Make an HTTP request to the configured backend.
- `enderai_openapi`: Fetch `/api/v1/openapi.json`.
- `enderai_health_check`: Fetch `/api/v1/utils/health-check/`.

## Execution Event Log (Optional)

This MCP server can help keep an **event log per Execution** (EnderAI `event` rows):

- If you call `POST /api/v1/executions/start` via `enderai_request`, the server will remember the returned `execution.id` (per MCP session).
- For subsequent `enderai_request` calls, you can pass an `audit` object:
  - `audit.intent`: short human-readable reason for the call (becomes the Event message)
  - `audit.run_id`: optional override for the current Execution id (also updates session context)
- When an Execution id is known, the server will append an `event` of type `mcp` containing:
  - the request args (method/path/query/headers/body)
  - the response summary (status/ok/data)
  - secrets redacted (`Authorization`, tokens, passwords, etc.)
  - payloads capped to keep DB/UI healthy (large JSON like OpenAPI is truncated)

Additionally, when you `POST /api/v1/artifacts/` and an Execution id is known, the server will auto-link
the created Artifact to the current Execution (`relation=created`).

Example (pseudo-code):

```json
{
  "method": "GET",
  "path": "/api/v1/items/",
  "query": { "skip": 0, "limit": 25 },
  "audit": { "intent": "List items to find the oldest two" }
}
```

## Environment

- `ENDERAI_BASE_URL` (default: `https://enderai-backend.onrender.com`)
- `ENDERAI_BEARER_TOKEN` (optional: `Authorization: Bearer ...`)
- `ENDERAI_TIMEOUT_MS` (default: `30000`)
- `MCP_BEARER_TOKEN` (optional, recommended for remote deploys: protects the MCP server itself)
- `MCP_PATH` (default: `/mcp`, streamable HTTP endpoint)

## Run Locally

```sh
# From the repo root:
cd mcp/enderai-api-mcp
npm install
npm run build
ENDERAI_BASE_URL=https://enderai-backend.onrender.com npm start
```

## Remote (Streamable HTTP)

This repo includes a Streamable HTTP MCP server entrypoint you can deploy so others can connect by URL:

```sh
# From the repo root:
cd mcp/enderai-api-mcp
npm install
npm run build
PORT=8080 MCP_BEARER_TOKEN=dev-token npm run start:http
```

Health endpoint: `GET /health`  
MCP endpoint: `GET|POST|DELETE /mcp` (or `MCP_PATH`)

## Test

Unit tests (no network):

```sh
# From the repo root:
cd mcp/enderai-api-mcp
npm test
```

Smoke test (spawns the MCP server and calls `enderai_health_check` + `enderai_openapi` against your configured backend):

```sh
# From the repo root:
cd mcp/enderai-api-mcp
ENDERAI_BASE_URL=https://enderai-backend.onrender.com npm run smoke
```

Smoke test (local Streamable HTTP server + Streamable HTTP client transport):

```sh
# From the repo root:
cd mcp/enderai-api-mcp
npm run smoke:http
```

## Configure MCP Client (example)

Example MCP server config (adapt to your client):

```json
{
  "mcpServers": {
    "enderai-api": {
      "command": "node",
      "args": ["mcp/enderai-api-mcp/dist/index.js"],
      "env": {
        "ENDERAI_BASE_URL": "https://enderai-backend.onrender.com",
        "ENDERAI_BEARER_TOKEN": "REDACTED"
      }
    }
  }
}
```

## Configure VS Code (Remote URL)

If your friends are using VS Code's `mcp.json`, they can point to your deployed URL:

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

### Per-User Backend Access (Hosted MCP)

When deploying the MCP server as a shared hosted service, MCP auth (to the MCP server) is **not** the same as backend auth (to the EnderAI API).

To access a specific user's account resources through the hosted MCP, send the user's backend access token on each request using:
- `X-EnderAI-Backend-Token: <enderai_backend_access_token>`

Some clients support env interpolation for headers; for example:

```json
{
  "servers": {
    "enderai-api": {
      "type": "http",
      "url": "https://YOUR-MCP-SERVICE.onrender.com/mcp",
      "headers": {
        "Authorization": "Bearer ${input:enderai_mcp_token}",
        "X-EnderAI-Backend-Token": "${env:ENDERAI_BACKEND_TOKEN}"
      }
    }
  }
}
```

## Deploy (Render MVP)

Create a **new Render Web Service** pointing at this repo (`al-exe/EnderAI`), with root directory `mcp/enderai-api-mcp`:

- Build command: `npm ci && npm run build`
- Start command: `npm run start:http`
- Env vars:
  - `ENDERAI_BASE_URL=https://enderai-backend.onrender.com`
  - `ENDERAI_TIMEOUT_MS=30000`
  - `MCP_BEARER_TOKEN=<random-long-secret>`

## Use From VS Code (Codex CLI)

If you are using VS Code and running Codex via the integrated terminal, you can register this server with the **Codex CLI** (it stores MCP servers in `~/.codex/config.toml`):

```sh
codex mcp add enderai-api \
  --env ENDERAI_BASE_URL=https://enderai-backend.onrender.com \
  --env ENDERAI_TIMEOUT_MS=30000 \
  -- node mcp/enderai-api-mcp/dist/index.js

codex mcp list
codex mcp get enderai-api --json
```

Notes:
- This avoids storing auth tokens in config. If you need auth, call the login endpoint and pass the token per-call via the `bearerToken` argument to `enderai_request`, or set `ENDERAI_BEARER_TOKEN` via your environment.

### Codex CLI (Hosted MCP URL)

If you are using the hosted Streamable HTTP MCP server (for example `https://enderai-mcp.onrender.com/mcp`), register it by URL:

```sh
codex mcp add enderai-mcp --url https://enderai-mcp.onrender.com/mcp
codex mcp list
```

Per-user backend auth (recommended for shared hosted MCP):
- Configure Codex to send the backend access token on each MCP request:
  - In `~/.codex/config.toml`:
    - `env_http_headers = { "X-EnderAI-Backend-Token" = "ENDERAI_BACKEND_TOKEN" }`
  - Then export: `ENDERAI_BACKEND_TOKEN="<access_token from /api/v1/login/access-token>"`

Non-interactive tip (Codex doesn’t see your interactive shell env):
- If a non-interactive agent run can’t see `ENDERAI_BACKEND_TOKEN`, set it at invocation time.
- One pattern is to store the token in a local file with tight perms and read it when launching Codex:
  - `~/.enderai_backend_token` (chmod `600`)
  - Example: `ENDERAI_BACKEND_TOKEN="$(tr -d '\\r\\n' < ~/.enderai_backend_token)" codex exec ...`

Optional MCP endpoint protection:
- If the hosted MCP is protected with a static bearer token (recommended), set:
  - `bearer_token_env_var = "ENDERAI_MCP_TOKEN"`
  - And export: `ENDERAI_MCP_TOKEN="..."`

Debug tip:
- `POST /api/v1/login/test-token` should return:
  - `200` when auth is working
  - `401 Not authenticated` when the backend did not receive a token
  - `403 Could not validate credentials` when the token is invalid/expired

Security note:
- `codex mcp get` / `codex mcp list --json` may print resolved header values; avoid running those commands when `ENDERAI_BACKEND_TOKEN` is set.

## Notes

- Requests are restricted to `path` values that start with `/` to prevent accidental full-URL overrides.
- Prefer `ENDERAI_BEARER_TOKEN` via MCP client env instead of passing tokens as tool arguments.
