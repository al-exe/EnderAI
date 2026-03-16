# Hosted MCP Onboarding

## Purpose

This document captures the current onboarding solution for getting an external engineer onto EnderAI when using a hosted MCP server.

It is intentionally focused on account creation, local agent setup, and getting the agent to use EnderAI consistently enough for a pilot.

## Current Recommendation

For the pilot, the onboarding flow is:

1. Create the user's account.
2. Send a password reset link so the user chooses their own password.
3. In the EnderAI web app, show a `Connect Agent` page.
4. The web app generates the local MCP config snippet the user needs for their client.
5. The user pastes that snippet into their local agent workflow.
6. The user's agent workflow includes a short EnderAI instruction snippet.
7. The hosted MCP server handles the rest.

This is the simplest acceptable flow for a pilot.

## Account Creation

The recommended pilot pattern is:

- create the user account as an admin
- do not rely on a human-chosen password being sent over email
- use a password reset link so the user sets their own password

This is good enough for a pilot, assuming:

- reset links expire
- the user resets the password promptly
- the backend email setup is configured correctly

## Hosted MCP Auth Model

The recommended hosted MCP setup now uses one user-scoped MCP token:

- client sends `Authorization: Bearer <mcp token>` to the hosted MCP
- hosted MCP validates that token with EnderAI
- hosted MCP reuses that same token for backend API calls on behalf of the user

Conceptually:

```text
local agent client
  -> hosted EnderAI MCP
      Authorization: Bearer <user-scoped mcp token>
  -> EnderAI backend
```

This lets one hosted MCP service act on behalf of different users without making the client also forward a second backend token.

Legacy compatibility:

- EnderAI still supports the older dual-token flow
- in that mode, the client sends a bearer token to reach the hosted MCP and separately forwards `X-EnderAI-Backend-Token`
- keep that only for backward compatibility while older clients migrate

## Clean Pilot UX: Web-Generated Config

Because external users will not have access to the EnderAI repo, the pilot should not depend on a repo-local helper script.

The current viable approach is:

```text
EnderAI web app
  -> Settings / Connect Agent
  -> choose local client
  -> generate config snippet
  -> user pastes it into local MCP config
```

The web page should provide:

- the hosted MCP URL
- the required auth headers
- copy-paste config for the user's chosen client
- brief instructions for where that config should go
- a way to rotate or regenerate credentials later

This is acceptable for the pilot even if it still requires one local copy-paste step.

For Codex CLI specifically, that local copy-paste step means adding the generated
MCP entry to `~/.codex/config.toml`.

The user should choose exactly one client path:

- generic MCP client: use the generated JSON config
- Codex CLI: use the generated `~/.codex/config.toml` snippet

They should not do both.

Important distinction:

- generic MCP clients can prompt for the MCP token directly, so they do not need env vars in this hosted flow
- Codex in this phase means terminal `codex` CLI, which is a good fit for env-var-based auth because it inherits the shell environment that launches it

## Legacy Dual-Token Mode

Older hosted setups used two different tokens:

- `ENDERAI_MCP_TOKEN`
  - authenticates the client to the hosted MCP
- `ENDERAI_BACKEND_TOKEN`
  - is forwarded separately to the backend as `X-EnderAI-Backend-Token`

Conceptually:

```text
local agent
  -> hosted MCP        uses ENDERAI_MCP_TOKEN
  -> EnderAI backend   legacy optional ENDERAI_BACKEND_TOKEN
```

This is no longer the recommended default.

Recommended hosted flow:

- use one user-scoped MCP token in the `Authorization` header
- let the hosted MCP reuse that token for backend requests

## Local MCP Wiring

For a generic hosted-MCP client, the local config should point at the hosted MCP URL and provide both headers.

The web app can generate a copy-paste config like this:

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

This is the generic MCP-client path.

With a hosted MCP URL, the user does not start the EnderAI MCP server locally. The hosted service is already running. The user only pastes the config into their local MCP client and enters the prompted tokens.

The generic hosted-client flow is:

1. In the EnderAI web app, generate the generic MCP config and tokens.
2. Paste the generated JSON into the local MCP client config.
3. Start or reconnect the local MCP client.
4. Enter the prompted tokens when the client asks for them.
5. Verify the agent can use `enderai-api`.

Legacy dual-token example:

```json
{
  "inputs": [
    {
      "type": "promptString",
      "id": "enderai_mcp_token",
      "description": "EnderAI MCP token",
      "password": true
    },
    {
      "type": "promptString",
      "id": "enderai_backend_token",
      "description": "EnderAI backend token",
      "password": true
    }
  ],
  "servers": {
    "enderai-api": {
      "type": "http",
      "url": "https://YOUR-MCP-SERVICE.onrender.com/mcp",
      "headers": {
        "Authorization": "Bearer ${input:enderai_mcp_token}",
        "X-EnderAI-Backend-Token": "${input:enderai_backend_token}"
      }
    }
  }
}
```

