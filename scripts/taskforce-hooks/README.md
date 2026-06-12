# Taskforce Claude Code hooks (TF-174 epic)

Drop-in hooks that wire the **Taskforce** workflow into Claude Code without the agent having to call any tool explicitly. TF-174 epic.

## What ships

- **UserPromptSubmit** (TF-176) — on every prompt, asks the backend for related prior work and prepends a preamble.
- **Stop** (TF-178) — when a session ends, ships a redacted transcript digest to `/v2/taskforce/observe` with `kind: "final"`. The backend summarizes it via haiku and PATCHes the active document (or creates a fresh one).
- **PostToolUse** (TF-178) — after every tool call by default (`TASKFORCE_CHECKPOINT_EVERY=1`; raise it to checkpoint less often), ships a mid-session checkpoint to the same endpoint with `kind: "checkpoint"`.

## What it does

Every time you submit a prompt to Claude Code:

1. The hook asks the Taskforce backend (`POST /v2/taskforce/discover`) for the top 1–3 V2 documents related to your prompt.
2. If anything's relevant (above the score threshold), it prepends a short "Related prior work" preamble to the prompt so the agent has the context.
3. A one-line `[Taskforce] N related docs pulled · …` banner is written to stderr so you can see what was injected.
4. Each surfaced match records a `document.consulted` metrics event, so the dashboard's **Avoided Rediscovery** card (TF-177, behind feature flag) starts moving.

When there are no matches, the hook is silent — Claude Code sees your prompt unchanged.

When the session ends (Stop hook) or after each tool call (PostToolUse hook), the backend gets a digest of what happened. **The observe endpoint defaults to shadow mode** (`TASKFORCE_OBSERVE_SHADOW=1`): it records what *would* happen but doesn't touch any documents until someone flips the flag server-side. That's the §7.4 rollout safety net.

## Install

Requires: `bash`, `curl`, `jq`. Mac and Linux. Reads the Taskforce MCP token from `~/.enderai_mcp_token` (created by the Connect Agent flow at https://www.taskforce.tools).

```bash
curl -fsSL https://raw.githubusercontent.com/al-exe/EnderAI/main/scripts/taskforce-hooks/install.sh | bash
```

Or from a clone:

```bash
bash scripts/taskforce-hooks/install.sh
```

The installer is idempotent: re-running it leaves `~/.claude/hooks/taskforce-user-prompt-submit.sh` and `~/.claude/settings.json` in a consistent state.

Restart your Claude Code session for the hook to take effect.

## Verify

```bash
# Hook is registered:
jq '.hooks.UserPromptSubmit' ~/.claude/settings.json

# Token is reachable:
test -r ~/.enderai_mcp_token && echo "token ok" || echo "token missing"

# Recent activity:
tail -f ~/.claude/taskforce-discover.log
```

After a prompt that triggers a match you should see the banner in your Claude Code UI and a `POST /v2/taskforce/discover → 200` line in the log.

## Configuration

| Env var | Default | What it does |
|---|---|---|
| `ENDERAI_BACKEND_URL` | `https://enderai-backend.onrender.com` | Backend base URL. Override for local dev. |
| `TASKFORCE_HOOKS_DISABLED` | `0` | Set to `1` to make all Taskforce hooks exit 0 after dependency checks. Useful when invoking `/tf` manually so hooks and the skill do not both emit context. |
| `TASKFORCE_PREAMBLE_BUDGET` | `1500` | Approximate token budget for the injected preamble. Higher = more context, more prompt cost. |
| `TASKFORCE_CHECKPOINT_EVERY` | `1` | PostToolUse checkpoints every Nth tool call. `1` captures everything; raise it to reduce backend/summarizer load. |
| `TASKFORCE_HOOK_DEBUG` | `0` | Mirror logs to stderr (helpful while iterating on the hook). |

## How it's safe

- **Never blocks the session.** All failure paths exit 0. The hook can be missing curl, missing jq, missing token, or hit a 500 — the user sees an unchanged prompt.
- **Best-effort secrets handling.** Only the prompt itself, cwd, and git branch ship to the backend. We don't read the transcript.
- **Silent on empty.** If discovery returns nothing, the hook writes nothing — no banner spam, no log noise.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No banner ever appears | Token missing or library empty | `cat ~/.enderai_mcp_token`; check the log; run a workflow that creates a doc first |
| Banner appears but prompt feels unchanged | Claude Code version doesn't yet inject UserPromptSubmit stdout into the prompt | Upgrade Claude Code |
| `[Taskforce] hook schema mismatch` (future) | Claude Code's UserPromptSubmit contract changed | Re-run the installer |

## Related: `/tf` slash command

The hooks bundle injects Taskforce context **silently** on every prompt. For the explicit, visible variant — useful for demos or one-off "show me prior work on X" moments — see [`scripts/taskforce-skill/`](../taskforce-skill/README.md) (TF-188). They coexist; for demos, export `TASKFORCE_HOOKS_DISABLED=1` so only the skill emits context.

## Plan + epic

- Plan: `~/dev/docs/claude-mcp-brainstorm.md` §2.4, §3.4, §3.5, §7.2
- Epic: TF-174
- Ticket: TF-176
