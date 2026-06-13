---
title: Metrics & the ROI ledger
slug: /docs/metrics
order: 6
audience: champion
---

# Metrics & the ROI ledger

Most memory tools show you a dashboard with a big number on it. Taskforce is built
so a skeptic can **drill from any number down to one verifiable event** — because a
number you can't audit is a number a buyer won't trust. This page explains how to
read the Metrics page and, just as importantly, how to trust it.

---

## The atom: a confirmed-reuse event

Every figure on the Metrics page is a *view* of one underlying event: a stored
document was **surfaced**, **used**, and recorded with **provenance** (which
document, which agent, which model, priced against which cost table). The ledger is
**append-only** — events are inserted, never deleted — so history is stable.

When you see "saved 412,840 tokens this week," that aggregate is the sum of
individual events you can open and inspect. That drill-down is the point.

---

## Measured vs. estimated — read this part

Taskforce keeps two kinds of savings cleanly separate, and shows you which is which:

| | What it is | How it's known |
|---|---|---|
| **Measured** | Prompt-cache reuse; answering from a document's Summary without expanding Details. | Mechanically observed from real token counts. |
| **Estimated** | The modeled value of reuse displacing re-derivation. | Inferred and **conservatively capped** (bootstrap reuse is capped, not booked at full re-derivation cost). |

Why the discipline? Because *reuse happened* is provable, but *reuse saved the full
original cost* is a counterfactual — the agent might have gotten it elsewhere. So
Taskforce books only what it can defend as measured, and labels the rest as the
estimate it is. The floor is unattackable; the estimate stays honest and, where
exposed, buyer-adjustable.

When you report numbers upward, lead with the **measured** floor. It's the figure
nobody can argue with.

---

## Versioned, reproducible pricing

Every dollar figure is computed against a **versioned** model-cost table. Each
priced event points at the cost table that was in effect when it happened, so a
figure you reported last quarter still reproduces exactly today even after model
prices change. No silent restatement of history.

---

## What to look at

- **Savings totals** — measured and estimated, split out.
- **Where savings came from** — attribution across documents and people.
- **Cross-boundary reuse** — the flagship signal: a document written in one tool, by
  one person, reused by a *different* tool or a *different* person. This is the
  number no single-vendor memory can structurally show, because no vendor curates
  context for a competitor's agent or across a whole team. When you're making the
  case for Taskforce, this is the slide.
- **Methodology** — the linked page defines every metric precisely. Send skeptics
  here.
- **Ledger** — the event-level list with provenance, for export and audit.

---

## Two personas, one set of events

The same event stream is rendered for different readers — never cross-wired:

- **Developer** → time saved, "you didn't re-break it," profile credibility.
- **Champion / lead** → repeat-issue rate, regression reuse, throughput.
- **Buyer** → dollars and risk avoided.

Each reads their own denomination of the same underlying, auditable events. The
mechanics (tokens, cache, provenance) prove the value; throughput and risk price it.

Next: **[Team rollout →](07-team-rollout.md)**
