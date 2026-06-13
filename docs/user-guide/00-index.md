---
title: Taskforce Docs
slug: /docs
order: 0
audience: all
---

# Taskforce Documentation

Taskforce is the **memory layer for your AI coding agents**. It captures the work
your agents do — the decisions, the fixes, the context — as cited documents, then
quietly hands that work back the next time *any* agent hits something similar. No
re-explaining your codebase. No re-deriving the same fix. And a ledger that proves,
in tokens and dollars, what that reuse was worth.

It works across every tool (Claude Code, Cursor, Codex, plain SDK scripts) and is
owned by none of them — so knowledge written by one agent, on one machine, by one
engineer is available to all of them.

---

## Start here

| If you are… | Read |
|---|---|
| A developer connecting your own agent | **[Quickstart →](01-quickstart.md)** (5 minutes) |
| Wondering what Taskforce actually does | [How Taskforce works](02-how-it-works.md) |
| Setting your agent up to capture + reuse | [The document workflow](03-document-workflow.md) |
| Using Claude Code | [The `/tf` flow](04-tf-skill.md) |
| Living in the web app | [Working in the web app](05-web-app.md) |
| The person who has to justify the spend | [Metrics & the ROI ledger](06-metrics-and-ledger.md) |
| Rolling Taskforce out to a team | [Team rollout](07-team-rollout.md) |
| Looking for the most leverage | [Best practices](08-best-practices.md) |
| Stuck | [FAQ & troubleshooting](09-faq.md) |

---

## The 30-second mental model

```
   Your agent does work          Taskforce captures it          Next agent reuses it
  ┌────────────────────┐        ┌─────────────────────┐        ┌────────────────────┐
  │ "Fix the Stripe    │        │  Document:          │        │ "Why are we getting │
  │  webhook double-   │  ───▶  │  Stripe webhook     │  ───▶  │  duplicate charges?" │
  │  charge"           │        │  idempotency        │        │                     │
  │                    │        │  · Summary + cited  │        │ Taskforce surfaces  │
  │                    │        │    Details anchors  │        │ the prior doc before │
  │                    │        │  · who/when/what    │        │ the agent starts.    │
  └────────────────────┘        └─────────────────────┘        └────────────────────┘
                                          │
                                          ▼
                                ┌─────────────────────┐
                                │  ROI ledger:        │
                                │  "reuse saved 28,432 │
                                │   tokens (~$0.38)"   │
                                └─────────────────────┘
```

Three things make Taskforce different from "an AI that remembers":

1. **It's a record, not a chat log.** Work is distilled into linkable documents —
   a Summary backed by anchored Details — so claims are auditable, not vibes.
2. **It crosses the seams a single vendor won't.** Across tools, across people,
   across sessions. Claude Code can read what Cursor did. You can read what your
   teammate's agent did last quarter.
3. **It proves its own value.** Every reuse is logged with provenance and priced
   against a versioned model-cost table, with *measured* savings kept honestly
   separate from *estimated* ones.

> **New accounts start on the MAX tier.** You can connect an agent and start
> capturing immediately — see the [Quickstart](01-quickstart.md).
