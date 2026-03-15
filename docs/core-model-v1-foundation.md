# Core Model v1 Foundation

Last updated: 2026-03-15

This document finalizes the first implementation pass for the `Topic / Case / ContextPack` model and records the migration decisions needed to evolve from the current `Thread / Execution / Artifact` backend.

## Goals

- keep the user-facing mental model simpler than `Thread / Execution / Artifact`
- preserve the existing auditability guarantees of executions, events, and artifacts
- make future schema work incremental instead of forcing a one-shot rename across the whole backend
- define which fields are canonical, derived, editable, and snapshotted before the storage migration starts

## Canonical v1 model

The v1 model is:

- `Topic`
- `Case`
- `ContextPack`

`Topic` and `Case` are persisted records.

`ContextPack` is a synthesized hydration payload assembled when a new case begins. The pack is stored as a case snapshot for auditability, but it is derived from topic and case data rather than edited as a first-class record.

## Mapping from the current backend

The current backend already has durable concepts that line up closely enough to support an incremental migration.

| Current concept | Core model concept | v1 migration decision |
| --- | --- | --- |
| `Thread` | `Topic` | Treat the existing thread record as the storage backing for a topic during the transition period. |
| `Execution` | `Case` | Treat the existing execution record as the storage backing for a case during the transition period. |
| `Event` | Case evidence log | Keep the append-only event log attached to the case as durable raw evidence. |
| `Artifact` | Reusable takeaways / promoted guidance | Keep artifacts as reusable knowledge, not as the primary case document. |
| Execution artifact links | Case-to-guidance references | Preserve links so cases can reference reusable guidance without duplicating it. |

## v1 assumptions

- A new chat creates a new case by default.
- A case owns one canonical structured document.
- A topic groups related cases and accumulates a rollup over time.
- The same canonical case record must support both a human-readable memo view and an AI hydration view.
- Case evidence remains auditable even when summaries and rollups are rewritten.

## Persistence decisions

### ContextPack snapshot behavior

`ContextPack` should be stored on the case as a snapshot of what the AI was hydrated with when the case started.

Decision:

- Persist `context_pack_snapshot` on the case.
- Treat the stored snapshot as the audit source of truth for what the agent saw.
- Allow rebuilds for diagnostics or comparison, but do not silently replace the stored snapshot after case creation.

Why:

- it preserves reproducibility for prior work
- it avoids drift when topic rollups evolve later
- it lets future tooling compare "what was used then" vs "what would be used now"

### Editable vs derived fields

Topic fields split into two buckets.

Editable or curated:

- `title`
- `description`
- `aliases[]`
- `status`
- `owner_ids[]`
- `pinned_takeaways[]`
- `negative_history[]`

Derived or system-managed:

- `last_used_at`
- `rollup_summary`
- `rollup_version`
- `canonical_files[]`
- `canonical_symbols[]`
- `canonical_errors[]`
- `canonical_symptoms[]`
- `representative_case_ids[]`
- `recent_case_ids[]`
- `case_count`
- `vocabulary[]`

Case fields also split into two buckets.

Editable or curated:

- `title`
- `status`
- `input_summary`
- `summary_current`
- `outcome`
- `next_steps[]`

Structured evidence, append-oriented, or system-managed:

- `opened_at`
- `updated_at`
- `closed_at`
- `actor_id`
- `source`
- `files[]`
- `symbols[]`
- `errors[]`
- `symptoms[]`
- `commands[]`
- `hypotheses[]`
- `changes[]`
- `context_pack_snapshot`

### Topic rollup extraction and pinning

Decision:

- Automatically extract rollup candidates from case updates.
- Keep pinned takeaways and negative history explicitly curated so high-value lessons do not churn.
- Track representative cases and recent cases automatically.
- Allow the rollup builder to emit suggested aliases and vocabulary, but require explicit promotion before they become pinned canonical signals.

This keeps the rollup useful without making every transient signal canonical.

### Summary rewrite and evidence retention

Decision:

- `summary_current` is allowed to be rewritten as the case evolves.
- Raw structured evidence (`commands[]`, `hypotheses[]`, `changes[]`, event history) should remain append-oriented.
- Topic rollups should store compact derived summaries and references, not full copied evidence.

This gives humans and agents a clean current summary while preserving the underlying trail.

## Proposed v1 record shapes

### Topic

```text
Topic
- id
- title
- slug
- description
- aliases[]
- status
- repo_id / project_id
- owner_ids[]
- created_at
- updated_at
- last_used_at
- rollup_summary
- rollup_version
- canonical_files[]
- canonical_symbols[]
- canonical_errors[]
- canonical_symptoms[]
- pinned_takeaways[]
- negative_history[]
- representative_case_ids[]
- recent_case_ids[]
- vocabulary[]
- case_count
```

### Case

```text
Case
- id
- topic_id
- title
- opened_at
- updated_at
- closed_at
- status
- actor_id
- source
- input_summary
- summary_current
- files[]
- symbols[]
- errors[]
- symptoms[]
- commands[]
- hypotheses[]
- changes[]
- outcome
- next_steps[]
- context_pack_snapshot
```

### ContextPack

```text
ContextPack
- topic_id
- case_id
- topic_summary
- matched_signals
- representative_cases[]
- recent_cases[]
- canonical_files[]
- canonical_symbols[]
- canonical_errors[]
- canonical_symptoms[]
- pinned_takeaways[]
- negative_history[]
- builder_version
- created_at
```

## Storage migration plan

The first implementation step should keep the existing tables stable while introducing the core-model contract at the API and schema layer.

Phase 1:

- Keep `thread`, `execution`, `event`, and `artifact` tables in place.
- Introduce `Topic` and `Case` API schemas as compatibility views over the existing records.
- Add the structured case document fields needed by the new model.
- Add `context_pack_snapshot` to the case backing record.

Phase 2:

- Build topic matching, rollup derivation, and context-pack assembly on top of the new structured fields.
- Expose human memo and AI hydration views from the same canonical case data.

Phase 3:

- Add high-level MCP workflow tools that operate in Topic / Case terms.
- Keep the old route shapes available long enough to avoid breaking existing clients.

## Consequences for upcoming tickets

- `KAN-8` should establish this contract and the migration-safe compatibility approach.
- `KAN-9` should add the structured case document fields and public schema.
- `KAN-10` should render both memo and hydration views from the canonical case record.
- `KAN-11`, `KAN-12`, and `KAN-13` should build the topic intelligence and context-pack pipeline on top of the structured case data.
- `KAN-15` should expose the workflow through high-level MCP tools once the underlying case model exists.
