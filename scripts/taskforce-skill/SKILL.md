---
name: tf
description: Explicit, visible Taskforce flow — discover prior work, do the task, record consultation, report savings.
---

# /tf — Taskforce in the foreground

You were invoked because the user typed `/tf` followed by a task description. Your job is to run the Taskforce flow **visibly** — every step the user sees should make it obvious that Taskforce is in the loop, distinct from your own reasoning.

There are five wrapper scripts in this skill's directory — `~/.claude/skills/tf/` (Claude Code), `~/.cursor/skills-cursor/tf/` (Cursor), or `~/.codex/skills/tf/` (Codex). The skill and scripts are byte-identical across harnesses; only the install location differs.

1. `tf-discover.sh` — POSTs `/v2/taskforce/session/start`, returns matched specialist + matched documents (with 3-line previews and full anchor content).
2. `tf-fleet.sh` — GETs `/v2/taskforce/fleet` + the active doc of each live sibling, returns what your **fleet-mates just figured out** (the knowledge bus). Read-only.
3. `tf-reference.sh` — POSTs `/v2/taskforce/reference`, appends a "Referenced by:" row to the consulted documents.
4. `tf-capture.sh` — POSTs `/v2/taskforce/observe` with structured fields, writing a fresh **decision** straight into the Library this turn (no waiting for the passive summarizer).
5. `tf-savings.sh` — GETs `/v2/taskforce/session-savings`, returns the net tokens / USD this session saved.

All five return a single JSON envelope on stdout. They always exit 0; check `.ok` and degrade gracefully.

## Beyond the demo flow — the live Taskforce surface

The `/tf` beats below cover the **foreground demo** (discover → work → reference → savings). Beyond it, Taskforce runs a **passive telemetry + Sessions layer** driven by the shell hooks your harness installed (`taskforce-hooks` for Claude Code, `taskforce-codex-hooks` for Codex, `taskforce-cursor-hooks` for Cursor) — **not** by anything you invoke. Those hooks call home on every prompt/tool-use, so an agent never sees them fire except for the `─── Related prior work ───` preamble the discover hook injects.

**This means a cold-start agent has no pointer to the rest of the surface. Use this section as that pointer.** All endpoints are under `${ENDERAI_BACKEND_URL:-https://enderai-backend.onrender.com}/api/v1/v2/taskforce/` and authenticate with `Authorization: Bearer $(cat ~/.taskforce_mcp_token)` (the token path is shared across all three harnesses).

### Seeing the rest of your Sessions roster (the common ask — a standing reflex, not just a /tf step)

This is an **always-on reflex**, not something gated behind `/tf`. Whenever the user asks *"what is the other agent doing"* / *"what are the other agents working on"* / *"get/pull the sessions roster"* / *"pull the shared context"* / *"who else is running"* — in any session — pull the roster **yourself, immediately, without asking first**.

