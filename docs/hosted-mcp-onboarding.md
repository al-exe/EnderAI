# Hosted MCP Onboarding

## Purpose

This document describes the current EnderAI onboarding flow for hosted MCP clients.

The product now standardizes on:
- one per-user MCP token
- a hosted MCP endpoint
- the Taskforce V2 document workflow for V2-enabled users, with the legacy V1 `Topic / Case / ContextPack` workflow as the fallback when V2 is not enabled
- deterministic document matching with self-heal (V2) or automatic context hydration (V1) at the start of meaningful work

## Current Recommendation

For the current product flow:

1. create the user account
2. have the user set their password via reset link
3. open `Settings -> Connect Agent`
4. configure an MCP-capable AI client
5. create or rotate a credential
6. copy the generated setup snippet and the minimal agent instruction snippet
7. reconnect the client and verify with `enderai_session_info`

## Auth Model

EnderAI uses one user-scoped MCP token:

```text
local MCP client
  -> hosted EnderAI MCP
      Authorization: Bearer <user mcp token>
  -> EnderAI backend
```

The hosted MCP validates that token and reuses it for backend API calls on behalf of the same user.

There is no separate backend-token step in the recommended flow.

## Connect Agent Output

The Connect Agent page should generate:
- the hosted MCP URL
- the one MCP token the user needs
- client-agnostic setup for an MCP-capable AI client
- a short workflow snippet telling the agent to start meaningful work with `enderai_begin_document` for V2-enabled users, or `enderai_begin_case` as the V1 fallback

## Generic Hosted MCP Client

Example generic config:

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

Generic flow:
1. paste the generated JSON into the local MCP config
2. reconnect the client
3. enter the prompted MCP token
4. verify with `enderai_session_info`

## MCP Client TOML Example

Example MCP server config block:

```toml
[mcp_servers.enderai-api]
url = "https://YOUR-MCP-SERVICE.onrender.com/mcp"
bearer_token_env_var = "ENDERAI_MCP_TOKEN"
```

Example shell export:

```sh
export ENDERAI_MCP_TOKEN="REDACTED"
```

Client flow:
1. run the MCP token export in the shell or environment that launches your AI client
2. add the TOML block to the client's MCP config file
3. restart or reconnect the client
4. verify with `enderai_session_info`

## Agent Instruction Layer

For Taskforce V2-enabled users, the setup page should provide:

```text
If Taskforce V2 MCP tools are available:
- When creating or rotating an EnderAI MCP credential during setup, tell the user to start from a fresh terminal before reconnecting the AI client so the updated shell environment is loaded.
- Start meaningful user-initiated work with `enderai_begin_document`. It scores existing documents against the request, reuses + self-heals a strong match, or creates a fresh one.
- Use `enderai_update_document` as material progress develops (commands, files, links, decisions, changes, open questions, progress notes). Pass `details_sections` with stable `anchor_id`s to upsert specific Details sections.
- Back every Summary claim with `evidence_anchor_id` segments that point at a Details section. Do not edit `human_summary` unless the user explicitly asks.
- Use `enderai_finish_document` when the work completes or pauses; it writes Outcome and clears the active document pointer.
- Prefer Taskforce V2 document tools over the legacy V1 `enderai_begin_case` workflow and over raw `enderai_request` when both are available.
- If Taskforce V2 document tools are unavailable, do not fabricate tool calls; tell the user they are unavailable and fall back only to tools the user explicitly approves.
- Sessions awareness is a standing reflex: when the user asks what other agents are doing ("what is the other agent doing", "get/pull the sessions roster", "pull the shared context", "who else is running"), pull the live roster yourself immediately and without asking — do **not** answer this from `/discover` (that is topical retrieval of your own docs). The roster is `GET /api/v1/v2/taskforce/fleet` (Bearer the user MCP token), returning every session group and its agents with live `title`, `repo`, `branch`, `summary_markdown`, `status`, and `minutes_ago`; report `status: running` / low-`minutes_ago` agents first and label `idle`/History entries as stale. Drill into one with `GET /session-log?session_id=…` and `GET /session-activity?session_id=…`.
```

For V1-only users, the legacy reminder still applies:

```text
If EnderAI tools are available:
- Start meaningful user-initiated work with `enderai_begin_case`.
- Let EnderAI auto-hydrate relevant prior context before work begins.
- Read any `local_skill_files` returned by `skill_hydration` or `enderai_use_skill` before applying generated Skill guidance.
- Use `enderai_update_case` as material progress develops.
- Use `enderai_finish_case` when the work is complete.
- Prefer the guided case tools over raw `enderai_request` calls.
```

## Meaningful Work Lifecycle

For Taskforce V2-enabled users:

1. user initiates meaningful work
2. agent calls `enderai_begin_document` with `request_summary` plus optional title / goal / files / symbols / errors / contexts
3. the tool either reuses an existing strong match (returning `self_healed_fields` describing any structural drift that was repaired) or creates a fresh document; `match_reasons` and `candidate_summaries` explain the decision
4. active work begins
5. agent calls `enderai_update_document` as the work develops (commands, files, links, decisions, changes, open questions, progress notes, explicit Details sections)
6. agent keeps Summary claims backed by Details evidence anchors and leaves `human_summary` untouched unless asked
7. agent calls `enderai_finish_document` at completion or pause

For V1-only users, the legacy lifecycle still applies:

1. user initiates meaningful work
2. agent calls `enderai_begin_case`
3. EnderAI auto-hydrates context and generated Skill matches if relevant prior context exists
4. agent reads any returned local Skill markdown files for this task
5. active work begins
6. agent calls `enderai_update_case` as the work develops
7. agent calls `enderai_finish_case` at completion

`enderai_request` remains available as a lower-level escape hatch, but it is not the normal entrypoint for meaningful work.

## Verification

Recommended verification order:

1. `enderai_session_info`
2. `enderai_health_check`
3. `enderai_openapi` only for deeper diagnostics

## Risks

The main remaining operational risks are:
- token expiry and reconnect needs
- clients that ignore workflow guidance without tool-level guardrails
- poor snippet hygiene if setup logic drifts from the actual MCP workflow
