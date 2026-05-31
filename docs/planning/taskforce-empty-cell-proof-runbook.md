# Taskforce Empty-Cell Proof Runbook

This runbook prepares and runs the TF-204 proof scenario against a live backend
database. It is intentionally non-demo: Alice and Bob are real users in one
organization, Alice's document is produced through Taskforce observe, and Bob's
session writes the real `document.consulted` ledger row.

## Prerequisites

- Backend working directory: `demo/full-stack-fastapi-template/backend/`
- A reachable Postgres database configured by the backend environment.
- Alembic migrations applied, including the C1 `produced_by_client` migration.
- `TASKFORCE_OBSERVE_SHADOW=0` for the process that runs the scenario.

## Run

```bash
cd demo/full-stack-fastapi-template/backend
TASKFORCE_OBSERVE_SHADOW=0 uv run python -m app.scripts.seed_empty_cell_scenario
```

The script creates or updates:

- Organization: `Acme`
- Alice: `alice@acme.example`
- Bob: `bob@acme.example`
- Shared password: `Taskforce123!`
- Non-demo organization-visible specialist: `payments`

From a clean database, it then:

1. Produces Alice's Stripe refund webhook idempotency document through
   `app.core.taskforce.observe.observe` with `client="codex"` and
   `visibility="organization"`.
2. Pins that real document to the `payments` specialist.
3. Starts Bob's session through `app.core.taskforce.session.session_start` with
   `client="claude-code"`.
4. Commits only after Bob's session emits a `document.consulted` event for
   Alice's document.

## Verify

Use the JSON printed by the script for the concrete ids. The proof row should
show:

- `document.produced_by_client = "codex"`
- `document.visibility = "organization"`
- `consulted_event.consumed_by_client = "claude-code"`
- `consulted_event.specialist_slug = "payments"`
- `consulted_event.net_saved_tokens > 0`
- Bob's `matched_document_ids` contains Alice's document id

SQL spot checks:

```sql
select id, owner_id, produced_by_client, visibility, is_demo
from v2_document
where title = 'Stripe refund webhook idempotency guardrail';

select id, user_id, document_id, payload->>'consumed_by_client' as consumed_by_client,
       payload->>'specialist_slug' as specialist_slug,
       payload->>'net_saved_tokens' as net_saved_tokens
from metrics_event
where kind = 'document.consulted'
order by occurred_at desc
limit 5;
```

If the script exits before committing, first check that
`TASKFORCE_OBSERVE_SHADOW=0` was present and that Alice/Bob share the printed
organization id.
