---
title: Best practices
slug: /docs/best-practices
order: 8
audience: all
---

# Best practices

Taskforce rewards a few small habits with outsized returns. None of these are
required to get value — they're how you go from "it remembers things" to "it makes
every task start warm."

---

## Capture

**Begin before you build.** Call `taskforce_begin_document` (or run `/tf`) *before*
doing the work, not after. The whole point is to start warm — discovering a prior
document after you've already re-solved the problem gets you none of the savings.

**Send sharp file hints, not everything.** 1–2 handler-shaped files (the request
entry points, or a service named after the task) score far better than a long list.
Each candidate is rewarded for how many of your files appear in *its* corpus, so
loosely-related paths drag matches down.

**Capture decisions, not just changes.** A diff tells the next agent *what*
changed; a recorded decision tells it *why* — and "why" is what stops the next agent
from confidently undoing it. Decisions and open questions are the highest-reuse
content you can write.

**Finish, even when you didn't fully solve it.** A paused document with an honest
Outcome and open questions saves the next person from re-walking the same dead end.
An unclosed document helps no one.

---

## Curate

**Title for the future searcher.** Name documents the way someone would describe the
problem months later — "Stripe webhook double-charge on retries," not "billing fix
3."

**Keep Summary claims anchored.** Every Summary claim should point at a Details
anchor that backs it. Unbacked claims are claims a future reader can't trust.

**Don't overwrite human summaries.** Automation appends; it doesn't rewrite
human-authored Summary text. If a summary is wrong, fix it deliberately, not as a
side effect.

**Dedupe.** Two thin documents on the same topic retrieve worse than one good one.
Merge them.

---

## Reuse honestly

**Use the confirmation gate.** In `/tf`, only confirm "yes, resolved" when it
actually resolved — the "Referenced by" row is evidence the document was useful, and
the savings number depends on it. Honest confirmations keep your metrics defensible.

**Report the measured floor.** When you share numbers, lead with measured savings
and cross-boundary reuse. They're the figures nobody can argue with.

---

## Get the cross-seam value

**Connect more than one tool.** The flagship metric — reuse across tools — only
exists if more than one tool is connected. Get Claude Code *and* Cursor/Codex on it.

**Share into the org.** A document kept on one machine helps one person. Shared into
the organization, it helps everyone — and produces the cross-person reuse that makes
the case for the whole thing.

**Seed the store.** Reuse lags capture until there's something to reuse. Front-load
your highest-recurrence existing knowledge so early tasks get early hits.

Next: **[FAQ & troubleshooting →](09-faq.md)**
