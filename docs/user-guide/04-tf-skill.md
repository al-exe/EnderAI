---
title: The /tf flow (Claude Code)
slug: /docs/tf-flow
order: 4
audience: developer
---

# The `/tf` flow in Claude Code

The instruction-block setup makes capture automatic and quiet. `/tf` is the
opposite: a **visible, narrated** Taskforce pass you trigger on demand. Use it when
you want to *see* Taskforce in the loop — and it's the recommended way to run a
single task end-to-end through the reuse loop.

```
/tf <describe your task>
```

Example: `/tf the Stripe webhook is double-charging customers on retries`

---

## What you'll see, step by step

`/tf` runs a fixed sequence so every beat is legible:

1. **🔎 Candidate files** — it greps your repo for 1–2 high-signal files from your
   prompt and shows them, then prints the exact JSON payload it's about to send to
   Taskforce. No surprises about what leaves your machine.

2. **🟪 Discover** — it calls Taskforce, which scores your prior work against the
   request.

3. **🧑‍💻 Profile (if any)** — if a profile matches, it's brought in first, with the
   confidence band and the reasons it matched, and a link to view it.

4. **📖 Document matches** — each matched document as a numbered card: title,
   confidence, what it matched on, a 3-line preview, and a link to open it at the
   exact anchor. (The full anchor content is loaded silently into the agent's
   context — you see the preview; the agent reads the evidence.)

5. **Do the work** — Claude reads the prior decisions and tackles your task,
   referencing the prior document where it applies so you can see the context shaped
   the work.

6. **Confirmation gate** — before recording anything, it recaps what changed and
   what was verified, then asks **"Did this resolve the issue?"** and *waits*.
   - **Yes** → it records the consultation and shows savings.
   - **No / not yet** → it stays in "consulted-only" mode: the matches helped this
     session, but nothing is written back and nothing is counted as resolved. You
     keep iterating.

7. **✍️ Write-back** — on a yes, it appends a "Referenced by" row to each document
   you actually used (and an invocation to the profile), printed one bullet per
   document so you see each write happen.

8. **💰 Savings** — the final line: the net tokens and dollars this session saved,
   as a link to the Metrics page filtered to this session.

---

## Why the confirmation gate matters

The gate is the one thing standing between Taskforce and a **false-positive save**.
A "Referenced by" row is evidence that a document was *actually useful* — so `/tf`
never writes one until you confirm the fix landed. This keeps your reuse numbers
honest and your Library free of noise. If you're still iterating, just say so; the
matches stay in context and nothing gets recorded.

---

## `/tf` vs. the automatic instruction block

| | Automatic block | `/tf` |
|---|---|---|
| How it runs | Agent calls the tools on its own | You invoke it explicitly |
| Visibility | Quiet, in the background | Every beat printed |
| Confirmation | — | Asks before writing back |
| Best for | Day-to-day flow | A task you want to run — or show — through the loop deliberately |

You can use both. Many people leave the automatic block on for everyday work and
reach for `/tf` when they want the narrated pass (or a demo).

If Taskforce isn't connected, `/tf` tells you so and continues the task normally —
it degrades gracefully and never blocks your work.

Next: **[Working in the web app →](05-web-app.md)**