For the pilot, the web app can simply render:

- the config block to paste
- the token values to enter or export locally, depending on the client
- short client-specific instructions

This keeps the local step simple without requiring EnderAI to ship a local installer yet.

### Client-Specific Note: Codex CLI

This section refers to terminal `codex` CLI.

Codex CLI does not use the generic JSON `inputs` block above or a generic `mcp.json` snippet by itself.

It is a separate setup path, not an extra step after the generic JSON flow.

For Codex CLI users, local MCP setup does include `~/.codex/config.toml` or the equivalent `codex mcp add` registration flow.

So yes, this is part of onboarding for Codex users.

At minimum, the generated setup should cover:

- registering the hosted MCP URL with Codex
- wiring `ENDERAI_MCP_TOKEN` as the bearer token env var for the hosted MCP
- optionally documenting `ENDERAI_BACKEND_TOKEN` only for legacy dual-token compatibility

In other words, the generic onboarding should say "install local MCP config", and the Codex-specific onboarding should concretely emit the `config.toml` instructions needed for Codex.

The onboarding flow for Codex CLI users should be explicit:

1. In the EnderAI web app, generate the hosted MCP credentials and the Codex-specific setup snippet.
2. Have the user export `ENDERAI_MCP_TOKEN` in the shell that will launch `codex`.
3. Have the user add the generated MCP entry to `~/.codex/config.toml`.
4. Launch a new terminal `codex` session so the new MCP server is loaded with those env vars.
5. In that new session, verify the MCP connection by asking the agent to confirm the server is available, list its tools, and run `enderai_health_check` plus `enderai_openapi`.

### Codex CLI (Terminal) Setup From Scratch

If the user wants terminal `codex` CLI to use EnderAI, this is the path to follow.

Do not use the generic JSON `inputs` flow for this case.

From a clean machine-local setup, the steps are:

1. Optional reset: remove any old local registration with `codex mcp remove enderai-api` and, if present from an older setup, `codex mcp remove enderai-mcp`.
2. Optional reset: in any already-open terminal, run `unset ENDERAI_BACKEND_TOKEN ENDERAI_MCP_TOKEN`.
3. In the EnderAI web app, open `Settings -> Connect Agent`.
4. Select the `Codex CLI` tab.
5. Create a new agent credential or rotate an existing one.
6. Copy the generated shell export block and run it in the terminal session that will launch Codex.
7. Copy the generated TOML block into `~/.codex/config.toml`. If an older EnderAI block already exists there, replace it instead of merging with it.
8. Launch `codex` from that same terminal session. If you later open a second shell, re-export the vars there before launching `codex` again.
9. Verify the setup by asking the new terminal `codex` session to confirm `enderai-api`, list its tools, and run `enderai_health_check` plus `enderai_openapi`.
10. If verification fails, inspect the active registration with `codex mcp list` and `codex mcp get enderai-api --json`. The recommended registration should point at the hosted MCP URL and use `bearer_token_env_var = "ENDERAI_MCP_TOKEN"`.

This is the minimum hosted-MCP setup for Codex. The user does not start the EnderAI MCP server locally in this flow.

Example shell exports:

```sh
export ENDERAI_MCP_TOKEN="..."
```

Example Codex config block to add to `~/.codex/config.toml`:

```toml
[mcp_servers.enderai-api]
url = "https://YOUR-MCP-SERVICE.onrender.com/mcp"
bearer_token_env_var = "ENDERAI_MCP_TOKEN"
```

Legacy dual-token Codex block:

```toml
[mcp_servers.enderai-api]
url = "https://YOUR-MCP-SERVICE.onrender.com/mcp"
env_http_headers = { "X-EnderAI-Backend-Token" = "ENDERAI_BACKEND_TOKEN" }
bearer_token_env_var = "ENDERAI_MCP_TOKEN"
```

If the user prefers starting from the Codex CLI, they can register the hosted MCP URL first:

```sh
codex mcp add enderai-api \
  --url https://YOUR-MCP-SERVICE.onrender.com/mcp \
  --bearer-token-env-var ENDERAI_MCP_TOKEN
```

After that, the onboarding still needs to tell them whether they are using the recommended single-token flow or the legacy dual-token flow.

The important requirement is that onboarding must include the local Codex registration step and the `config.toml` edit, not just token issuance.

Suggested verification prompt for the next Codex session:

```text
Use the MCP server `enderai-api` in this session. First confirm the server is available. Then list every tool exposed by that server. After that, call `enderai_health_check` and `enderai_openapi` and summarize the results. Use the MCP tools directly rather than reading the repo unless the MCP call fails.
```

## Native Codex OAuth Roadmap

The single-token hosted flow removes the extra backend header, but it still relies on the user supplying a bearer token to Codex.

The next product step for first-class Codex support is:

