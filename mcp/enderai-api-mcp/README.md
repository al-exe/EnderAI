# EnderAI API MCP Server

Local MCP server that proxies tool calls to an EnderAI backend (for example the Render deployment).

## Tools

- `enderai_begin_case`: Start a guided Topic/Case workflow, create a new case, and hydrate it with a compact `ContextPack`.
- `enderai_update_case`: Patch the active case document with evidence, commands, hypotheses, changes, and progress notes.
- `enderai_finish_case`: Apply final case updates, close the active case with a terminal status, and clear the active case context.
- `enderai_request`: Make a lower-level HTTP request to the configured backend when you need an endpoint the guided tools do not cover yet.
- `enderai_openapi`: Fetch `/api/v1/openapi.json`.
- `enderai_health_check`: Fetch `/api/v1/utils/health-check/`.

### Guided Case Workflow

The new guided tools are meant to mirror the Topic / Case docs:

1. `enderai_begin_case`
   - starts an execution-backed case
   - seeds the canonical case document
   - builds and attaches a `ContextPack` by default
   - remembers the returned `case_id` and `topic_id` for this MCP session
2. `enderai_update_case`
   - patches the active case document
   - optionally appends a progress event
   - refuses to close a case so the workflow stays explicit
3. `enderai_finish_case`
   - applies final case updates
   - requires a terminal status such as `done` or `failed`
   - optionally appends a closing event
   - clears the active case context so the next case must start with `enderai_begin_case`

If the caller skips a step or tries to switch cases mid-session, the tool returns a clear sequencing error instead of guessing.

### Backward-Compatibility Path Rewrites

`enderai_request` will transparently rewrite a few older (pre-migration) API paths:

- `/api/v1/me` -> `/api/v1/users/me`
- `/api/v1/runs/*` -> `/api/v1/executions/*`
- `/api/v1/tasks/*` -> `/api/v1/threads/*` (and `/api/v1/tasks/{id}/runs/*` -> `/api/v1/threads/{id}/executions/*`)
- `/api/v1/library/*` -> `/api/v1/artifacts/*`

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

This is the recommended generic hosted-MCP flow. The hosted EnderAI MCP service is already running at that URL, so the user does not start the MCP server locally. They only paste this config into their MCP client and provide the prompted token when the client connects.

Use this generic hosted-client flow or the Codex CLI flow below, not both.

Important distinction:

- generic MCP clients can prompt for the MCP token directly, so they do not need env vars in this hosted flow
- Codex in this phase means terminal `codex` CLI, which inherits the shell environment that launches it

### Per-User Backend Access (Hosted MCP)

Recommended hosted flow:

- send the user-scoped EnderAI MCP token in `Authorization: Bearer ...`
- the hosted MCP validates that token and reuses it for backend API calls on behalf of that user

Legacy compatibility flow:

- if you still need a separate backend token, the hosted MCP also accepts `X-EnderAI-Backend-Token: <enderai_backend_access_token>`

If a client still needs the older dual-token setup, env interpolation for headers also works; for example:

```json
{
  "servers": {
    "enderai-api": {
      "type": "http",
      "url": "https://YOUR-MCP-SERVICE.onrender.com/mcp",
      "headers": {
        "Authorization": "Bearer ${env:ENDERAI_MCP_TOKEN}",
        "X-EnderAI-Backend-Token": "${env:ENDERAI_BACKEND_TOKEN}"
      }
    }
  }
}
```

## Deploy (Render MVP)

This section is for the EnderAI operator who is deploying the hosted MCP service, not for an end user connecting to an already-hosted MCP URL.

Create a **new Render Web Service** pointing at this repo (`al-exe/EnderAI`), with root directory `mcp/enderai-api-mcp`:

- Build command: `npm ci && npm run build`
- Start command: `npm run start:http`
- Env vars:
  - `ENDERAI_BASE_URL=https://enderai-backend.onrender.com`
  - `ENDERAI_TIMEOUT_MS=30000`
  - `MCP_BEARER_TOKEN=<random-long-secret>`

## Use From Codex CLI (Local MCP)

If you are using terminal `codex`, you can register this server with the **Codex CLI** (it stores MCP servers in `~/.codex/config.toml`):

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
- Start a new Codex session after registration. The current session will not pick up MCP servers that were added after it started.
- A simple verification prompt for the next Codex session is:

```text
Use the MCP server `enderai-api` in this session. First confirm the server is available. Then list every tool exposed by that server. After that, call `enderai_health_check` and `enderai_openapi` and summarize the results. Use the MCP tools directly rather than reading the repo unless the MCP call fails.
```

### Codex CLI (Hosted MCP URL)

If you are using terminal `codex` with the hosted Streamable HTTP MCP server (for example `https://enderai-mcp.onrender.com/mcp`), register it by URL.

This is a different client-specific setup from the JSON `inputs` example above. Codex does not use that JSON block; it uses `~/.codex/config.toml` plus local environment variables.

Use this Codex flow instead of the generic JSON `inputs` flow above.

Clean setup from scratch for terminal `codex`:

1. Optional reset: remove any old local registration with `codex mcp remove enderai-api`.
2. Optional reset: in any already-open terminal, run `unset ENDERAI_BACKEND_TOKEN ENDERAI_MCP_TOKEN`.
3. In the EnderAI web app, open `Settings -> Connect Agent`.
4. Select the `Codex CLI` tab.
5. Create or rotate an agent credential.
6. Run the generated `export ENDERAI_MCP_TOKEN=...` line in the terminal that will launch `codex`.
7. Register the hosted MCP URL with Codex CLI using the env-var name, not the token value.
8. Launch `codex` from that same terminal session.
9. Verify the new session can see `enderai-api` and can call `enderai_health_check` plus `enderai_openapi`.

