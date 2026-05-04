# Single-Token, Auto-Hydrating EnderAI MCP Workflow

## Summary

EnderAI now standardizes on a single hosted-MCP workflow:

- each user gets one per-user MCP token
- that token is sent to the hosted MCP as `Authorization: Bearer ...`
- the hosted MCP validates the token and reuses it for backend API calls on behalf of the user
- there is no second backend token in the normal product flow

The canonical meaningful-work lifecycle is:

1. the user initiates meaningful work
2. the agent calls `enderai_begin_case`
3. EnderAI automatically hydrates relevant prior context and generated Skill matches if they exist
4. the case becomes active
5. the agent reads any returned local Skill markdown files for this task
6. the agent proceeds with work
7. the agent calls `enderai_update_case` as work develops
8. the agent calls `enderai_finish_case` when complete

## Auth Model

### Single token only

The only user-visible token is `mcp_access_token`.

That token is used for both:
- authenticating the client to the hosted MCP
- authorizing backend API calls made by the hosted MCP on behalf of that user

### Removed from the product flow

The product should not rely on or document:
- `ENDERAI_BACKEND_TOKEN`
- `X-EnderAI-Backend-Token`
- dual-token onboarding
- legacy token toggles in setup UI

## Canonical Workflow

### Meaningful work starts with EnderAI

For meaningful user-initiated work, the default first call is:
- `enderai_begin_case`

This is the normal entrypoint for feature work, debugging, investigation, refactors, and other multi-step work where retained context matters.

### Automatic hydration

`enderai_begin_case` should automatically:
- identify the relevant topic
- gather related prior cases when available
- build a compact `ContextPack`
- attach that hydration snapshot to the started case
- match generated Skills from the hydrated case signals
- sync matched Skill markdown locally and return the file paths to read

If no relevant prior context exists, the case still starts normally.

Generated Skill guidance is advisory. Agents should read only the `local_skill_files` returned by `skill_hydration` or `enderai_use_skill` for the current task unless the user asks for broader Skill exploration.

### Progress updates

As work develops, the agent should record material progress with `enderai_update_case`, including:
- findings
- commands
- hypotheses
- changes
- errors
- next steps

### Completion

When work completes or stops, the agent should close the case with `enderai_finish_case`.

## MCP Tool Expectations

### Guided tools

The guided workflow tools are the default surface:
- `enderai_begin_case`
- `enderai_use_skill`
- `enderai_update_case`
- `enderai_finish_case`
- `enderai_session_info`

### Lower-level escape hatch

`enderai_request` remains available, but it is not the normal lifecycle entrypoint.

Write-like low-level requests should require:
- an active case, or
- an explicit escape-hatch reason

## Connect Agent UX

The setup UI should generate:
- the one MCP token the user needs
- client-agnostic setup for an MCP-capable AI client
- a short workflow instruction snippet telling the agent to start meaningful work with `enderai_begin_case`

The setup UI should not generate:
- backend-token env vars
- header overrides for backend auth
- legacy-mode setup branches

## Verification

Recommended verification flow:

1. connect the local client to the hosted MCP
2. run `enderai_session_info`
3. confirm the session is authenticated and ready
4. start a real task and confirm the agent uses `enderai_begin_case`

## Implementation Notes

### Backend
- collapse agent credential issuance to a single `mcp_access_token`
- keep `validate-mcp-token` as the per-user MCP validation endpoint
- allow the MCP token to authenticate normal backend requests for that user

### MCP server
- remove client-provided backend-token override behavior from the normal flow
- expose `enderai_session_info`
- make `enderai_begin_case` return explicit hydration metadata
- make `enderai_begin_case` and `enderai_use_skill` sync matched generated Skills to local markdown
- reject write-like `enderai_request` calls when no active case exists unless an explicit override reason is supplied

### Frontend
- simplify `Connect Agent` to one-token-only setup
- add the minimal workflow snippet to the page
- remove dual-token branches and copy

## Acceptance Criteria

The implementation is successful when:
- users only receive one token in the Connect Agent flow
- setup snippets only reference `ENDERAI_MCP_TOKEN`
- meaningful work starts with `enderai_begin_case`
- `enderai_begin_case` auto-hydrates prior context by default
- matched generated Skills are returned as local markdown file paths for the agent to read
- `enderai_request` write-like calls do not bypass the active-case workflow
- onboarding docs and templates no longer describe a second backend token
