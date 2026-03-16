# EnderAI API MCP

MCP server for the EnderAI backend.

It provides:

- a thin authenticated HTTP bridge to the backend
- guided Topic / Case workflow tools
- hosted Streamable HTTP deployment support

## Tools

The server exposes these tools:

- `enderai_begin_case`
- `enderai_update_case`
- `enderai_finish_case`
- `enderai_request`
- `enderai_openapi`
- `enderai_health_check`

## Guided Topic / Case Workflow

The guided workflow uses the canonical model directly.

### `enderai_begin_case`

- attaches to an existing Topic by `topic_id`, or creates a new Topic from `topic_title`
- optionally builds a ContextPack
- creates a new Case under that Topic
- remembers the active `case_id` and `topic_id` for the MCP session

### `enderai_update_case`

- patches the active Case with evidence, hypotheses, commands, changes, and summaries
- can append a progress Case event

### `enderai_finish_case`

- applies final updates
- requires a terminal Case status such as `done` or `failed`
- can append a closing Case event
- clears the active case context

If the caller skips a step or tries to switch cases mid-session, the tool returns a sequencing error instead of guessing.

## Request Auditing

`enderai_request` can append a best-effort Case event when a `case_id` is known.

Supported audit input:

- `audit.intent`: human-readable reason for the call
- `audit.case_id`: explicit Case id override for the current request/session

The recorded audit payload contains:

- request metadata
- response summary
- redacted secrets
- active case/topic context

## Environment

- `ENDERAI_BASE_URL` (default: `https://enderai-backend.onrender.com`)
- `ENDERAI_BEARER_TOKEN` (optional: `Authorization: Bearer ...`)
- `ENDERAI_TIMEOUT_MS` (default: `30000`)
- `MCP_BEARER_TOKEN` (optional, recommended for remote deploys: protects the MCP server itself)
- `MCP_PATH` (default: `/mcp`, streamable HTTP endpoint)

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

Health endpoint: `GET /health`
MCP endpoint: `GET|POST|DELETE /mcp` (or `MCP_PATH`)

## Test

```sh
cd mcp/enderai-api-mcp
npm test
```

Smoke test:

```sh
cd mcp/enderai-api-mcp
ENDERAI_BASE_URL=https://enderai-backend.onrender.com npm run smoke
```

HTTP smoke test:

```sh
cd mcp/enderai-api-mcp
npm run smoke:http
```

## Configure MCP Client

Example local MCP server config:

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

## Hosted MCP Token Flow

The current hosted MCP token flow remains supported:

- store the token in `~/.enderai_mcp_token`
- protect the file with `chmod 600`
- load it into the shell environment for local clients such as Codex CLI
- send it as `Authorization: Bearer ...` to the hosted MCP endpoint

This auth flow is intentionally unchanged by the Topic / Case cutover.
