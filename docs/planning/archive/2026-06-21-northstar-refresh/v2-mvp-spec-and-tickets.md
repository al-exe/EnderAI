> ⚠️ **ARCHIVED 2026-06-21 — historical; NOT current product direction.**
> Superseded by [`../../taskforce-northstar.md`](../../taskforce-northstar.md). Retained for reference only. Future agents: do not treat this as current guidance.

# EnderAI v2 MVP Spec and Implementation Tickets

Date: 2026-04-27

## MVP Objective

Build v2 as a side-by-side harness layer without breaking the current v1 deployment.

The MVP should prove one vertical slice:

> A human can queue a work item, EnderAI can build a cited Context Pack v2, an agent can run inside a bounded Case/Run, and a human can observe, steer, approve, reject, or stop the work.

## Product Scope

### In Scope

- first-class Context Pack v2
- work queue
- active run model
- append-only run timeline
- cited context selection
- basic freshness state
- MCP opt-in v2 run flow
- frontend operations views
- human control actions
- self-audit summary at run finish

### Out of Scope

- billing
- enterprise RBAC
- full multi-agent scheduling
- automatic production deploy/merge
- full Jira/Linear integration
- broad semantic memory across all sources
- complex organization hierarchy
- replacing v1 APIs

## Non-Negotiable Guardrails

- Do not break existing `/api/v1/*` behavior.
- Do not remove or rename `case_record.context_pack_snapshot`.
- Add schema only; do not drop/rename v1 fields.
- Gate v2 behavior behind feature flags.
- Keep v1 production on the current domain until v2 is explicitly promoted.
- v2 can depend on v1 data; v1 must not depend on v2.

Recommended flags:

- `ENABLE_CONTEXT_PACK_V2`
- `ENABLE_RUNS_V2`
- `ENABLE_MCP_RUNS_V2`
- `ENABLE_GITHUB_INGESTION`

## Domain and Deployment Plan

Keep current production stable:

- `www.enderai.xyz` = v1 production frontend
- existing Render backend/MCP = v1 production services

Use separate v2/staging surfaces:

- `staging.enderai.xyz` or `v2.enderai.xyz`
- `api-staging.enderai.xyz` or `api-v2.enderai.xyz`
- `mcp-staging.enderai.xyz` or `mcp-v2.enderai.xyz`

Use a separate staging database.

## Core v2 Objects

### WorkItem

A queued unit of engineering work.

Minimum fields:

- id
- title
- description
- status
- priority
- source
- source_url
- topic_id
- created_by_user_id
- assigned_agent_label
- created_at
- updated_at

### Run

One autonomous execution attempt.

Minimum fields:

- id
- work_item_id
- topic_id
- case_id
- status
- agent_label
- started_at
- finished_at
- paused_at
- stop_reason
- context_pack_id
- summary
- confidence
- created_at
- updated_at

### ContextPackV2

A persisted, cited operational briefing.

Minimum fields:

- id
- topic_id
- case_id
- run_id
- builder_version
- title
- summary
- confidence
- freshness_status
- selected_case_ids
- canonical_files
- canonical_symbols
- known_constraints
- prior_failed_approaches
- open_questions
- next_suggested_actions
- why_selected
- created_at
- refreshed_at
- stale_at

### ContextPackCitation

Evidence behind a Context Pack claim.

Minimum fields:

- id
- context_pack_id
- claim_key
- source_type
- source_id
- source_url
- file_path
- symbol
- excerpt
- confidence
- created_at

### RunEvent

Append-only audit event.

Minimum fields:

- id
- run_id
- case_id
- type
- message
- data
- created_at

### HumanIntervention

A human control action.

Minimum fields:

- id
- run_id
- actor_user_id
- action
- instruction
- reason
- created_at

Supported MVP actions:

- pause
- resume
- steer
- approve
- reject
- kill

### RunReview

Agent self-audit and human-readable final review.

Minimum fields:

- id
- run_id
- result
- summary
- risks
- tests_run
- files_changed
- follow_ups
- confidence
- created_at

## MVP User Flow

1. Human creates a WorkItem.
2. EnderAI matches or creates a Topic.
3. EnderAI builds a Context Pack v2.
4. Human or MCP starts a Run.
5. Agent receives Context Pack v2.
6. Agent logs RunEvents while working.
7. Human watches active Run timeline.
8. Human can pause, resume, steer, approve, reject, or kill.
9. Agent finishes with RunReview.
10. EnderAI promotes useful learnings into Topic memory.

## Implementation Tickets

### Epic 0: v2 Safety and Platform

#### V2-001: Add v2 feature flags

Goal: introduce backend and frontend feature flags for dormant v2 code.

Acceptance criteria:

- backend settings expose `ENABLE_CONTEXT_PACK_V2`, `ENABLE_RUNS_V2`, `ENABLE_MCP_RUNS_V2`, and `ENABLE_GITHUB_INGESTION`
- frontend can read `VITE_ENABLE_CONTEXT_PACK_V2` and `VITE_ENABLE_RUNS_V2`
- production defaults keep all v2 behavior off

#### V2-002: Create staging deployment runbook

Goal: document how v2 will deploy without touching v1 production.

Acceptance criteria:

- doc lists staging frontend/backend/MCP URLs
- doc lists required env vars
- doc lists rollback steps
- doc identifies separate staging database requirement

#### V2-003: Add backend CI

Goal: protect backend changes before v2 schema/API work begins.

Acceptance criteria:

- GitHub Actions workflow runs formatting/lint checks
- workflow runs backend tests with test env vars
- workflow does not deploy

#### V2-004: Add MCP CI

Goal: protect MCP run-flow changes.

Acceptance criteria:

- GitHub Actions workflow installs MCP package dependencies
- workflow runs TypeScript checks/tests
- workflow does not require production secrets

#### V2-005: Normalize frontend package manager in CI

Goal: make frontend CI match local workflow.

Acceptance criteria:

- deploy/test workflow uses the chosen package manager consistently
- lockfile behavior is deterministic
- build still succeeds for current v1 frontend

### Epic 1: v2 Data Model

#### V2-101: Add WorkItem model and migration

Goal: persist queued work without changing v1 Case behavior.

Acceptance criteria:

- additive Alembic migration adds `work_item`
- model includes MVP fields
- table can link to Topic
- tests cover create/read basics

#### V2-102: Add Run model and migration

Goal: represent one autonomous execution attempt.

Acceptance criteria:

- additive migration adds `agent_run`
- model links to WorkItem, Topic, Case, and ContextPackV2 where available
- status supports queued, running, paused, blocked, reviewing, succeeded, failed, killed
- tests cover status transitions at model/service level

#### V2-103: Add ContextPackV2 model and migration

Goal: persist Context Packs as first-class artifacts.

Acceptance criteria:

- additive migration adds `context_pack`
- model includes MVP fields
- model links to Topic, Case, and Run
- no changes are required to v1 `case_record.context_pack_snapshot`

#### V2-104: Add ContextPackCitation model and migration

Goal: attach evidence to Context Pack claims.

Acceptance criteria:

- additive migration adds `context_pack_citation`
- citation links to ContextPackV2
- citation supports case, event, file, symbol, PR, commit, CI, and human note source types
- tests cover citation serialization

#### V2-105: Add RunEvent model and migration

Goal: provide append-only run audit timeline.

Acceptance criteria:

- additive migration adds `run_event`
- events link to Run and optionally Case
- event payload supports JSON data
- service prevents event mutation outside explicit supersession strategy

#### V2-106: Add HumanIntervention and RunReview models

Goal: persist human control actions and final self-audit.

Acceptance criteria:

- additive migration adds both tables
- intervention actions support pause/resume/steer/approve/reject/kill
- run review captures result, risks, tests, files, follow-ups, and confidence