- add OAuth authorization-server endpoints to EnderAI
- advertise protected-resource metadata from the hosted MCP
- let Codex use `codex mcp login enderai-api`
- have the hosted MCP derive the EnderAI user identity from that OAuth access token instead of requiring any manual secret wiring

That is the long-term Codex-native path. The single-token hosted flow above is the intermediate simplification that makes the current setup materially less awkward.

## Optional Future UX: Published `enderai connect`

The `enderai connect` idea still makes sense, but only if it is shipped as a real distributed product artifact:

- installable CLI package
- downloadable binary
- packaged helper outside the private repo

At that point it could:

- authenticate the user
- store tokens securely
- install or update local MCP config
- remove the need for manual copy-paste

What it should store:

- tokens, not the user's password
- preferably in the OS keychain
- or, for a pilot fallback, in a local file with tight permissions

The key point is that `enderai connect` is a future packaged product helper, not a repo-local script.

## Why a Local Helper Still Makes Sense

EnderAI is a web application, but the user's agent workflow runs locally.

The web app can:

- manage users
- issue or revoke credentials
- show installation instructions

The web app cannot directly:

- edit the user's local MCP config
- set env vars inside the user's terminal session
- install local agent wiring on the user's machine

That is why a web-generated config flow is viable now and a packaged `enderai connect` helper is compatible later. The web app remains the source of truth; any CLI only handles machine-local installation.

## Agent Instruction Layer

The MCP existing at all is not enough. The agent still needs some instruction about when to use EnderAI.

For the pilot, a short `AGENTS.md` snippet is acceptable.

The instruction should be minimal, for example:

- start meaningful work by creating or beginning an EnderAI case
- update EnderAI after material findings or code changes
- finish by recording outcome and next steps

This should stay short. The repo-level instruction is a pilot compatibility layer, not the long-term source of truth.

## Better Long-Term Workflow

The more elegant long-term solution is to encode the workflow in the MCP tools themselves.

Instead of a generic HTTP proxy being the primary interface, expose a small high-level tool set such as:

- `begin_case`
- `update_case`
- `finish_case`

These tools should:

- describe when they should be called
- return the IDs needed for the next step
- require prior state where appropriate
- fail clearly when used out of order

This is stronger than relying on a large prose instruction block.

## Role of Tool Descriptions

Tool descriptions matter because models read:

- tool names
- tool descriptions
- parameter schemas
- parameter descriptions

So the workflow guidance should live inside the tool contract as much as possible.

However, descriptions guide behavior. They do not fully guarantee behavior.

Reliable behavior comes from a combination of:

- self-descriptive tool names
- concise tool descriptions
- required fields such as `case_id`
- backend validation when steps are skipped or misordered

## Pilot Summary

The current landed solution for pilot onboarding is:

- admin creates account
- user sets password via reset link
- EnderAI web app shows a `Connect Agent` page
- user copies generated MCP config and token setup instructions into their local workflow
- agent gets a minimal EnderAI instruction snippet
- hosted MCP and backend do the rest

This is acceptable for a pilot.

## Long-Term Direction

The cleaner long-term product direction is:

- a web `Connect Agent` flow in EnderAI
- web-generated client-specific config as the default bootstrap
- optionally a published `enderai connect` helper that installs the local setup automatically
- dedicated revocable agent credentials instead of reusing normal user login tokens
- local installation generated from the web app
- higher-level EnderAI MCP tools that encode the memory workflow
- minimal or no per-repo `AGENTS.md` customization beyond a short reminder

## Open Risks

The main risks still outside the onboarding flow are:

- backend tokens expire and may need refresh or reconnection
- a generic MCP tool surface relies too much on prompt discipline
- multi-user isolation and permission boundaries must be strong enough before broad paid rollout

These do not block a small trusted pilot, but they should be addressed before a larger hosted multi-user launch.

## Implementation Status: 2026-03-15

The interim hosted-MCP simplification described above is now implemented.

Current product state:

- recommended hosted flow: one user-scoped MCP token
- recommended generic client path: prompted JSON `inputs`
- supported Codex path in this phase: terminal `codex` CLI
- legacy compatibility path: dual-token flow with `X-EnderAI-Backend-Token`

What changed in the implementation:

- backend auth now accepts `agent_mcp` tokens anywhere normal bearer-auth user resolution runs
- hosted MCP validates the incoming per-user MCP bearer token and reuses that same token for backend API calls
- if a client still sends `X-EnderAI-Backend-Token`, that legacy header still overrides the session backend token
- the EnderAI `Connect Agent` UI now defaults to the one-token hosted flow and keeps the dual-token setup behind a legacy toggle

What is intentionally not solved in this phase:

- native Codex OAuth
- a first-class VS Code Codex sidebar auth flow

Validation completed during implementation:

- backend credential/auth route tests passed with a disposable local Postgres instance
- MCP package tests passed, including auth precedence coverage
- frontend production build passed
- targeted `Connect Agent` Playwright coverage passed for the one-token default flow and the legacy fallback
