---
title: FAQ & troubleshooting
slug: /docs/faq
order: 9
audience: all
---

# FAQ & troubleshooting

## Getting started

**Do I need a credit card to start?**
No. New accounts start on the MAX tier so you can connect an agent and start
capturing right away. Plans (`free`, `pro`, `max`) are on the Pricing page.

**Which AI tools work with Taskforce?**
Any MCP-capable client (Claude Code, Cursor, Codex, and others). For harnesses that
don't speak MCP — a plain Anthropic SDK script, a browser session, a custom
pipeline — use `taskforce-cli`, which wraps the same endpoints with the same token.

**What's the difference between the instruction block and `/tf`?**
The instruction block makes capture/reuse automatic and quiet during normal work.
`/tf` (Claude Code) runs the same loop *visibly* and asks you to confirm before
recording. Use both — see [The `/tf` flow](04-tf-skill.md).

---

## Tokens & connection

**`taskforce_session_info` fails or the tools aren't showing up.**
1. Confirm the MCP server is registered and pointed at
   `https://enderai-mcp.onrender.com/mcp`.
2. Confirm your token is saved (`~/.taskforce_mcp_token`) and sent as
   `Authorization: Bearer <token>`.
3. **Restart your client** so it reloads the MCP config and token environment —
   this is the most common fix.

**`/tf` says "Taskforce not connected."**
Your client doesn't have a valid token. Set one up at
[Settings → Connect Agent](https://www.taskforce.tools), then re-run. `/tf` degrades
gracefully — it'll do the task without Taskforce until you connect.

**I lost my token.**
Tokens are shown only once at creation. Rotate the credential in Settings → Connect
Agent to get a fresh one; the old token stops working immediately.

**Can I revoke access for a machine or a person?**
Yes — rotate or delete that credential. Access stops at once. Tokens are per-user,
so this is also how you offboard cleanly.

---

## Documents & reuse

**Why didn't Taskforce reuse a document I know exists?**
Matching is signal-driven. Check the `candidate_summaries` and `match_reasons` in the
`taskforce_begin_document` response — they show what scored and why. Often it's
because the request didn't carry the files/symbols/errors that the document is keyed
on. Sending 1–2 sharp file hints usually fixes it.

**Why did it create a new document instead of reusing?**
No candidate scored high enough to be a confident match. That's by design — a weak
match is worse than a fresh start. The new document becomes reusable for the *next*
related task.

**Will Taskforce overwrite my hand-written summaries?**
No. Automation appends; it self-heals structural gaps (missing description, anchors,
a Current Work section) but never rewrites human-authored Summary content. The
`self_healed_fields` array tells you exactly what it touched.

**My document looks half-finished.**
If work paused, that's expected — finishing writes an honest Outcome with open
questions. A paused-but-closed document is still valuable to the next person.

---

## Metrics

**Why are my dollar figures modeled instead of exact?**
Exact figures need real per-turn token counts. Claude Code users get this by
installing the cost-tracking hook (Connect Agent → "Claude Code cost tracking").
Other clients can pass `usage` on the document tools. Without it, reuse is still
tracked; the dollars are modeled.

**What's the difference between "measured" and "estimated" savings?**
Measured = mechanically observed (cache reuse, summary-only answers). Estimated =
the conservatively-capped modeled value of reuse displacing re-derivation. Taskforce
always shows which is which — see [Metrics & the ROI ledger](06-metrics-and-ledger.md).
Lead with the measured floor when you report numbers.

**A number changed — did history get restated?**
No. The ledger is append-only and pricing is versioned, so historical figures
reproduce exactly even after model prices change. New events add to totals; old
events don't move.

---

## Privacy & scope

**Is my code sent to Taskforce?**
Taskforce captures the *distilled record* of work — decisions, summaries, file
paths, anchored evidence your agent chooses to record — not a wholesale copy of your
repository. The `/tf` flow shows you the exact payload before it sends.

**Who can see my documents?**
By default, you. Sharing into the organization (Library → Shares) is an explicit
action; that's what makes a document team-visible. Metrics are scoped to personal or
organization views.

---

Still stuck? Open Settings → Connect Agent to re-check your credential, or reach out
to the Taskforce team.
