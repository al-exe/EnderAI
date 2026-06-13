---
title: The document workflow
slug: /docs/document-workflow
order: 3
audience: developer
---

# The document workflow

This is the lifecycle your agent runs for every meaningful task. Understanding it
helps you get clean, reusable documents instead of noise — and clean documents are
what make the *next* task start warm.

The three tools (canonical names; `enderai_*` aliases still work for one release):

| Tool | When | What it does |
|---|---|---|
| `taskforce_begin_document` | Start of meaningful work | Scores candidates, reuses + self-heals a match or creates a fresh document. Sets the active document for the session. |
| `taskforce_update_document` | As progress develops | Appends commands, files, links, decisions, changes, open questions, summary points, anchored Details sections. |
| `taskforce_finish_document` | Work completes or pauses | Writes the Outcome section and clears the active document. |

Plus `taskforce_session_info` to inspect session policy, auth, and the active
document at any time.

---

## `taskforce_begin_document`

Call this **before** doing the work, with a `request_summary` and any signals you
already have:

| Field | Use |
|---|---|
| `request_summary` | Short statement of the task or problem (required). |
| `title`, `goal` | Optional human framing for a new document. |
| `files` | Paths already known to be relevant — strong matching signal. |
| `symbols` | Functions/classes/identifiers involved. |
| `errors` | Known error strings or stack signatures. |
| `contexts` | Free-form context snippets. |
| `collaborators` | People involved. |

**Read the response before continuing:**
- `match_reasons` — *why* this document was chosen (per-signal contributions).
- `candidate_summaries` — the ranked alternatives and their scores; matching is
  auditable, not a black box.
- `self_healed_fields` — any structural drift Taskforce repaired before handing the
  document back (it fills gaps; it never rewrites human content).

> **Tip on file hints:** send the 1–2 most *handler-shaped* files (the request entry
> points — routes/handlers/controllers, or a service whose name matches the task),
> not everything. Each candidate is scored on how many of your sent files appear in
> *its* corpus, so a pile of loosely-related paths dilutes the signal. Two
> well-chosen paths is the sweet spot.

---

## `taskforce_update_document`

Call as material progress develops — not on every trivial step, but whenever
something worth preserving happens. Useful fields:

- `progress_note` — a short narrative beat.
- `commands` — commands you ran and what they showed.
- `files`, `links` — what you touched / referenced.
- `decisions` — choices made and why (the highest-value content for future reuse).
- `changes` — what actually changed.
- `open_questions` — what's still unresolved.
- `summary_points` — new Summary-level claims.
- `details_sections` — upsert a specific Details section by stable `anchor_id`.

Two rules that keep documents trustworthy:
1. **Keep Summary claims backed by Details evidence anchors.** A claim with no
   supporting anchor is a claim a future reader can't verify.
2. **Don't edit `human_summary` unless the user explicitly asks.** Human-authored
   summary text is sacred; automation appends, it doesn't overwrite.

---

## `taskforce_finish_document`

Call when the work completes or pauses. It writes an **Outcome** section —
`status`, `outcome`, `validation`, `follow-ups` — and clears the active-document
pointer so the next `begin` starts clean.

Finishing matters even when you "didn't fully solve it": a paused document with
honest open questions and an outcome is exactly what saves the next person from
re-discovering the same dead end.

---

## Pricing your turns (so savings are accurate)

Pass `usage` on `begin` / `update` / `finish` with your most recent turn's token
counts (`model_id`, `input_tokens`, `output_tokens`, `cache_read_input_tokens`,
`cache_creation_input_tokens`). The Metrics page uses this to price the work and
attribute savings.

When you answered straight from a document's **Summary** without expanding its
Details, also set `view_consulted: "summary"` — that fires the *summary-only*
savings calculation (a measured saving: you got the answer without paying to read
the full evidence).

Claude Code users who installed the cost-tracking hook get this automatically.

---

## A worked example

```
taskforce_begin_document {
  request_summary: "Stripe webhook charging customers twice on retries",
  files: ["app/api/routes/billing.py"],
  errors: ["duplicate charge", "idempotency_key reused"]
}
→ reuses "Stripe webhook idempotency" (match_reasons: files+errors),
  self_healed_fields: ["details:current-work"]

…agent reads the prior decision, applies the idempotency-key guard…

taskforce_update_document {
  decisions: ["Reuse Stripe idempotency_key per event id, not per retry"],
  changes: ["billing.py: guard handler with event-id dedupe"],
  files: ["app/api/routes/billing.py"],
  summary_points: ["Retries no longer double-charge; dedupe keyed on event id"]
}

taskforce_finish_document {
  status: "shipped",
  outcome: "Duplicate charges eliminated",
  validation: "added test_webhook_retry_idempotent — passing"
}
```

Next: **[The `/tf` flow →](04-tf-skill.md)**
