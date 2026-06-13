---
title: Quickstart — Connect your agent
slug: /docs/quickstart
order: 1
audience: developer
---

# Quickstart: connect your agent in 5 minutes

By the end of this page your AI coding agent will be able to **discover** prior
work before it starts a task and **capture** new work as it finishes — and you'll
see the first savings show up on your Metrics page.

You'll need:
- A Taskforce account ([www.taskforce.tools](https://www.taskforce.tools)) — new
  accounts start on the MAX tier.
- An MCP-capable AI client. **Claude Code** is the smoothest path; any MCP client
  works, and there's a CLI for clients that don't speak MCP.

---

## Step 1 — Get your token

1. Open **Settings → Connect Agent**.
2. Give the credential a label (e.g. `My laptop — Claude Code`) and click
   **Create**.
3. A token is shown **once**. Keep this page open for the next step.

> Your token is per-user and scoped to your account. It's the only secret your
> agent needs — there is no separate backend key.

---

## Step 2 — Connect Claude Code (recommended path)

On the Connect Agent page, copy the **"Connect Claude Code"** one-command snippet.
It saves your token locally and registers the hosted Taskforce MCP server in one
shot. Running it looks like this:

```bash
printf '%s\n' '<your-token>' > ~/.taskforce_mcp_token && chmod 600 ~/.taskforce_mcp_token && \
  claude mcp add --transport http taskforce https://enderai-mcp.onrender.com/mcp \
    --header "Authorization: Bearer $(cat ~/.taskforce_mcp_token)"
```

Then **restart Claude Code** so it reloads the MCP config, and verify:

```
taskforce_session_info
```

You should get back your session policy, auth model, and a confirmation that
you're ready to start work. That's it — you're connected.

### Using a different MCP client?

Any MCP client works. Point it at the hosted endpoint with your token as a bearer
header:

- **MCP URL:** `https://enderai-mcp.onrender.com/mcp`
- **Auth:** `Authorization: Bearer <your-token>`

The Connect Agent page generates a generic client config block you can paste into
Cursor, Codex, or a custom client.

### No MCP support? Use the CLI

For harnesses that don't speak MCP (a plain Anthropic SDK script, a browser
session, a custom pipeline), the same package ships `taskforce-cli`, which wraps
the identical endpoints with the same token:

```bash
taskforce-cli discover --prompt "fix metrics card" --cwd "$PWD" --pretty
```

---

## Step 3 — Tell your agent to use Taskforce

Capture and reuse happen when your agent calls the Taskforce tools at the right
moments. Add a short instruction block to your agent's core instruction file
(`AGENTS.md`, `CLAUDE.md`, or equivalent). The Connect Agent page generates this
for you; the essence is:

```markdown
## Taskforce
- At the start of meaningful, user-initiated work, call `taskforce_begin_document`.
  It scores existing documents against the request and either reuses + self-heals a
  strong match or creates a fresh one. Read the returned `match_reasons`,
  `candidate_summaries`, and `self_healed_fields` before continuing.
- As material progress develops, call `taskforce_update_document` (commands, files,
  decisions, changes, open questions, anchored Details sections).
- When the work completes or pauses, call `taskforce_finish_document` to write an
  Outcome section and close the active document.
```

> **Claude Code users:** you can also drive this *visibly and on demand* with the
> `/tf` command — see [The `/tf` flow](04-tf-skill.md). The instruction block above
> makes capture automatic; `/tf` makes it a foreground, narrated step.

---

## Step 4 (optional, Claude Code only) — turn on cost tracking

To get exact token/dollar savings on your Metrics page, install the usage-tracking
hook from the **"Claude Code cost tracking"** card on the Connect Agent page. It's a
single command that saves your token, writes a local hook, and records each turn's
real token usage. Nothing is downloaded — the hook script is written inline.

Without it, Taskforce still tracks reuse; the hook just makes the dollar figures
exact rather than modeled.

---

## You're done — now prove it

1. Ask your agent to do a real task.
2. Watch it call `taskforce_begin_document` (or run `/tf <task>` in Claude Code).
3. Open **Library** in the web app — your new document is there.
4. Do a *related* task later and watch the prior document get surfaced and reused.
5. Open **Metrics** to see the savings.

Next: **[How Taskforce works →](02-how-it-works.md)**
