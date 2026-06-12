# Taskforce — "Fleet" tab (MVP)

*Plan (2026-06-12). Builds directly on `taskforce-active-sessions-roster.md` — that doc's `active_sessions` query is this feature's data source. Read that first.*

## Context

The active-sessions roster gives a flat, recency-sorted list of "what's currently running." Fleet is the **human control panel** on top of that: a dedicated tab where someone running several Claude instances at once (frontend/backend/payments/tracking, per the EM's tmux scenario) can see them **grouped by the work session they belong to**, drill into what each one has produced, and manually re-group them as the work shifts.

**Simplest form, stated plainly:**
- A **Fleet session** is a named, user-created group (e.g. "Checkout redesign sprint").
- Each currently-active CLI instance (a row from the `active_sessions` roster — call it a **"fleet agent"** here) belongs to **zero or one** Fleet session.
- The Fleet tab shows: Fleet sessions as boxes, each containing its member agents; an "Unassigned" bucket for agents not yet grouped; click-through on agents and sessions to existing Taskforce artifacts (documents, session-log).

### Terminology — don't confuse with `AgentSpecialist`

"Agent" here means **an active CLI session/terminal** (a `taskforce_session_archive` row — what the roster calls a sibling). This is a *different* concept from the existing `AgentSpecialist` (the seeded frontend/backend/payments/tracking *routing profiles* on `/v2/agents`). A fleet agent *has* a `specialist_slug` (which profile it routed to) and that can be shown as a label on its card — but Fleet is about live instances, not profiles. Consider naming the UI term "Agent session" or just "Session" in-product if "agent" reads as ambiguous next to the existing Agents tab.

## Data model (minimal additions)

```python
class TaskforceFleetSession(SQLModel, table=True):
    __tablename__ = "taskforce_fleet_session"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    actor_id: uuid.UUID = Field(foreign_key="user.id", index=True, ondelete="CASCADE")
    organization_id: uuid.UUID | None = Field(default=None, foreign_key="organization.id", index=True)
    name: str = Field(max_length=120)
    created_at: datetime
    updated_at: datetime
```

```python
# On TaskforceSessionArchive (existing table):
fleet_session_id: uuid.UUID | None = Field(
    default=None, foreign_key="taskforce_fleet_session.id",
    index=True, ondelete="SET NULL",
)
```

Grouping is **just a label on the session row** — removing an agent from a Fleet session sets `fleet_session_id = NULL`, it does *not* end the session (the terminal keeps running, just shows up under "Unassigned"). Deleting a Fleet session similarly un-groups its members rather than touching the underlying sessions.

## API

Builds on the roster query from the other doc (`actor_id = me`, `ended_at IS NULL`, `last_seen_at >= now() - 8h`):

- `GET /v2/taskforce/fleet` → `{ fleet_sessions: [{ id, name, agents: [<roster entry> + specialist_slug] }], unassigned: [<roster entry>] }`
- `POST /v2/taskforce/fleet` `{ name }` → create an (initially empty) Fleet session
- `PATCH /v2/taskforce/fleet/{id}` `{ name? }` → rename
- `DELETE /v2/taskforce/fleet/{id}` → delete (members fall back to Unassigned)
- `PATCH /v2/taskforce/session/{session_id}` `{ fleet_session_id }` → assign/unassign an agent (null = unassign)

Drill-down reuses **existing** endpoints — no new read surface needed:
- Agent detail → `GET /v2/taskforce/session-log?session_id=...` (already returns discover→match history) + the agent's `active_document_id` → `GET /v2/v2-documents/{id}` (existing library doc view).
- Fleet-session detail → union of each member agent's `active_document_id` plus `referenced_document_ids` from each `taskforce_session_archive` row, each linking to `/v2/library/$documentId`.

## Frontend: `/v2/fleet`

New top-level tab alongside Library/Agents/Metrics/Ledger (`TaskforceShell.tsx` nav).

**Layout (MVP):**
- A column/board of **Fleet session cards**, each a labeled box (rename inline) containing **agent chips** (reuse the roster card from the active-sessions rail: title, repo/branch, summary snippet, presence dot, `specialist_slug` badge).
- An **"Unassigned"** box at the top or side, listing agents not in any Fleet session.
- **Add to session**: dropdown on each agent chip — "Move to: [existing Fleet sessions...] / New session…". (Drag-and-drop is a nice-to-have, not MVP — a dropdown is simplest and accessible.)
- **Remove from session**: same dropdown → "Unassign".
- **Click an agent chip** → side drawer: full summary, `specialist_slug`, branch/cwd, `session-log` entries (what it discovered/reused), link to its active document.
- **Click a Fleet session header** → expand/route to a session detail view: member list + the union-of-documents list described above, each a link into `/v2/library/$documentId`.
- **Empty state**: no active agents at all → same "Connect a terminal" CTA already used on `/v2/library`.

**Freshness**: same polling pattern as the active-sessions rail (`refetchInterval: 30s`) — Fleet membership itself only changes on user edits (no polling needed for that part; just refetch on mutation).

## Sequencing (after active-sessions roster ships)

1. Migration: `taskforce_fleet_session` table + `fleet_session_id` FK on `taskforce_session_archive`.
2. Backend: 5 endpoints above (mostly CRUD + the existing roster query grouped by `fleet_session_id`).
3. Frontend: `/v2/fleet` route + nav entry, board layout reusing the roster agent-card component, dropdown-based assignment, drawer reusing `session-log` + library document view.
4. Test: open 3-4 sessions, group into 2 Fleet sessions + 1 unassigned, verify drill-down links land on the right documents, verify unassign/delete don't end sessions.

## Later ideas (not MVP)

- Auto-suggest grouping by `cwd`/`repo` similarity (agents in the same repo → suggested same Fleet session).
- Drag-and-drop between boxes.
- Fleet-session-level aggregate metrics (combined token savings, doc count) via existing `core/metrics` — once the per-session ledger rollup is wired, grouping by `fleet_session_id` is a cheap additional `GROUP BY`.
- Org-wide Fleet view (see teammates' fleets) — depends on the cross-user visibility work flagged in the roster doc.