### Epic 2: Context Pack v2 Builder

#### V2-201: Create Context Pack v2 builder service

Goal: build a v2 pack from Topic, Case history, request signals, and citations.

Acceptance criteria:

- service can build a pack for an explicit Topic
- service can build a pack from request signals
- output includes summary, selected cases, files, constraints, failed approaches, open questions, next actions, and why-selected reasoning
- output persists to `context_pack`

#### V2-202: Add citation generation

Goal: every important pack claim can point to source evidence.

Acceptance criteria:

- citations are generated for selected prior cases
- citations are generated for files/symbols when source data exists
- pack response includes citations grouped by claim
- missing citation coverage is visible in output

#### V2-203: Add freshness state

Goal: make stale or uncertain context visible.

Acceptance criteria:

- packs have freshness status: fresh, aging, stale, unknown
- freshness considers source timestamps
- stale status does not block pack generation
- frontend/API can display freshness

#### V2-204: Add v1 compatibility adapter

Goal: allow v2 packs to produce v1 snapshot shape when needed.

Acceptance criteria:

- adapter maps ContextPackV2 into current `ContextPackSnapshot`
- existing v1 endpoints keep their response shape
- tests prove v1 snapshot generation still works

### Epic 3: v2 API Surface

#### V2-301: Add WorkItem API routes

Goal: let frontend create and manage queued work.

Acceptance criteria:

- create/list/read/update WorkItems
- filter by status and topic
- routes require authenticated user
- feature flag blocks routes when disabled

#### V2-302: Add Run API routes

Goal: let frontend inspect and control runs.

Acceptance criteria:

- create/list/read Runs
- start/pause/resume/kill endpoints
- list RunEvents
- create HumanIntervention
- feature flag blocks routes when disabled

#### V2-303: Add Context Pack v2 API routes

Goal: expose persisted packs and builder.

Acceptance criteria:

- build pack v2 endpoint
- read pack by id
- list packs by Topic, Case, or Run
- response includes citations
- feature flag blocks routes when disabled

#### V2-304: Add RunReview API routes

Goal: expose agent self-audit results.

Acceptance criteria:

- create/read RunReview
- review links to Run
- run detail response includes review summary

### Epic 4: MCP v2 Run Flow

#### V2-401: Add opt-in MCP start run flow

Goal: allow agents to start a v2 Run without changing v1 `enderai_begin_case` default behavior.

Acceptance criteria:

- new tool or opt-in argument starts WorkItem/Run flow
- returns Context Pack v2
- v1 MCP flow still works unchanged
- feature flag disables v2 flow by default

#### V2-402: Add RunEvent logging from MCP

Goal: agent actions create audit timeline events.

Acceptance criteria:

- MCP can append command, finding, change, test, blocker, and decision events
- event payloads redact obvious secrets
- failures to log events do not break primary work unless strict mode is enabled

#### V2-403: Add MCP human-control awareness

Goal: agent can detect pause/kill/steer instructions.

Acceptance criteria:

- MCP checks run control state before write-like actions
- paused runs block further writes
- steer instructions are visible to the agent
- killed runs terminate cleanly

#### V2-404: Add MCP finish run review

Goal: agent finishes with structured self-audit.

Acceptance criteria:

- finish flow writes RunReview
- finish flow updates Run status
- finish flow updates Case summary/outcome where compatible

### Epic 5: Frontend v2 Operations UI

#### V2-501: Add v2 navigation entry behind flag

Goal: expose v2 operations only when enabled.

Acceptance criteria:

- app shell shows Queue/Active Runs only when feature flag is enabled
- v1 navigation remains unchanged by default

#### V2-502: Build Work Queue page

Goal: users can create and triage WorkItems.

Acceptance criteria:

- list queued/running/completed work
- create WorkItem
- assign Topic
- start Run from WorkItem

#### V2-503: Build Active Runs page

Goal: users can see what the machine is doing now.

Acceptance criteria:

