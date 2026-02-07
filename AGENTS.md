# EnderAI — Layer 0 Agent Rules (Repo-Wide)

Last updated: 2026-02-07
These rules define the highest-precedence behavior for any agent operating in this repository.
EnderAI’s differentiator is **continuity with trust**: past work informs the present, and present work teaches the future — but only through explicit, scoped, inspectable memory.

Optional overrides (if present): `architecture/0-agents/agents.override` (template: `architecture/0-agents/agents.override.example`).

## Memory Layers (Canonical)
- **Layer 0 — Rules Context:** `AGENTS.md` (this file)
- **Layer 1 — Ground Truth:** `architecture/1-ground-truth/` (citeable facts captured for the task)
- **Layer 2 — Knowledge Base:** `architecture/2-knowledge-base/` (curated, reusable context; not guaranteed 1==1)
- **Layer 3 — Task Context:** `architecture/3-task-context/` (in-flight notes and experiments to unblock execution)

## API-Backed Memory (Tasks/Library)
In addition to filesystem `.mdc` artifacts, EnderAI uses a Postgres-backed memory store exposed via the EnderAI backend HTTP API for:
- **Tasks** (goals + acceptance criteria)
- **Runs** (a work session/attempt on a task)
- **Run events** (append-only, timestamped log entries)
- **Library items** (reusable memory; never delete, supersede instead)
- **Run <-> Library links** (Used/Created/Promoted/Superseded)

See runbook: `architecture/1-ground-truth/tasks-library-memory-implementation.mdc`.

### How Agents Must Access Memory
- Prefer the EnderAI backend API (recommended: via the EnderAI MCP server), not direct Postgres connections.
- Treat direct DB access (psql, raw SQL, `DATABASE_URL`) as a last resort requiring explicit user approval.

MCP tools (when configured):
- `enderai_health_check`
- `enderai_openapi`
- `enderai_request` (generic API request; use `path` starting with `/`)

Auth notes:
- MCP auth (to the MCP server URL) is separate from backend auth (to `ENDERAI_BASE_URL`).
- Backend auth: obtain an `access_token` via `POST /api/v1/login/access-token` and pass it as `bearerToken` on `enderai_request`, or set `ENDERAI_BEARER_TOKEN` in the MCP service environment.

## Rules (Descending Importance)
1) **User control + least privilege**
   - Default to read-only behavior and reversible actions.
   - Treat anything with external side effects as “risky” (deploys, prod access, DB writes, pushing branches, opening PRs, schema changes, deleting data/files) and require explicit user confirmation before proceeding.
   - Never store secrets in repo docs; redact tokens/keys and store references instead.

2) **Ground truth + audit trail (timestamped)**
   - Don’t guess: if an answer matters, anchor it in ground truth (code, tests, tool output, or recorded Layer 1 artifacts).
   - Capture enough evidence to replay the work: commands tried, key outputs/errors, and code pointers (file paths + important symbols).
   - Timestamp any notes/artifacts you create or materially update (prefer UTC).
   - **Continuous updates requirement (all tasks):** update the appropriate documentation/log artifacts as you progress through each meaningful step, not only at the end.
   - If a step changes understanding, decisions, commands, or outcomes, record it immediately in the active Layer 3 log and/or the relevant task docs.
   - **Debugging requirement:** when troubleshooting live with a user (errors/logs/commands), continuously update a Layer 3 `.mdc` working log with:
     - the exact command(s) run
     - the key output/error (verbatim snippets)
     - the current hypothesis + next check
     - a clearly labeled **BREAKTHROUGH** entry when something starts working (what changed + exact command + observed result)
   - **Commit message style:** use short, imperative, Title Case summaries (e.g. “Add…”, “Update…”, “Document…”) and never include secrets.
   - **EnderAI memory logging via API (when enabled by user):**
     - If the user explicitly opts in (e.g., “keep EnderAI memory updated”, “log this to Tasks/Library”), treat writes via the EnderAI backend API (recommended: through the MCP server) as approved for the session/ticket. Still require confirmation for other destructive/external side effects.
     - Read existing memory first (Tasks/Runs/Library) via API; then inject the minimal relevant context into the current work.
     - Prefer API writes where supported (for example: `PATCH /api/v1/tasks/{task_id}` to rename, `POST /api/v1/library/` to create, `PUT /api/v1/library/{id}` to supersede-update).
     - If a desired write is not supported by the API, fall back to Layer 3 `.mdc` logging and propose the missing endpoint; do not default to direct SQL.
     - Never delete memory data; supersede instead to preserve trust.
     - Never store secrets in API-written logs/library items (passwords/tokens/DB URLs). Redact and store references only.

3) **Layer 1 first; Layer 2 only after completion; Layer 3 during execution**
   - Before starting a user-defined task/ticket, consult `architecture/1-ground-truth/`; if it’s missing or stale, add new ground truth or mark older entries as superseded.
   - Use `architecture/2-knowledge-base/` to accelerate execution, but treat it as non-authoritative and overrideable.
   - Do not write to `architecture/2-knowledge-base/` while a task is in progress; only update the knowledge base after the user confirms the task/ticket is completed.
   - During the task, write `.mdc` notes in `architecture/3-task-context/` as needed to unblock progress (code pointers, workarounds, commands tried, what worked, what failed, and why).
   - Treat Layer 3 as a live execution log: update incrementally during progress, including single-step advances and pivots.
   - **During debug loops:** prefer updating the same Layer 3 file incrementally after each attempt (don’t batch-write a summary at the end).

4) **Freshness and pruning (7-day TTL for Layer 2/3)**
   - For `.mdc` files in `architecture/2-knowledge-base/` and `architecture/3-task-context/`, include `Created` and `Last used` (or `Last reviewed`) dates.
   - Update `Last used` when the file meaningfully helps current work.
   - Prune, refresh, or consolidate anything in Layer 2/3 not used in the last **7 days**.

5) **Documentation hygiene**
   - Read relevant docs before answering or changing code, then keep them accurate and runnable.
   - If behavior/workflows change, update the corresponding docs in the same patch.
   - Keep docs/logs in sync continuously while working; do not defer routine documentation updates until final recap.
   - Remove or consolidate stale/duplicated docs; keep one canonical source whenever possible.

6) **Do updates before responding (with one exception)**
   - When a request implies repo changes (docs/code/memory artifacts), make the change first, then respond with pointers to the updated files.
   - Exception: Layer 2 updates are deferred until completion per Rule 3.
