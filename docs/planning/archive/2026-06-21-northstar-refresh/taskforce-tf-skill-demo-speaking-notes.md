> ⚠️ **ARCHIVED 2026-06-21 — historical; NOT current product direction.**
> Superseded by [`../../taskforce-northstar.md`](../../taskforce-northstar.md). Retained for reference only. Future agents: do not treat this as current guidance.

# `/tf` demo — speaking notes

Last updated: 2026-05-26

Essentials-only speaking notes for the Stripe double-spend recording. Full script with copy-paste blocks, fallbacks, and reset flow lives in [taskforce-tf-skill-demo-script.md](taskforce-tf-skill-demo-script.md).

---

## Beat 1 — Positioning + setup
- Coding agents are powerful, but they forget what your team already learned
- Taskforce = continual-learning memory layer for coding agents — captures useful work, retrieves it next time any agent hits something similar
- Here: Claude Code = harness, Opus = model, Taskforce = memory layer
- Setup: customers double-charged on Stripe plan upgrade — webhook retried, fulfilled twice. Before digging in, ask Taskforce if we've seen this before

## Beat 2 — Invoke `/tf`
*(type the `/tf` prompt into Claude Code)*
- `/tf` is a skill that invokes Taskforce discovery
- In Claude Code it runs as a skill; in Codex/Cursor/anything MCP, same flow runs through Taskforce's MCP server

## Beat 2b — Candidate file
*(point at the grep lines)*
- Claude hands Taskforce the prompt plus a quick scan of what part of the repo we're touching
- Taskforce surfaces what we've already learned about it

## Beat 3 — Payload
*(pause on payload)*
- Sends prompt + context: working dir, candidate files Claude just found, git branch
- No code body, no chat history

## Beat 3b — Profile selected
- Taskforce selected the Jensen profile — billing reliability
- A profile isn't a separate agent; it's reusable operating context — routing triggers, linked memory, prior decisions, code touchpoints — usable by Claude, Codex, Cursor, Composer
- Scoring engine ranks each candidate by triggers + linked memory + repo context, picks top one above medium

## Beat 3c — Profile world
*(tab to `agents` index)*
- Jensen is one of these — every profile is operating context the team's built up
- Create by hand, or Taskforce auto-suggests new ones as work is stored and ranked
- You stay in control to accept, edit, or kill. Jensen was promoted because billing-reliability work kept coming back
- *(tab back to Claude Code)*

## Beat 4 — Matches
*(click first URL, browser opens to incident anchor)*
- Two matches — first is the incident write-up from April, exact same root cause, webhook fired twice on retry. Second is the regression test we wrote right after
- Both got stored in Taskforce at the time, linked to Jensen, back the moment we hit it again
- That's the loop — work we've already done, ready when we need it
- *(over browser)* Written months ago, by me and Codex. Without Taskforce I'd re-derive or never find it
- *(Cmd-Tab back)*

## Beat 5 — Claude does the work
*(over streaming edit)*
- Opus has the prior decision in context: WAL check belongs at the route boundary, before fulfillment
- Without that memory, a model might add idempotency inside the handler — fixes the symptom but breaks the architectural invariant
- The fix is six lines

## Beat 6 — Test passes
*(over Claude's pytest green)*
- There's the regression test we surfaced from Taskforce — passing
- Was failing before the fix; dedup at the route boundary short-circuits the second delivery before fulfillment

## Beat 6b — Confirmation gate
*(type `yes`)*
- Quick confirmation — Taskforce doesn't record this as a win until I say the fix actually solved the problem. Yes.

## Beat 7 — Referenced-by
- Link goes both ways — this session is now in each document's "Referenced by" list, and on Jensen's invocation history
- Over time, docs referenced most surface as the team's most-trusted memory

## Beat 8 — Jensen's profile
*(Cmd-Tab to Jensen, scroll to Recent Invocations)*
- Here's Jensen — the profile we routed through earlier
- Top row in Recent Invocations is the session we just finished, written seconds ago
- Every time Jensen handles a billing problem it shows up here, linked memory gets stronger
- Profile compounds — same way a teammate gets sharper at billing the more tickets they touch
- *(Cmd-Tab back to terminal)*

## Beat 9 — Session metrics
*(click savings link)*
- The receipt. Fifty thousand tokens, twenty-five cents on Opus 4.7 — net of context Taskforce injected
- Two documents Jensen consulted, what we'd have spent re-deriving, what Taskforce actually shipped
- Mechanical, no agent self-report

## Beat 10 — Aggregate + close
*(click Overview / metrics tab)*
- Zoomed out — Jensen was one profile, one session. This is the team
- Every session that pulled from Taskforce shows up here, savings compound, memory keeps getting stronger
- More work flows through Taskforce, more every future session benefits
- That's Taskforce working
- *(hold ~3s, stop)*