- list active, paused, blocked, and reviewing runs
- show status, agent, topic, elapsed time, and latest event
- link to Run detail

#### V2-504: Build Run Detail page

Goal: show the operational timeline and controls.

Acceptance criteria:

- show Run status and metadata
- show Context Pack summary
- show append-only event timeline
- show changed files/tests/blockers when present
- expose pause/resume/steer/approve/reject/kill controls

#### V2-505: Build Context Pack v2 detail view

Goal: make the pack inspectable and trustworthy.

Acceptance criteria:

- show summary, selected cases, files, constraints, failed approaches, open questions, and next actions
- show citations inline or adjacent to claims
- show freshness and confidence
- show why-selected reasoning

#### V2-506: Build RunReview view

Goal: make the self-audit visible to humans.

Acceptance criteria:

- show result, risks, tests, files changed, follow-ups, confidence
- support approve/reject from review state

### Epic 6: GitHub and CI Evidence MVP

#### V2-601: Add GitHub source model stub

Goal: prepare for PR/commit/CI citations without full integration.

Acceptance criteria:

- citation source types include PR, commit, review_comment, ci_run
- API accepts manually supplied source URLs
- UI renders source links safely

#### V2-602: Add minimal GitHub PR ingestion

Goal: ingest PR metadata for citation and audit.

Acceptance criteria:

- backend can store PR title, URL, state, changed files, and commit SHA
- Context Pack citations can reference PR records
- ingestion is idempotent

#### V2-603: Add minimal CI failure ingestion

Goal: make CI results usable as evidence.

Acceptance criteria:

- backend can store CI run URL, status, conclusion, and failure summary
- RunEvents can reference CI evidence
- Context Pack v2 can cite CI failures

### Epic 7: Verification and Quality

#### V2-701: Add Context Pack v2 unit tests

Goal: protect pack builder behavior.

Acceptance criteria:

- tests cover explicit topic pack build
- tests cover signal-based topic selection
- tests cover citation creation
- tests cover freshness status
- tests cover v1 compatibility adapter

#### V2-702: Add Run lifecycle tests

Goal: protect work queue and run status behavior.

Acceptance criteria:

- tests cover create/start/pause/resume/kill/finish
- tests cover invalid transitions
- tests cover human intervention recording

#### V2-703: Add MCP v2 tests

Goal: protect agent run flow.

Acceptance criteria:

- tests cover start run
- tests cover event logging
- tests cover pause/kill awareness
- tests cover finish run review

#### V2-704: Add frontend Playwright smoke tests

Goal: protect the operations UI.

Acceptance criteria:

- queue page renders
- work item can be created with mocked API
- active runs page renders
- run detail shows timeline, Context Pack, and controls

## Suggested Implementation Order

1. V2-001, V2-002, V2-003, V2-004, V2-005
2. V2-101 through V2-106
3. V2-201 through V2-204
4. V2-301 through V2-304
5. V2-401 through V2-404
6. V2-501 through V2-506
7. V2-701 through V2-704
8. V2-601 through V2-603 when the core loop works

## Open Decisions

- Should v2 use `Run` as a new top-level product term or keep exposing `Case` to users?
- Should the MCP v2 entry point be a new tool or an opt-in argument to `enderai_begin_case`?
- Should Context Pack v2 use embeddings in MVP or start with deterministic retrieval plus citation/freshness?
- Which subdomain should be canonical for staging: `staging.enderai.xyz` or `v2.enderai.xyz`?
- Should approval gates block PR creation, merge, or both?

## MVP Exit Criteria

The MVP is complete when:

- v1 production remains functional
- v2 can run on staging with separate env/database
- a user can create a WorkItem
- EnderAI can build a cited Context Pack v2
- an agent can start a Run using that pack
- RunEvents show the agent's work timeline
- a human can pause, steer, resume, reject, approve, or kill the run
- the agent can finish with a RunReview
- useful outcomes can be promoted back into Topic memory