They do **not** mean `/discover` (that's topical retrieval of *your own* docs and will echo your own recent prompts back at you). They mean the **roster**:

```bash
tok="$(tr -d '\r\n' < ~/.taskforce_mcp_token)"
curl -sS --max-time 20 -H "Authorization: Bearer ${tok}" \
  "https://enderai-backend.onrender.com/api/v1/v2/taskforce/fleet"
```

`GET /fleet` returns `{ fleet_sessions: [{ name, agents: [...] }], unassigned: [...] }`, each agent carrying its live `title`, `repo`, `branch`, `summary_markdown`, `status`, `minutes_ago`/`last_seen_at`, `specialist_slug`, and `model_id`. **This is the literal "what is every sibling agent doing right now" call.** Report the live agents first — non-`History` session, `status: running`, low `minutes_ago` — and label `idle`/`History`-group entries as stale rather than presenting them as current. Drill deeper with `GET /session-log?session_id=…` (discover→match history) and `GET /session-activity?session_id=…` (per-turn timeline).

### Full endpoint map

| Group | Endpoints | Purpose |
|---|---|---|
| **Discover / work** (this skill) | `POST /discover`, `POST /session/start`, `POST /reference`, `GET /session-savings` | The `/tf` demo flow below. |
| **Telemetry** (hooks, auto) | `POST /session/heartbeat`, `POST /observe`, `GET /active-sessions` | Presence + tool-use capture → writes `V2Document`s. You never call these by hand. |
| **Sessions roster** | `GET /fleet`, `POST /fleet`, `PATCH /fleet/{id}`, `DELETE /fleet/{id}`, `PATCH /session/{session_id}` | Group/rename/assign live sessions. `GET /fleet` is read-only and safe. |
| **Inspect a session** | `GET /session-log`, `GET /session-activity` | What a given agent discovered/reused and its per-turn activity. |
| **ROI ledger** | `GET /ledger`, `GET /ledger/{session_id}`, `GET /ledger/{session_id}/raw-transcript`, `GET /documents/{id}/sessions` | Per-session savings rollup + transcript. |

### The fleet knowledge bus — what is and isn't wired

`/tf` now runs a **client-side knowledge bus** (Beat 4b via `tf-fleet.sh`): on each invocation it reads `/fleet`, finds your live fleet-mates, and pulls their *active document* so a sibling's fresh decision lands in your session — "pull from another agent," made real. Be precise about its shape so you don't over-promise:

- It is a **pull on each `/tf` turn**, not a server **push**. Latency is one discover cycle: a fleet-mate's decision reaches you the next time you run `/tf`, not the instant they make it. There is still no channel that injects context into an *already-mid-turn* agent.
- It is scoped to your **own fleet session** (or same `cwd`), and only surfaces siblings that have an `active_document_id` and were active recently. `/discover` topical matching is unchanged and independent.
- The fuller server-side **push / directive channel** (`docs/planning/taskforce-fleet-mission-control.md` + `taskforce-fleet-knowledge-bus.md`) — broadcast steering, pause/stop, true realtime — is still **designed, not shipped**. Don't claim it.

## Required output sequence

You MUST execute the beats in this exact order. The skill is load-bearing for a recorded demo — do not skip, reorder, or summarize.

### Beat 1 — Find candidate files, then announce + show payload

Before calling the discover script, do two things in order.

**1a. Discover candidate files via Grep.**

Pick 1–2 high-signal nouns from the user's prompt (e.g. "Stripe webhook double-charging" → `stripe`, `webhook`; "JWT refresh failing" → `jwt`, `refresh`). Run a single Grep scoped to likely source dirs, excluding tests, migrations, and build artifacts:

```bash
grep -rln -E "(<kw1>.*<kw2>|<kw2>.*<kw1>)" \
  --include="*.py" --include="*.ts" --include="*.tsx" --include="*.js" \
  --exclude-dir=.venv --exclude-dir=node_modules --exclude-dir=.git \
  --exclude-dir=tests --exclude-dir=migrations --exclude-dir=alembic \
  app/ src/ backend/ 2>/dev/null | head -5
```

Print one line per candidate you'll send, using 🔎:

```
🔎 Found candidate file: app/api/routes/billing.py
```

**Cap at 2 files.** When grep returns more than 2, rank by how "handler-shaped" the path is and keep the top 2:
1. Files under `routes/`, `handlers/`, `api/`, `controllers/` (the request entry points)
2. Files under `services/`, `core/`, or whose filename matches a prompt noun (e.g. `stripe_billing.py` for a "stripe" prompt)
3. Everything else (drop)

Extra files dilute the scorer's per-doc files-match ratio (each match doc is rewarded for how many of the sent files appear in *its* corpus, so unrelated files drag scores down). Two well-chosen paths is the sweet spot.

If zero come back, refine the grep once with different terms; if still zero, print `🔎 No obvious candidates from prompt — Sending without file hints.` and proceed with `files: []`.

Do **not** Read the file contents here. The paths are scoring signal for Taskforce; full content comes after matches return (Beat 5).

**1b. Announce + show payload.**

Print:

```
🟪 Checking Taskforce for related prior work…

📬 Sending to Taskforce:
```

Then a fenced ` ```json ` block with the literal payload you are about to send: `prompt`, `cwd`, the `files` from step 1a, `git_branch`, and `client`. The `client` value is the current harness (`claude-code` for `~/.claude`, `codex` for `~/.codex`, `cursor` for `~/.cursor`), unless `TASKFORCE_CLIENT` overrides it. The payload must match what `tf-discover.sh` sends in Beat 2 — no hidden differences.

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

### Beat 3 — Render the matched profile (if any)

If `.matched_specialist` is non-null, print it FIRST, before listing documents. A "profile" is reusable operating context (routing triggers, linked memory, code touchpoints) that any harness/model can adopt — not an autonomous agent.

```
🧑‍💻 Bringing in profile: <name> — <role>
  Confidence: <band> (<confidence>)
  Why: <reasons joined with " · ">
  [→ View profile](<href>)
```

If `.matched_specialist` is null, skip this beat silently (no banner, no apology).

### Beat 4 — Render the document matches with 3-line previews

If `.matches` is empty, print `No related prior work in Taskforce yet — Proceeding from scratch.` and skip ahead to Beat 5.

Otherwise, first print a header line attributing the documents to whoever did the bringing — the matched profile if there was one, otherwise Taskforce itself. Pluralize `document` based on count.

- If `.matched_specialist` is non-null:

  ```
  📖 <matched_specialist.name> is bringing in <N> related document<s>:
  ```

- If `.matched_specialist` is null:

  ```
  📖 Taskforce is bringing in <N> related document<s>:
  ```

Then, for each match print a numbered card:

```
N. **<title>** — Confidence: <confidence_band> (<score, 2 decimals>)
   [→ Open at <matched_anchor_id>](<href>)
   Matched on: <match_reasons joined with ", ">

<anchor_preview as-is — already prefixed with `> `>
```

Render exactly `.matches.length` cards. Do not paraphrase the previews; emit them verbatim.

### Beat 4b — Pull live context from your fleet (the knowledge bus)

After the document matches, check whether a **fleet-mate** just figured out something relevant — the "pull from another agent" beat. Run:

```bash
~/.claude/skills/tf/tf-fleet.sh \
  --exclude-session "<session_id from discover>" \
  --cwd "$PWD"
```

Parse the result. If `.ok == false` **or** `.siblings == []`, **skip this beat silently** — no banner, no apology (a solo session is the common case).

If `.siblings` is non-empty, print a header, pluralizing on count:

```
🛰 From your fleet — <N> teammate<s> working nearby:
```

Then one card per sibling (render exactly `.siblings.length`):

```
N. **<display_name>** (<agent_kind>)<profile suffix> — active <minutes_ago>m ago
   On: [<title>](<href>)
<preview as-is — already prefixed with `> `>
```

`<profile suffix>` is ` · profile <specialist_slug>` when `specialist_slug` is non-null, else empty.

Then read each `sibling.full` as additional reasoning context (like the document anchors — **do not echo `full`**; the 3-line preview is what the user sees). When a fleet-mate's decision applies, build on it explicitly in Beat 5 ("a teammate just landed the route-boundary decision in this same repo — building on it rather than re-deriving"). This is a pull on *this* `/tf` turn, not a realtime push — don't narrate it as live telepathy.

### Beat 5 — Do the work (your own reasoning, silently using the injected anchors)

Now read each `match.anchor_full` as additional context for your reasoning. **Do not echo `anchor_full` to the user** — that's invisible context. The 3-line preview from Beat 4 is what they see; the full anchor is for you.

Tackle the user's task normally — read code, propose a fix, make edits, run tests. Reference the prior decision in your reasoning when it applies ("Based on the prior decision in *<title>* (<anchor_id>), …") so the viewer sees the context shaped the work.

### Beat 5b — Confirm with the user before recording

After your edits land and tests pass (or you've otherwise reached a stopping point), print a short recap and ask one yes/no question:

```
Recap of this session:
  • Applied: <one-line summary of what changed and where>
  • Verified: <test name(s)>, passed

Did this resolve the issue?
```

Then **wait** for the user's response. Do NOT call `tf-reference.sh` or `tf-savings.sh` until the user replies.

- If the user replies with any affirmation (yes, y, yep, looks good, ship it, etc.): proceed to Beat 6.
- If the user replies with any negation (no, n, not yet, undo, etc.) or asks for further changes:
  - Print: `Got it — leaving Taskforce in "consulted-only" mode. The matches stayed in your context for this session; no reference rows added, no session recorded as resolved.`
  - Do NOT call `tf-reference.sh` or `tf-savings.sh`.
  - Continue the conversation normally — the user wants to keep iterating.

If the reply is ambiguous (a follow-up question, not a clear yes/no), ask once more: `Just to confirm — is this issue resolved, or do you want to keep iterating?`

This gate is the only thing standing between Taskforce and a false-positive save. Don't skip it, don't pre-fire references, don't print savings before the user agrees the fix landed.

### Beat 6 — Record the consultation (only after Beat 5b confirms)

Once the user has confirmed in Beat 5b that the fix resolved the issue, call:

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
✍️ Writing this session back to the referenced documents…
```

Then one indented bullet per `updated_document_ids` entry. Render the title as a markdown link to the document page — construct the URL as `<frontend_host>/v2/library/<doc_id>` (`frontend_host` is on the discover response; `doc_id` matches the entry in `updated_document_ids`):

```
  • [<title>](<frontend_host>/v2/library/<doc_id>) — Added "Referenced by" entry
```

If the matched specialist was non-null, also print (indented to match; link the name to the profile page using `matched_specialist.href` from discover):

```
  • Profile [<specialist name>](<matched_specialist.href>) — Added invocation
```

Do **not** collapse these into a summary like "Recorded consultation in N documents." The per-document bullets are load-bearing for the demo — viewer sees each write happen, which is the only visible proof of the back-link. Keep ✍️ on the header line only; child lines stay clean bullets with linked titles.

(The specialist invocation is recorded server-side by the matched_specialist routing on discover; this line is for the user's benefit.)

If `.skipped_document_ids` is non-empty, print `(skipped N inaccessible doc(s))` once at the end.

### Beat 7b — Capture what you figured out (only when there's something new)

Sometimes the work produced a **new** decision or gotcha that wasn't already in the consulted documents — the kind of thing the next teammate would want, and exactly what the bus in Beat 4b surfaces. When that's the case (and only then), write it into the Library **now** rather than waiting for the passive Stop-hook summarizer:

```bash
~/.claude/skills/tf/tf-capture.sh \
  --session-id "<session_id from discover>" \
  --decision "<the reusable decision, one sentence>" \
  --summary-point "<what changed and where, one line>" \
  --files "<comma-separated files you touched>" \
  --outcome shipped \
  --specialist-slug "<matched_specialist.slug, if one routed>" \
  --branch "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
```

Pass `--decision` more than once for multiple findings. **Skip this beat entirely** when the work merely applied already-documented decisions — don't manufacture a capture just to have one. (This is gated by Beat 5b like the reference call: only run it after the user confirmed the fix landed.)

On `.ok == true` and `.action != "skipped"`, print one bullet beneath the Beat 7 writes — label it with the gist of your `--decision` since the response carries the link, not a title:

```
  • [Captured: <one-line gist of the decision>](<href>) — new decision saved to the Library
```

Use `.href` from the response. This is the document a fleet-mate's `tf-fleet.sh` will surface next — capture here closes the loop the bus opens.

### Beat 8 — Fetch + render savings

Call:

```bash
~/.claude/skills/tf/tf-savings.sh --session-id "<session_id>"
```

Then print, as the **final** line of your response:

```
💰 [Taskforce saved you <net_saved_tokens> tokens on <model_display><optional effort suffix> (~$<usd_saved>)](<metrics_url>)
```

Use `model_display` from the `tf-savings.sh` JSON response. If `effort_label` is non-empty, append ` <effort_label> effort`; if it is empty, omit the effort suffix entirely. Format `net_saved_tokens` with comma thousands separators (e.g. `28,432`). Format `usd_saved` to 2 decimals (e.g. `0.38`). The whole sentence after `💰 ` is one markdown link, so the user can click it to open the metrics page filtered to this session.

`tf-savings.sh` reads `CLAUDE_MODEL` from the running Claude Code environment and passes it as `pricing_model_id`; when unset it falls back to `claude-opus-4-7`. It also reads `CLAUDE_EFFORT` when present for display only. Do not hardcode `Opus 4.7 xhigh effort`; render the values returned by the script so the USD math and model label stay aligned.

## Failure modes — graceful degradation

| Scenario | Behavior |
|---|---|
| `tf-discover.sh` returns `ok:false` | Print one-line warning, skip Beats 3/4/4b/5b/6/7/7b/8, do the work normally |
| `.matches == []` | Skip Beats 4/5b/6/7/7b/8 (nothing to confirm, reference, or score). Still run Beat 4b — fleet context is independent of your own matches — then do the work |
| `.matched_specialist == null` | Skip Beat 3, keep all other beats |
| `tf-fleet.sh` returns `ok:false` **or** `.siblings == []` | Skip Beat 4b silently (no banner). The common solo-session case |
| User says no (or anything non-affirmative) at Beat 5b | Skip Beats 6/7/7b/8 entirely; print the "consulted-only mode" line; keep helping the user |
| `tf-reference.sh` returns `ok:false` (after Beat 5b yes) | Print `⚠️ Couldn't record reference (<reason>).` and still attempt Beats 7b/8 |
| Nothing new to record at Beat 7b | Skip Beat 7b silently — applying existing decisions is the norm, not every session captures |
| `tf-capture.sh` returns `ok:false` or `.action == "skipped"` | Print nothing for the capture bullet; proceed to Beat 8 |
| `tf-savings.sh` returns `ok:false` (after Beat 5b yes) | Print `💰 (Savings unavailable)` with no link, then stop |

## Ordering rules — non-negotiable

- **Do not** call `tf-reference.sh` before the user explicitly confirms at Beat 5b. The "Referenced by" rows are evidence the consultation was useful; pre-firing them lies about that.
- **Do not** call `tf-savings.sh` before `tf-reference.sh`. The savings number is computed from consultation events, but the order also matters for the demo recording flow.
- **Do not** call `tf-discover.sh` more than once per `/tf` invocation. One discover → one session_id → one Beat 5b confirmation → one reference call → one savings call.
- **Do not** call `tf-capture.sh` before the user confirms at Beat 5b, and only when there's a genuinely new decision (it writes a "shipped" decision into the shared Library — fabricating one pollutes the next teammate's bus).
- **Do not** call `tf-fleet.sh` more than once per `/tf` invocation, and always pass `--exclude-session` so you never surface your own session back to yourself.
- **Do not** render `match.anchor_full` or `sibling.full` to the user. That content is for your reasoning only — the user sees the 3-line preview.
- **Do not** assume yes at Beat 5b. Wait for an explicit reply; "I think that's it" or "looks reasonable" without a yes/no should trigger the clarification prompt, not auto-proceed.
