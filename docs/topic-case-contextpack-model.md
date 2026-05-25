# Topic / Case / ContextPack Model

## Canonical Model

EnderAI uses a single canonical domain model:

- `Topic`
- `Case`
- `ContextPack`

These are the only product-memory concepts the active runtime should depend on.

## Topic

A Topic is the reusable area of work.

A Topic should capture:

- title
- slug / stable key
- description
- aliases
- status
- ownership metadata
- rollup summary
- rollup-derived canonical files, symbols, errors, and symptoms
- representative and recent case references

## Case

A Case is a bounded work session under a Topic.

A Case should capture:

- topic id
- title
- status
- opened / updated / closed timestamps
- input summary
- current summary
- files
- symbols
- errors
- symptoms
- commands
- hypotheses
- changes
- outcome
- next steps
- context pack snapshot

## ContextPack

A ContextPack is the synthesized hydration payload for a Case.

A ContextPack should capture:

- selected topic ids
- selected case ids
- relevant prior cases
- matched signals
- canonical files / symbols / errors / symptoms
- pinned takeaways
- ambiguity notes
- open questions
- builder metadata and confidence

## User-Facing Language

The user-facing language should be:

- `Topics`
- `Cases`

`ContextPack` is an internal/system construct rather than a primary navigation object.

## Route and API Expectations

The canonical frontend paths are:

- `/topics`
- `/cases`

The canonical backend product endpoints are:

- `/api/v1/topics`
- `/api/v1/cases`
- `/api/v1/context-packs/build`

## Non-Goals

The active product model does not include any separate demo-template item surface.
