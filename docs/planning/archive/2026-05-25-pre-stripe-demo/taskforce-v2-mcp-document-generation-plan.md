# Taskforce V2 MCP Document Generation Plan

## Goal

Taskforce V2 should give agents a guided document lifecycle for meaningful work:

1. start work by finding or creating the right V2 document
2. update that document as evidence, decisions, commands, files, and outcomes develop
3. finalize the document when work completes or stops

The agent experience should feel like the existing guided EnderAI MCP workflow, but the durable artifact should be a Taskforce V2 document instead of a legacy Topic, Case, or ContextPack. The current backend already exposes V2 document list, create, read, and update APIs, so the first implementation step should be the MCP lifecycle layer over those endpoints.

## Current Foundation

The backend V2 document model already supports the shape the UI needs:

- `title`
- `description`
- `human_summary`
- `ai_generated_summary`
- `collaborators`
- `main_body`
- `details_file_name`
- `details_markdown_sections`
- `is_demo`
- `created_at`
- `updated_at`

The current public API surface is:

- `GET /api/v1/v2/documents/`
- `POST /api/v1/v2/documents/`
- `GET /api/v1/v2/documents/{document_id}`
- `PATCH /api/v1/v2/documents/{document_id}`

The first MCP implementation should use those endpoints through the existing `enderai-api-mcp` package. A backend matching endpoint can be added later if local deterministic matching becomes too limited, but it is not required for the first version.

## Guided MCP Tools

Add three guided tools to `mcp/enderai-api-mcp/src/mcpServer.ts`.

### `enderai_begin_document`

Purpose: choose the document for the work and return an active document handle.

Recommended input:

- `request_summary`: concise user request
- `goal`: optional intended outcome
- `acceptance_criteria`: optional success criteria
- `title`: optional preferred document title
- `collaborators`: optional known collaborators
- `files`: optional files or directories in scope
- `symbols`: optional code symbols or product terms
- `errors`: optional error strings
- `contexts`: optional product/customer/context labels
- `document_id`: optional explicit document to reuse
- `reuse_within_seconds`: optional recency window
- `force_new`: optional escape hatch
- `demo`: optional demo-mode query flag

Behavior:

1. If `document_id` is provided, read that document and reuse it if accessible.
2. If `force_new` is true, create a new document.
3. Otherwise list current user's V2 documents and run the deterministic matching algorithm below.
4. Reuse the highest-confidence document when it is a strong match.
5. Self-heal the reused document before returning it.
6. Create a new document when confidence is low or the best candidate is stale, terminal, or ambiguous.

Return:

- `document_id`
- `document_url_path` when the frontend path can be derived
- `reused_existing`
- `match_confidence`
- `match_reasons`
- `self_healed_fields`
- `agent_usage_note`

### `enderai_update_document`

Purpose: append material progress and keep Summary and Details coherent.

Recommended input:

- `document_id`: optional when an active document exists in MCP session state
- `title`: optional corrected title
- `description`: optional corrected description
- `summary_points`: concise claims for Summary
- `details_sections`: detailed Markdown sections with stable anchors
- `commands`: command records with purpose and salient result
- `files`: inspected or changed files
- `links`: relevant links accessed
- `decisions`: decisions and rationale
- `changes`: code, config, docs, test, or infra changes
- `open_questions`: unresolved items
- `progress_note`: human-readable update
- `demo`: optional demo-mode query flag

Behavior:

1. Read the current document.
2. Merge new evidence into `details_markdown_sections` using stable anchor IDs.
3. Regenerate or patch `main_body` so Summary claims link to Details evidence anchors.
4. Update `ai_generated_summary` when material context changed.
5. Preserve `human_summary` unless the input explicitly asks to change it.
6. PATCH only changed fields.

### `enderai_finish_document`

Purpose: finalize the document at completion or pause.

Recommended input:

- `document_id`: optional when an active document exists in MCP session state
- `outcome`: final result
- `validation`: checks performed and results
- `follow_ups`: remaining work
- `status`: `done`, `paused`, `blocked`, or `superseded`
- `closing_note`: optional final narrative
- `demo`: optional demo-mode query flag

Behavior:

1. Read the document.
2. Ensure Summary covers final outcome, validation, and important follow-ups.
3. Ensure Details contains the full work log and evidence anchors.
4. Mark completion status in Details until the data model has a first-class status field.
5. PATCH changed fields.

## Reuse And Self-Heal Strategy

The hardest product question is deciding when an existing document is good enough to update instead of creating a duplicate. The first version should be conservative and predictable.

### Candidate Pool

Start with documents returned by `GET /api/v1/v2/documents/`.

Filter out candidates when:

- `is_demo` does not match the requested mode
- the document is clearly terminal and the new request is unrelated
- the document was updated outside the default recency window and has weak lexical overlap
- an explicit `document_id` points somewhere else

The default recency window should be 30 days, matching the existing MCP case reuse default.

### Scoring Signals

Score each candidate using deterministic signals:

- exact or normalized title overlap
- shared product, customer, workflow, or repository terms
- shared file paths or directory prefixes
- shared symbols
- shared error strings
- shared collaborators
- overlap with existing Details anchors or section headings
- recent `updated_at`
- repeated request intent, such as "continue", "update", "same issue", or "follow up"

Use additive scoring with clear reasons. Return those reasons to the agent so the choice is auditable.

### Confidence Bands

Recommended first-version thresholds:

- `high`: reuse automatically
- `medium`: reuse only when the top candidate has a clear lead and no conflict signal
- `low`: create a new document

Conflict signals should lower confidence sharply:

- different customer or tenant
- different repository or major subsystem
- different incident/error family
- title says complete/resolved but the request is a new unrelated problem
- multiple candidates tie closely

### Self-Healing

When reusing a document, fix structural drift before returning it:

- populate missing `description`
- populate missing `ai_generated_summary`
- normalize `collaborators`
- add a Details section if none exists
- create missing anchor IDs for Details sections
- repair Summary segments that refer to missing anchors
- add a "Current work" Details section for the new request
- update stale title or description only when the request clearly supersedes them

Self-healing should not rewrite the entire document unless the structure is unusable. Prefer minimal PATCHes that make the document navigable and evidence-backed.

## Document Structure Contract

Summary and Details should be generated together.

Summary:

- short enough to scan
- represented in `main_body`
- uses `evidence_anchor_id` on important claims
- avoids claims that cannot be backed by Details

Details:

- comprehensive Markdown in `details_markdown_sections`
- stable `anchor_id` values
- sections for request, context, investigation, commands, changes, decisions, validation, outcome, and follow-ups when applicable
- enough evidence for another agent or human to understand why the Summary is true

Human-authored fields:

- preserve `human_summary` by default
- only change it when the agent was explicitly asked to edit the human summary
- treat `ai_generated_summary`, `main_body`, and Details as the agent-maintained surface

## Backend Additions To Consider Later

The first MCP version can use list/read/create/update. Add backend endpoints only if MCP-side matching becomes too slow, inconsistent, or difficult to audit.

Potential later endpoints:

- `POST /api/v1/v2/documents/match`
- `POST /api/v1/v2/documents/{document_id}/append`
- first-class `status`
- first-class `source_refs`
- first-class `last_activity_kind`

The matching endpoint would centralize reuse scoring and let the frontend preview "this work belongs in an existing document" decisions. It should still return candidate scores and reasons rather than hiding the decision.

## MCP Session State

The MCP server should keep a lightweight active document pointer in process memory:

- `active_document_id`
- `active_document_title`
- `started_at`
- `last_updated_at`
- `demo`

This only improves ergonomics. Every write tool should still accept an explicit `document_id`, and hosted MCP instances should treat process memory as opportunistic rather than durable.

## Agent Instruction Snippet

When Taskforce V2 document tools are enabled, the Connect Agent instructions should say:

```text
For meaningful user-initiated work:
- Start with `enderai_begin_document`.
- Reuse and self-heal an existing document when the tool returns one.
- Use `enderai_update_document` as material findings, commands, files, decisions, or changes develop.
- Keep Summary claims backed by Details evidence anchors.
- Use `enderai_finish_document` when work completes or pauses.
- Prefer guided Taskforce V2 document tools over raw request calls.
```

This should replace the legacy Topic/Case instruction block for V2-enabled customers.

## Implementation Phases

### Phase 1: MCP Lifecycle Tools

- Add schemas for begin, update, and finish document tools.
- Add typed helpers for V2 document list, read, create, and patch.
- Add deterministic document matching in the MCP package.
- Add minimal in-memory active document state.
- Add self-healing helpers for missing summaries, anchors, and Details scaffolding.
- Add unit tests for schemas, matching, and self-healing.

### Phase 2: Document Generation Quality

- Improve Summary generation to keep the top claims short and evidence-backed.
- Standardize Details section templates.
- Make update merging idempotent so repeated tool calls do not duplicate sections.
- Add tests for repeated updates and anchor preservation.

### Phase 3: Product Integration

- Update Connect Agent copy for V2-enabled customers.
- Add feature flag or capability detection so legacy users keep the existing workflow.
- Add UI affordances for showing when a document was agent-maintained.
- Confirm document editing remains user-controlled and does not overwrite human Summary edits.

### Phase 4: Backend Matching Endpoint If Needed

- Move deterministic matching to the backend only if MCP-side matching is not enough.
- Preserve scoring explanations and confidence bands.
- Add backend tests for tenant/user isolation and ambiguous matches.

## Validation Plan

MCP tests:

- begin creates a document when no candidate matches
- begin reuses a high-confidence candidate
- begin creates a new document on low confidence
- begin does not reuse ambiguous tied candidates
- begin self-heals missing Details anchors
- update patches only changed fields
- update preserves `human_summary` by default
- finish records outcome, validation, and follow-ups

Backend/API tests:

- V2 document create/read/update remains owner-scoped
- demo and non-demo documents stay isolated
- PATCH rejects empty updates
- matching endpoint tests if that endpoint is added later

Integration tests:

- agent starts work, updates progress, finishes, and the frontend renders Summary, Details, and Split coherently
- evidence anchors in Summary navigate to Details
- a second related request updates the existing document instead of creating a duplicate
- an unrelated request creates a new document

## Design Constraints

- Keep the first implementation small by building on the existing V2 document API.
- Do not disrupt the frontend document design with agent-specific UI chrome.
- Make reuse decisions explainable.
- Prefer conservative duplicate creation over incorrectly merging unrelated work.
- Preserve human-authored summaries unless explicitly edited.
- Keep demo documents read-only in normal user editing flows unless a demo flag intentionally seeds or updates demo data.
- Continue using branch, pull request, and explicit merge workflow for code changes.
