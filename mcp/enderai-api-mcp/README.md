# EnderAI API MCP Server

Hosted or local MCP server that proxies tool calls to an EnderAI backend.

## Tools

Taskforce V2 document workflow (preferred for V2-enabled users):

- `enderai_begin_document`: first step for meaningful work; lists candidate Taskforce V2 documents, scores them against the request using a deterministic congruence engine, and either reuses + self-heals the top match or creates a fresh document. Remembers the active document for this MCP session.
- `enderai_update_document`: append material progress to the active document (commands, files, links, decisions, changes, open questions, summary points, explicit Details sections). Leaves `human_summary` untouched unless explicitly set.
- `enderai_finish_document`: finalize the active document with an Outcome section (status, outcome, validation, follow-ups) and clear the active-document pointer.

Legacy V1 Topic/Case workflow (fallback when V2 tools are not enabled for the user):

- `enderai_begin_case`: starts a guided Topic/Case workflow, auto-hydrates relevant prior context by default, and syncs matching generated Skills to local markdown when available
- `enderai_use_skill`: explicitly match generated EnderAI Skills for the active case or supplied request signals, then sync the matched Skill markdown locally
- `enderai_update_case`: record material progress during active work
- `enderai_finish_case`: close the active case with a terminal status

Cross-cutting:

- `enderai_session_info`: return session policy, auth model, active case/topic/document ids, and user summary when available
- `enderai_request`: lower-level HTTP escape hatch for backend endpoints
- `enderai_openapi`: fetch `/api/v1/openapi.json`
- `enderai_health_check`: fetch `/api/v1/utils/health-check/`

## Taskforce V2 Document Workflow

For V2-enabled users, the intended lifecycle for meaningful work is:

1. call `enderai_begin_document` with `request_summary` (plus optional `title`, `goal`, `files`, `symbols`, `errors`, `contexts`, `collaborators`)
2. the tool either reuses an existing strong match (with `self_healed_fields` describing any structural drift that was fixed before handing back the document) or creates a fresh one; the `match_reasons` array explains the decision
3. perform the work
4. call `enderai_update_document` as material progress develops, passing `progress_note`, `commands`, `files`, `links`, `decisions`, `changes`, `open_questions`, `summary_points`, or explicit `details_sections` with stable `anchor_id`s
5. keep Summary claims backed by Details evidence anchors; do not edit `human_summary` unless the user explicitly asks
6. call `enderai_finish_document` when the work completes or pauses

Scoring is auditable: every match returns per-signal contributions and reasons in `candidate_summaries`. Self-heal is conservative: it fills gaps (missing description / summary / anchors / collaborators / a Current Work Details section seeded from whichever request signals weren't already in the document) but never rewrites human content.

## Guided Case Workflow (Legacy V1)

For users who are not yet on Taskforce V2, the intended V1 lifecycle is:

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
- active Taskforce V2 document (id, title, started/last-updated timestamps, demo flag) when one is open
- authenticated user summary when available
- local Skill sync directory and discovery reminder
- readiness to start meaningful work
- `next.v2_begin_tool` / `v2_update_tool` / `v2_finish_tool` pointing at the Taskforce V2 document lifecycle tools

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

For Taskforce V2-enabled users, point the agent at the document tools:

```text
If Taskforce V2 MCP tools are available:
- When creating or rotating an EnderAI MCP credential during setup, tell the user to start from a fresh terminal before reconnecting the AI client so the updated shell environment is loaded.
- Start meaningful user-initiated work with `enderai_begin_document`. It scores existing documents against the request, reuses + self-heals a strong match, or creates a fresh one.
- Use `enderai_update_document` as material progress develops (commands, files, links, decisions, changes, open questions, progress notes). Pass `details_sections` with stable `anchor_id`s to upsert specific Details sections.
- Back every Summary claim with `evidence_anchor_id` segments that point at a Details section. Do not edit `human_summary` unless the user explicitly asks.
- Use `enderai_finish_document` when the work completes or pauses; it writes Outcome and clears the active document pointer.
- Prefer Taskforce V2 document tools over the legacy V1 `enderai_begin_case` workflow and over raw `enderai_request` when both are available.
- If Taskforce V2 document tools are unavailable, do not fabricate tool calls; tell the user they are unavailable and fall back only to tools the user explicitly approves.
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