This hosted-MCP path does not require the user to start the EnderAI MCP server locally.

```sh
export ENDERAI_MCP_TOKEN='YOUR_ENDERAI_MCP_TOKEN'

codex mcp add enderai-api \
  --url https://enderai-mcp.onrender.com/mcp \
  --bearer-token-env-var ENDERAI_MCP_TOKEN

codex mcp list
```

Important:
- `--bearer-token-env-var` expects the environment variable name, for example `ENDERAI_MCP_TOKEN`.
- Do not paste the raw JWT directly after `--bearer-token-env-var` or Codex will treat it as a missing flag value and the MCP handshake will fail.
- Start a fresh Codex session after registration; already-running sessions will not pick up newly added MCP servers.

Per-user backend auth (recommended for shared hosted MCP):
- the recommended hosted setup no longer needs `X-EnderAI-Backend-Token`
- use a user-scoped `ENDERAI_MCP_TOKEN` and let the hosted MCP reuse it for backend API calls

Non-interactive tip:
- terminal `codex` does inherit env vars from the shell that launches it
- if you want to avoid keeping secrets exported in a long-lived shell, set them only at invocation time
- one pattern is to store the token in a local file with tight perms and read it when launching Codex:
  - `~/.enderai_mcp_token` (chmod `600`)
  - Example: `ENDERAI_MCP_TOKEN="$(tr -d '\\r\\n' < ~/.enderai_mcp_token)" codex exec ...`

Persistent shell setup for local dev:
- if you want new terminals to pick up the token automatically, keep the secret in `~/.enderai_mcp_token` and load it from `~/.bashrc`

```sh
printf '%s\n' 'YOUR_ENDERAI_MCP_TOKEN' > ~/.enderai_mcp_token
chmod 600 ~/.enderai_mcp_token
echo 'export ENDERAI_MCP_TOKEN="$(tr -d "\\r\\n" < ~/.enderai_mcp_token)"' >> ~/.bashrc
source ~/.bashrc
```

Pitfall of the simpler `~/.bashrc` version:
- directly writing `export ENDERAI_MCP_TOKEN="..."` into `~/.bashrc` also works, but the secret then lives in a config file that is more likely to be copied, synced, diffed, screenshared, or shared for debugging
- a dedicated token file is not stronger against a full same-user compromise, but it is better at reducing accidental disclosure during normal development workflows

Optional MCP endpoint protection:
- user-scoped MCP tokens are already bearer tokens, so the recommended Codex block is:
  - `bearer_token_env_var = "ENDERAI_MCP_TOKEN"`
  - And export: `ENDERAI_MCP_TOKEN="..."`

Legacy dual-token Codex block:

```toml
[mcp_servers.enderai-api]
url = "https://enderai-mcp.onrender.com/mcp"
env_http_headers = { "X-EnderAI-Backend-Token" = "ENDERAI_BACKEND_TOKEN" }
bearer_token_env_var = "ENDERAI_MCP_TOKEN"
```

Debug tip:
- `POST /api/v1/login/test-token` should return:
  - `200` when auth is working
  - `401 Not authenticated` when the backend did not receive a token
  - `403 Could not validate credentials` when the token is invalid/expired

Security note:
- `codex mcp get` / `codex mcp list --json` may print resolved header values; avoid running those commands when `ENDERAI_BACKEND_TOKEN` is set.
- After adding the hosted MCP config, launch a new terminal `codex` session before asking the agent to use `enderai-api`.

### Native Codex OAuth Roadmap

The single-token hosted flow removes the extra backend header, but a user still has to supply `ENDERAI_MCP_TOKEN` to Codex today.

The long-term first-class Codex path is:
- expose OAuth authorization-server endpoints from EnderAI
- advertise OAuth protected-resource metadata from the hosted MCP
- let the user run `codex mcp login enderai-api`
- have the hosted MCP derive backend identity from that OAuth access token without any extra header wiring

That OAuth path is still future work. The single-token hosted flow above is the current simplification step.

## Notes

- Requests are restricted to `path` values that start with `/` to prevent accidental full-URL overrides.
- Prefer `ENDERAI_BEARER_TOKEN` via MCP client env instead of passing tokens as tool arguments.

## Implementation Status: 2026-03-15

The interim hosted-MCP rollout described in this README is now implemented.

Current defaults:

- one user-scoped MCP token for the recommended hosted flow
- prompted JSON `inputs` for generic hosted MCP clients
- terminal `codex` CLI for Codex users in this phase
- legacy dual-token support kept for backward compatibility

Current behavior:

- validated per-user MCP bearer tokens are reused for downstream backend API calls
- `X-EnderAI-Backend-Token` still works as a legacy override when a client intentionally sends it
- EnderAI backend auth now accepts `agent_mcp` tokens for normal authenticated API access

Explicitly deferred:

- native Codex OAuth / `codex mcp login`
- a polished VS Code Codex sidebar auth path

Implementation verification that was completed:

- backend agent-credential route tests
- MCP vitest coverage, including backend-token precedence behavior
- frontend build
- targeted `Connect Agent` Playwright coverage for the default and legacy flows
