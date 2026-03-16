# Topic / Case / ContextPack Model

## Purpose

This document defines a first-pass model for EnderAI memory that is simpler than the current `Thread / Execution / Artifact` naming while preserving the important behavior:

- group related work
- separate one work session from another
- hydrate future AI work with useful prior context
- keep saved context useful to both humans and AI

## Core Model

### User-Facing Language

The primary user-facing concepts should be:

- `Topic`
- `Case`

`Note` can exist as contextual memory or supporting content, but it should not be treated as a primary top-level navigation concept.

During the transition, backend and API compatibility layers may still use `Thread`, `Execution`, and `Artifact`, but the product should keep raising `Topic` and `Case` to users.

The recommended v1 model is:

- `Topic`
- `Case`
- `ContextPack`

`Topic` and `Case` are stored records. `ContextPack` is a synthesized hydration payload assembled when a new case begins.

In v1, a `Case` owns one canonical structured document rather than multiple free-form notes.

## Conceptual Mapping

Existing terminology maps roughly like this:

- `Thread` -> `Topic`
- `Execution` -> `Case`
- `Artifact` -> split across the case document, pinned takeaways, and topic rollup

This is not a claim that the storage model must be identical. It is a mental model simplification.

## High-Level Diagram

```text
Topic
  |
  +-- Case A
  |     |
  |     +-- Case document
  |
  +-- Case B
  |     |
  |     +-- Case document
  |
  +-- Topic Rollup (derived from all cases)
        |
        +-- used to synthesize ContextPack for new cases
```

Hydration path:

```text
new user request
  -> topic matching
  -> new Case
  -> build ContextPack from Topic Rollup + relevant prior Cases
  -> hydrate AI
  -> patch Case as work evolves
  -> update Topic Rollup and topic indices
```

## Topic

`Topic` is the reusable area of work.

Examples:

- `Notebook frontend bugs`
- `Payments webhook failures`
- `Build pipeline flakiness`

Suggested fields:

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
```

### Notes

- `title` should be human-facing.
- `aliases[]` helps topic matching.
- `rollup_summary` is a compact derived summary, not the full rollup payload.

## Case

`Case` is one work session or AI chat under a topic. New chat creates a new case by default.

Examples:

- `Notebook hydration bug - 2026-01-01`
- `Notebook mobile flicker investigation - 2026-01-02`

Suggested fields:

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

### `commands[]`

```text
CommandRecord
- cmd
- purpose
- salient_result
- ts
```

### `hypotheses[]`

```text
HypothesisRecord
- statement
- status        // open | supported | disproven
- evidence
- ts
```

### `changes[]`

```text
ChangeRecord
- kind          // code | config | infra | docs | test
- summary
- files[]
- refs[]        // commit, PR, diff, issue, etc.
- ts
```

### Why a structured case document

The case document needs to be useful to:

- a human engineer skimming prior work
- an AI agent hydrating context for similar future work

That means it cannot rely on vague prose alone. It needs stable anchors such as files, symbols, errors, commands, hypotheses, and outcome.

## Topic Rollup

`Topic Rollup` is a derived topic-level memory built from all cases under a topic. It is more than a blurb.

It should answer:

- what this topic usually refers to
- what signals commonly identify it
- what prior cases are representative
- what lessons and dead ends recur

Suggested rollup shape:

```text
TopicRollup
- topic_id
- brief
- canonical_files[]
- canonical_symbols[]
- canonical_errors[]
- canonical_symptoms[]
- pinned_takeaways[]
- negative_history[]
- representative_case_ids[]
- aliases[]
- vocabulary[]
- ambiguity_notes[]
- open_questions[]
- case_count
- recent_case_ids[]
- updated_at
```

### How the rollup is built

The rollup should be updated whenever cases are created or modified.

Useful derived signals include:

- file/path frequencies
- symbol frequencies
- symptom and error string frequencies
- repeated commands
- repeated failed hypotheses
- repeated successful fixes
- representative cases by recency and relevance
- aliases and topic vocabulary discovered from case text

This can be implemented as a materialized summary, cached document, or background-derived object. It does not need to be manually edited in full.

## ContextPack

`ContextPack` is the hydration payload built for a new case. It should be compact and selective.

Suggested shape:

```text
ContextPack
- topic_match
- topic_brief
- pinned_takeaways[]
- relevant_cases[]
- ambiguities[]
- questions[]
- negative_history[]
```

### `topic_match`

```text
TopicMatch
- topic_id
- confidence
- reasons[]
- alternative_topic_ids[]
```

### `relevant_cases[]`

Each relevant case should be summarized, not dumped whole.

```text
RelevantCase
- case_id
- title
- short_summary
- outcome
- key_files[]
- key_symbols[]
- key_errors[]
- key_commands[]
- why_selected
```

## Context Pack Construction

The pack should be synthesized dynamically at hydration time from:

- the selected or matched topic
- the topic rollup
- top relevant prior cases
- current request signals

The system should not simply ask a model to invent the entire pack from scratch every time. Better pattern:

1. Retrieve structured candidate data.
2. Rank relevant topics and cases.
3. Assemble a compact draft pack.
4. Optionally let an AI compress or rewrite it for clarity.

That keeps the pack grounded in real stored context rather than only model narration.

## Topic Matching

Topic matching should be hybrid, not purely semantic and not purely title-based.

Suggested matching inputs:

- topic title
- aliases
- file paths
- symbols
- symptoms
- error strings
- recent activity
- semantic similarity on request text

Suggested hydration policy:

- high confidence -> hydrate top 1 topic
- medium confidence -> hydrate top 2-3 topics
- low confidence -> hydrate top 4-5 topics

If multiple topics are hydrated, the AI can ignore irrelevant packs after reading them. This is usually safer than missing the right topic entirely.

## Update Flow

Recommended flow:

1. User request arrives.
2. Match candidate topics.
3. Create a new case under the best topic or user-selected topic.
4. Build `ContextPack`.
5. Hydrate AI with the pack.
6. AI works and updates the case document.
7. Case modifications update topic indices and rollup.
8. Future cases benefit from the stronger rollup.

## Design Notes

- Keep the user-facing model simple: `Topic / Case`.
- Keep the case document canonical for both humans and AI.
- Keep the rollup derived.
- Keep the context pack synthesized.
- Prefer structured evidence over generic summaries.

## Open Design Questions

- Should `ContextPack` be stored as a snapshot on the case, or rebuilt on demand only?
- Which fields should be manually editable versus fully derived?
- Should pinned takeaways live as a dedicated sub-record type, or just as tagged rollup entries?
- How much raw evidence belongs in the case document versus external references?
- At what point does a case need more than one document?
