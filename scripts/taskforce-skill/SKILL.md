---
name: tf
description: Explicit, visible Taskforce flow — discover prior work, do the task, record consultation, report savings.
---

# /tf — Taskforce in the foreground

You were invoked because the user typed `/tf` followed by a task description. Your job is to run the Taskforce flow **visibly** — every step the user sees should make it obvious that Taskforce is in the loop, distinct from your own reasoning.

There are three wrapper scripts at `~/.claude/skills/tf/`:

1. `tf-discover.sh` — POSTs `/v2/taskforce/session/start`, returns matched specialist + matched documents (with 3-line previews and full anchor content).
2. `tf-reference.sh` — POSTs `/v2/taskforce/reference`, appends a "Referenced by:" row to the consulted documents.
3. `tf-savings.sh` — GETs `/v2/taskforce/session-savings`, returns the net tokens / USD this session saved.

All three return a single JSON envelope on stdout. They always exit 0; check `.ok` and degrade gracefully.

## Required output sequence

You MUST execute the beats in this exact order. The skill is load-bearing for a recorded demo — do not skip, reorder, or summarize.

### Beat 1 — Announce + show payload

Before calling anything, print:

```
🔎 Checking Taskforce for related prior work…

📨 Sending to Taskforce:
```

Then a fenced ` ```json ` block with the literal payload you are about to send: `prompt`, `cwd`, `files`, `git_branch`.

To populate `files` honestly (so the preview matches what the script actually sends), run this first with the Bash tool and use its output:

```bash
git diff --name-only --relative HEAD~1 HEAD 2>/dev/null \
  | grep -vE '(^|/)(tests?|migrations?|alembic)/' \
  | head -5
```

If that returns nothing (not a git repo, or no recent commits), render `files` as `[]`. The discover script applies the same heuristic internally as a fallback, so the rendered payload mirrors the actual HTTP body.

### Beat 2 — Call discover

Run via the Bash tool:

```bash
~/.claude/skills/tf/tf-discover.sh \
  --prompt "<the user's task description, verbatim>" \
  --cwd "$PWD" \
  --files "<comma-separated paths or empty>" \
  --git-branch "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
```

Parse the JSON result. If `.ok == false`:
- `reason == "no_token"` → print `⚠️ Taskforce not connected — set up at https://www.taskforce.tools, then re-run /tf. Continuing without prior work.` and proceed to do the task normally without further /tf beats.
- Any other failure → print `⚠️ Taskforce unavailable (<reason>). Continuing without prior work.` and proceed normally.

### Beat 3 — Render the matched specialist (if any)

If `.matched_specialist` is non-null, print it FIRST, before listing documents:

```
✓ Routed to <name> — <role>
  Confidence: <band> (<confidence>)
  Why: <reasons joined with " · ">
  [→ View specialist profile](<href>)
```

If `.matched_specialist` is null, skip this beat silently (no banner, no apology).

### Beat 4 — Render the document matches with 3-line previews

If `.matches` is empty, print `No related prior work in Taskforce yet — proceeding from scratch.` and skip ahead to Beat 5.

Otherwise, for each match print a numbered card:

```
N. **<title>** — confidence: <confidence_band> (<score, 2 decimals>)
   [→ Open at <matched_anchor_id>](<href>)
   Matched on: <match_reasons joined with ", ">

<anchor_preview as-is — already prefixed with `> `>
```

Render exactly `.matches.length` cards. Do not paraphrase the previews; emit them verbatim.

### Beat 5 — Do the work (your own reasoning, silently using the injected anchors)

Now read each `match.anchor_full` as additional context for your reasoning. **Do not echo `anchor_full` to the user** — that's invisible context. The 3-line preview from Beat 4 is what they see; the full anchor is for you.

Tackle the user's task normally — read code, propose a fix, make edits, run tests. Reference the prior decision in your reasoning when it applies ("Based on the prior decision in *<title>* (<anchor_id>), …") so the viewer sees the context shaped the work.

### Beat 6 — Record the consultation

When the work is done (tests pass, edit applied, or you've otherwise reached a stopping point), call:

```bash
~/.claude/skills/tf/tf-reference.sh \
  --session-id "<session_id from discover>" \
  --document-ids "<comma-separated document_ids of the matches you actually used>" \
  --user-prompt "<the user's original task description>"
```

If you consulted all matches (the usual case), pass all their ids. If you skipped one because it was off-topic, omit it.

### Beat 7 — Render the reference confirmations

Print, before any savings line:

```
Recording this session in the referenced docs…
```

Then one line per `updated_document_ids` entry. You'll need to look up the title from the discover results:

```
✓ <title> — added Referenced by entry
```

If the matched specialist was non-null, also print:

```
✓ <specialist name> — added invocation
```

(The specialist invocation is recorded server-side by the matched_specialist routing on discover; this line is for the user's benefit.)

If `.skipped_document_ids` is non-empty, print `(skipped N inaccessible doc(s))` once at the end.

### Beat 8 — Fetch + render savings

Call:

```bash
~/.claude/skills/tf/tf-savings.sh --session-id "<session_id>"
```

Then print, as the **final** line of your response:

```
Finished. [Taskforce saved you <net_saved_tokens> tokens on <model_display><optional effort suffix> (~$<usd_saved>)](<metrics_url>)
```

Use `model_display` from the `tf-savings.sh` JSON response. If `effort_label` is non-empty, append ` <effort_label> effort`; if it is empty, omit the effort suffix entirely. Format `net_saved_tokens` with comma thousands separators (e.g. `28,432`). Format `usd_saved` to 2 decimals (e.g. `0.38`). The whole sentence after `Finished.` is one markdown link, so the user can click it to open the metrics page filtered to this session.

`tf-savings.sh` reads `CLAUDE_MODEL` from the running Claude Code environment and passes it as `pricing_model_id`; when unset it falls back to `claude-opus-4-7`. It also reads `CLAUDE_EFFORT` when present for display only. Do not hardcode `Opus 4.7 xhigh effort`; render the values returned by the script so the USD math and model label stay aligned.

## Failure modes — graceful degradation

| Scenario | Behavior |
|---|---|
| `tf-discover.sh` returns `ok:false` | Print one-line warning, skip Beats 3/4/6/7/8, do the work normally |
| `.matches == []` | Skip Beats 4/6/7/8 (no docs to reference / record savings against), do the work normally |
| `.matched_specialist == null` | Skip Beat 3, keep all other beats |
| `tf-reference.sh` returns `ok:false` | Print `⚠️ Couldn't record reference (<reason>).` and still attempt Beat 8 |
| `tf-savings.sh` returns `ok:false` | Print `Finished.` with no savings line |

## Ordering rules — non-negotiable

- **Do not** call `tf-reference.sh` before the work is done. The user must see the edits + test pass before the "Referenced by" banner.
- **Do not** call `tf-savings.sh` before `tf-reference.sh`. The savings number is computed from consultation events, but the order also matters for the demo recording flow.
- **Do not** call `tf-discover.sh` more than once per `/tf` invocation. One discover → one session_id → one reference call → one savings call.
- **Do not** render `match.anchor_full` to the user. That content is for your reasoning only — the user sees the 3-line preview.
