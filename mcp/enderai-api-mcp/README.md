# EnderAI API MCP Server

Local MCP server that proxies tool calls to an EnderAI backend (for example the Render deployment).

## Tools

- `enderai_request`: Make an HTTP request to the configured backend.
- `enderai_openapi`: Fetch `/api/v1/openapi.json`.
- `enderai_health_check`: Fetch `/api/v1/utils/health-check/`.

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

## Notes

- Requests are restricted to `path` values that start with `/` to prevent accidental full-URL overrides.
- Prefer `ENDERAI_BEARER_TOKEN` via MCP client env instead of passing tokens as tool arguments.
