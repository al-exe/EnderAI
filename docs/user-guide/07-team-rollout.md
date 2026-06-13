---
title: Rolling out to your team
slug: /docs/team-rollout
order: 7
audience: champion
---

# Rolling Taskforce out to your team

A single developer gets value from Taskforce on day one — their own agent stops
re-deriving their own past work. But the compounding value, and the reason the spend
is justified, is **cross-person and cross-vendor reuse**: one engineer's solved
problem becoming every engineer's starting point, regardless of which tool they use.

This page is for the person driving that rollout — typically a staff+, platform, or
reliability lead who both feels the dev value and owns the metrics that roll upward.

---

## The shape of a rollout

### 1. Seed before you scale
The reuse flywheel doesn't self-start: reuse lags capture until the store has
something in it. Don't wait for it to fill organically. **Seed it** — run your
highest-recurrence existing knowledge (recent incidents, gnarly PRs, postmortems,
the "ask so-and-so" tribal knowledge) through the document workflow so the first
people to hit a related task get an immediate hit. Early hits are what make the
habit stick.

### 2. Connect a pilot group
Have each pilot engineer follow the [Quickstart](01-quickstart.md): create their own
credential, connect their agent, paste the instruction block. Tokens are per-user,
so reuse is correctly attributed to people from the start.

Cover the tools you actually use — the cross-vendor seam only shows up if more than
one tool is connected. Get at least one Claude Code user and one Cursor/Codex user
in the pilot so the first cross-tool reuse event lands.

### 3. Share into the organization
Encourage sharing useful documents into the org (Library → Shares). This is the step
that converts "my machine's memory" into "the team's durable knowledge." Folders by
domain or service keep it navigable as it grows.

### 4. Watch the right number
On the Metrics page, the rollout's headline isn't total tokens — it's
**cross-boundary reuse**: a document written by one person or tool, reused by
another. That's the value no single-vendor memory can produce, and it's the proof
the shared store is doing something a per-developer tool can't.

---

## Curation is load-bearing, not polish

The input to the flywheel is *curated, reusable knowledge* — not raw activity. If
the store fills with uncurated noise, retrieval gets worse and the wheel spins
backward. A few habits keep it healthy:

- **The confirmation gate is a quality filter.** Reuse is only recorded when the
  user confirms it helped (see [the `/tf` flow](04-tf-skill.md)). Lean into it.
- **Dedupe and title well.** Merge near-duplicates; give documents names a future
  searcher would actually type.
- **Honest outcomes beat heroic summaries.** A paused document with clear open
  questions saves more re-derivation than an overclaimed "solved."

---

## Organization & access

- **Members** are admins or members; admins manage invitations and membership.
- **Metrics are org-scoped** — you can read savings for yourself or for the whole
  organization, so the champion sees the team picture while each developer still
  sees their own.
- **Credentials are per-user and rotatable**, so onboarding and offboarding are
  clean: rotate or revoke a token and that agent's access stops immediately.

---

## Making the case upward

When you take this to the person writing the check:

- Lead with the **measured** savings floor and the **cross-boundary reuse** number —
  the two things a competitor's dashboard structurally cannot show.
- Use the **Methodology** page to disarm "how do you know?" — every figure is
  defined and drillable to a single event.
- Frame the recurring win as **not re-deriving solved work and not re-explaining
  context every session** — the highest-frequency, most universal cost of agents
  forgetting.
- Invoice on something mechanical (seats/usage); sell on throughput and risk
  avoided. The tokens prove it; the throughput prices it.

Next: **[Best practices →](08-best-practices.md)**
