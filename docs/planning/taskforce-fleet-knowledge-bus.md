# Taskforce — Fleet Knowledge Bus (implementation plan)

*Plan (2026-06-16). Implements **piece 1** of the cross-agent sharing work sketched
in `taskforce-fleet-mission-control.md` §3 (Collaborate). Server-only — no agent,
hook, or client change required to ship the core. Read mission-control first.*

## Goal

Make **fleet membership the sharing boundary.** When any agent in a fleet session
writes a `V2Document`, every *other* member of that fleet session receives it as
candidate context on their next `/discover` — **regardless of whether their prompt
topically matches it.** This restores the "pull from another agent" experience and
removes the three current failure modes (wrong-shaped prompt, not-yet-summarized,
no semantic overlap).

## Today (grounded read)

- `/discover` candidate set = `list_v2_documents_for_actor` (actor-scoped, capped at
  `CANDIDATE_LIMIT = 200` most-recently-updated docs), then semantic rank, cutoff
  `min_score = 0.2` (`discover.py`, hook sends `min_score: 0.2`).
- `observe.py:280` **already stamps `fleet_session_id`** onto every created doc.
- Fleet membership lives on `TaskforceSessionArchive.fleet_session_id`.
- **The gap:** `/discover` never reads `fleet_session_id`. Same-fleet docs only
  surface if they happen to win the semantic ranking against the caller's prompt.
  Fleet grouping is currently cosmetic to discovery.

## Design

On each `/discover`, resolve the caller's fleet and inject its siblings' recent docs
as **guaranteed** candidates, returned in a **separate, clearly-labeled array** so
they don't pollute the topical-match precision/savings math.

1. **Resolve caller's fleet.** From the request `session_id`, look up
   `TaskforceSessionArchive.fleet_session_id` for the calling session. Null → behave
   exactly as today (no change for unassigned agents).
2. **Fetch sibling docs.** New helper `docs_for_fleet(fleet_session_id,
   exclude_session_id, limit=K)`: docs whose `fleet_session_id == X`, **excluding the
   caller's own session's docs** (this is the self-echo bug — never return the
   caller's own work back to it), ordered by recency, capped at `K` (default 3).
3. **Return distinctly.** Add optional `fleet_context: [DiscoverMatch]` to
   `TaskforceDiscoverResponse`, each entry tagged `source = "fleet"`. Do **not** fold
   into `matches` — keeping them separate means:
   - topical `matches` keep their meaning (and the savings/reference math stays clean),
   - the hook can render a second labeled block ("From your fleet" vs "Related prior
     work"),
   - fleet docs bypass the `min_score` cutoff by construction (membership, not score,
     earns inclusion).
4. **Bound cost.** Cap `fleet_context` at `K` most-recent sibling docs; reuse the
   existing per-doc summary truncation so the preamble token budget is respected.

### Why a separate array, not a score boost

A membership boost (option B) would silently re-rank topical results and muddy the
"73% rediscovery avoided" precision story. A separate `fleet_context` array (option
C) is honest: *"here is what your fleet is doing"* is a different claim from *"here
is prior work that matches your task."* Ship C.

## API shape

```python
# TaskforceDiscoverResponse — additive, backwards compatible
fleet_context: list[TaskforceDiscoverMatch] = Field(default_factory=list)
# each carries source="fleet" plus the existing match fields
# (title, summary_markdown, score?, session_id, document_id, href, last_seen_at)
```

Existing clients ignore the new field; the hook opts in to rendering it.

## Scoping & safety

- **`actor_id` still enforced.** Fleet is per-actor today; cross-user/org fleets
  depend on the visibility work flagged in mission-control §4 and are out of scope.
- **Exclude caller's own session docs** from `fleet_context` (the self-echo bug).
- **Cap at `K` (default 3)** most-recent sibling docs to bound token cost.
- **Recency window** (e.g. `last_seen_at >= now() - 8h`, matching the roster
  backstop) so a stale fleet doesn't inject dead context.

## Files to touch (backend)

- `core/taskforce/discover.py` — resolve caller fleet, assemble + dedupe candidates,
  populate `fleet_context`.
- `core/taskforce/fleet_sessions.py` (or `active_sessions.py`) — new
  `docs_for_fleet(fleet_session_id, exclude_session_id, limit, since)` helper.
- `models.py` — add `fleet_context` to `TaskforceDiscoverResponse` (+ `source` on the
  match shape if not already present).
- `api/routes/taskforce.py` `/discover` handler — thread `session_id → fleet`
  resolution (the request already carries `session_id`).
- `~/.claude/hooks/taskforce-user-prompt-submit.sh` *(optional follow-up)* — render a
  second `─── From your fleet ───` block from `fleet_context`. Server can ship first;
  rendering can land separately.

## Tests

- **Two sessions, same fleet:** A writes a doc; B's `/discover` with an *unrelated*
  prompt returns A's doc in `fleet_context`.
- **Self-echo guard:** the caller's own session docs never appear in its
  `fleet_context`.
- **Unassigned caller:** `fleet_context == []`, topical `matches` unchanged.
- **Cap + recency:** at most `K`; docs older than the window excluded.
- **Backwards compat:** response without consumers still validates.

## Sequencing

1. Helper + response field + discover assembly (server-only). ← ships the behavior
2. Tests above.
3. Hook rendering of `fleet_context` (optional, separable).
4. *Later (separate plans):* cross-user/org fleet (needs visibility work), then the
   **directive channel** = piece 2 (push/control), mission-control §2 + §"The unlock".

## Out of scope

Directive channel, push-to-agent, pause/steer/handoff (piece 2). This plan is
pull-only but **membership-guaranteed** — it makes the fleet's collective memory
arrive automatically without any agent-side or harness change.

## Related

- `taskforce-fleet-mission-control.md` §3 (Collaborate — "Fleet knowledge bus" 🟡)
- `taskforce-fleet-tab.md` (the shipped MVP / data model)
- Tickets: TF-178 observe orchestrator · TF-181 structured observe payload ·
  TF-229 fleet session membership
