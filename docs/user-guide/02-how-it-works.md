---
title: How Taskforce works
slug: /docs/how-it-works
order: 2
audience: all
---

# How Taskforce works

Taskforce sits between your agents and turns their work into a durable, reusable
asset. Three concepts carry the whole product: **documents**, **profiles**, and the
**reuse loop** that the **ledger** measures.

---

## Documents — the unit of memory

A Taskforce document is a distilled record of a piece of work, not a transcript. It
has two layers:

- **Summary** — the human-facing claims: what was done, what was decided, the
  outcome. This is what a person reads.
- **Details** — anchored evidence sections (commands run, files touched, decisions,
  changes, open questions). Each section has a stable `anchor_id` so a Summary claim
  can point at the exact evidence that backs it.

This Summary-over-cited-Details shape is what makes a document *auditable*: any
claim can be traced to the evidence underneath it, and a skeptic can drill into one
specific anchor and verify it. It's also why retrieval is precise — agents can be
handed just the relevant anchor, not a wall of text.

Documents are **append-only by instinct**: agents add progress and outcomes; human
Summary text is never silently rewritten by automation.

---

## The reuse loop

Every meaningful task runs the same three-beat loop:

### 1. Discover — `taskforce_begin_document`
Before working, the agent describes the request. Taskforce scores every candidate
document against it with a **deterministic congruence engine** — matching on files,
symbols, errors, and request signals — and returns the ranked candidates with
**per-signal `match_reasons`** so the decision is explainable, never a black box.

It then does one of two things:
- **Reuses** a strong match (and *self-heals* structural drift — filling a missing
  description, summary, anchors, or a Current Work section — without touching human
  content; the `self_healed_fields` array tells you exactly what it fixed), or
- **Creates** a fresh document when nothing matches well enough.

### 2. Work + update — `taskforce_update_document`
As the task progresses, the agent appends material: commands, files, links,
decisions, changes, open questions, new Summary points, and anchored Details
sections. Summary claims stay backed by Details evidence.

### 3. Finish — `taskforce_finish_document`
When the work completes or pauses, the agent writes an **Outcome** section (status,
outcome, validation, follow-ups) and clears the active-document pointer.

The payoff is in beat 1 of the *next* related task: the prior document is surfaced
before the agent starts, so it begins warm instead of re-deriving — or, just as
valuable, it's stopped from confidently doing the thing the team already learned not
to do.

---

## Profiles — reusable operating context

A **profile** (you'll see these under **Agents** in the web app) is reusable
operating context for a domain — routing triggers, linked memory, code touchpoints.
When a request matches a profile, Taskforce brings that profile in *first*, then the
documents it's linked to.

A profile is **not** an autonomous agent that goes off and does work. It's a set of
operating context that **any** harness or model can adopt — "here's how this team
handles billing," portable across Claude Code, Cursor, or anything else.

---

## The ledger — proof of value

Every reuse is recorded as an event with provenance and priced against a
**versioned** model-cost table, so historical figures stay reproducible even after
prices change. Critically, the ledger keeps two kinds of savings cleanly separate:

- **Measured** — mechanically observable savings (e.g. prompt-cache reuse, and
  answering from a document's Summary without expanding Details).
- **Estimated** — the modeled value of reuse displacing re-derivation, conservatively
  capped.

You always see which is which. See [Metrics & the ROI ledger](06-metrics-and-ledger.md).

---

## Why "across tools, owned by none" matters

The leverage isn't that one agent remembers — every harness is bolting on memory of
its own. The leverage is in the **seams no single vendor will cross**:

- **Vendor seam** — no vendor curates context for a competitor's agent. Taskforce
  lets Claude Code read what Cursor did.
- **Person seam** — your machine's memory isn't your team's shared, durable
  knowledge. Taskforce makes it shared.
- **Moment seam** — an ephemeral session's memory isn't a maintained institutional
  record. Taskforce keeps it.

That's the whole point: knowledge written by one tool, one person, one session
becomes available to all of them.

Next: **[The document workflow →](03-document-workflow.md)**
