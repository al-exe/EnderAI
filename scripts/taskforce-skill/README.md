# /tf — Taskforce slash command for Claude Code (TF-188)

A foreground, visible Taskforce flow for Claude Code. Where the [taskforce-hooks](../taskforce-hooks/README.md) bundle injects prior work *invisibly* on every prompt, `/tf` does the same thing *explicitly* — the user sees Taskforce surface matches, sees the specialist routing, watches the work happen, and sees the savings tally at the end. Built for demos, sales calls, and one-off "find me the prior thinking on X" moments.

## What it does

1. `/tf <task>` → POST `/v2/taskforce/session/start`
2. Skill prints the matched specialist (when one routes above the medium band) and the top documents with 3-line anchor previews + deep links to `taskforce.tools/v2/library/<id>#<anchor>`
3. Claude reads the full anchor content as context (invisibly), then does the task normally
4. On completion: POST `/v2/taskforce/reference` → each consulted doc gets a "Referenced by" row appended
5. Final line: a markdown link reporting `Taskforce saved you N tokens (~$X)` that opens the metrics page filtered to this session

## Install

Requires: `bash`, `curl`, `jq`. Mac and Linux. Reads the Taskforce MCP token from `~/.enderai_mcp_token` (created by the Connect Agent flow at https://www.taskforce.tools).

```bash
curl -fsSL https://raw.githubusercontent.com/al-exe/EnderAI/main/scripts/taskforce-skill/install.sh | bash
```

Or from a clone:

```bash
bash scripts/taskforce-skill/install.sh
```

Idempotent — re-running leaves `~/.claude/skills/tf/` consistent.

Restart your Claude Code session, then type `/tf` followed by your task.

## Configuration

| Env var | Default | What it does |
|---|---|---|
| `TASKFORCE_BACKEND_URL` (alias: `ENDERAI_BACKEND_URL`) | `https://enderai-backend.onrender.com` | Backend base URL. Override for local dev. |
| `TASKFORCE_FRONTEND_HOST` | `https://www.taskforce.tools` | Used to build deep links in the skill's rendered output. |

## How it interacts with the hooks bundle

The hooks (TF-176) inject context silently on **every** prompt — useful for steady-state use. The `/tf` skill is the **opt-in, visible** version — useful when you want to *show* Taskforce in the loop.

Recommended for demos: set `TASKFORCE_HOOKS_DISABLED=1` so only the skill emits Taskforce context (no double-injection). For day-to-day work the two coexist fine — the hooks are silent on no-match, and the skill is only invoked when you type `/tf`.

## Verify

```bash
ls ~/.claude/skills/tf
# SKILL.md  tf-discover.sh  tf-reference.sh  tf-savings.sh

# Token present:
test -r ~/.enderai_mcp_token && echo "token ok" || echo "token missing"

# Recent activity:
tail -f ~/.claude/taskforce-skill.log
```

## How it degrades

- **No token** → skill prints `⚠️ Taskforce not connected — set up at https://www.taskforce.tools…` and proceeds without prior work.
- **Backend down / 5xx** → skill prints `⚠️ Taskforce unavailable (http_5xx). Continuing without prior work.` and proceeds.
- **No matches** → skill prints `No related prior work in Taskforce yet — proceeding from scratch.` and proceeds.
- **No specialist matched** → skill silently skips the routing banner; document matches still render.

In every failure path the user gets a working session — Taskforce never blocks the work.

## Demo behavior

A few things are intentionally constrained for reproducible demo recordings (see `~/dev/docs/taskforce-demo-video-plan.md` §0):

- **Model pricing** follows `CLAUDE_MODEL` when Claude Code exposes it and falls back to `claude-opus-4-7` when unset. `CLAUDE_EFFORT` is display-only and may be empty.
- **3-line previews** of the matched anchor are rendered under each document card as `>`-quoted lines.

## Plan + epic

- Plan: `~/dev/docs/taskforce-demo-video-plan.md` §4 (beat-by-beat spec)
- Epic: TF-183 (/tf skill demo flow)
- Tickets: TF-188, TF-190
