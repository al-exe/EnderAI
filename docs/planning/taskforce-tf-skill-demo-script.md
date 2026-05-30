# `/tf` skill demo — Stripe double-spend recording script

Last updated: 2026-05-26

Literal "do this, say this, type this" script for tomorrow's recording. The video plan at [taskforce-demo-video-plan.md](taskforce-demo-video-plan.md) is the *why* — this is the *what*. Follow top to bottom.

> **Demo target:** Stripe webhook double-fulfillment fix on the `fix/stripe-webhook-double-fulfillment` branch. Recorded with the `/tf` skill in the foreground. ~2:55 video (13 beats — agents-index at Beat 3c, confirmation gate at Beat 6b, Jensen profile visit at Beat 8, session metrics at Beat 9, aggregate metrics closes at Beat 10).

---

## Pre-flight — 5 minutes before record

### A. Smoke-test the deployed stack

Run these from any terminal. Each should pass before you hit record.

```bash
# 1. Discover surfaces the two Stripe seed docs at medium band.
#    Two files in payload mirrors what /tf sends post-grep-discovery (PR #102):
#    Claude's Beat 1a grep on "stripe.*webhook" returns billing.py + stripe_billing.py
#    after the cap-at-2 + route/handler preference is applied.
TOKEN=$(cat ~/.enderai_mcp_token)
curl -s -X POST "https://enderai-backend.onrender.com/api/v1/v2/taskforce/discover?demo=true" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"prompt":"Stripe is double-charging some users on plan upgrades — looks like webhook retries are getting fulfilled twice. Can you fix it?","files":["app/api/routes/billing.py","app/core/stripe_billing.py"],"top_k":3,"min_score":0.3}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); [print(m['score'],m['confidence_band'],m['title']) for m in d['matches']]"
```

Expect at least:
```
0.34+ medium  Stripe webhook idempotency strategy
0.37+ medium  Stripe plan upgrade webhook retries — regression test pattern
```

If you get zero matches, the seed didn't fire for your account — open `https://www.taskforce.tools/v2/library?demo=true` in a browser once to trigger `ensure_v2_documents_demo_seed`, then re-run the curl.

```bash
# 2. Deep-link scroll works (TF-185)
open "https://www.taskforce.tools/v2/library/<doc_id>#incident-2026-04-11"
# Browser should land scrolled to the "Incident — 2026-04-11 double-charge" section, not the top.
# Use one of the document_ids returned by step 1.

# 3. Demo branch has the bug
cd /home/alexlee/dev/EnderAI
git fetch origin fix/stripe-webhook-double-fulfillment
git log origin/fix/stripe-webhook-double-fulfillment -1 --oneline
# Expect: 2c53b03 TF-193: Demo branch — Stripe WAL-after-fulfillment bug

# 4. /tf skill installed
ls ~/.claude/skills/tf
# Expect: SKILL.md  tf-discover.sh  tf-reference.sh  tf-savings.sh
```

### B. One-shot setup block (idempotent — safe to re-run)

Paste this whole block into a fresh shell. It sets every required env var, reuses an existing `fix/stripe-webhook-double-fulfillment` worktree if one exists (anywhere), creates one only if needed, cds into the backend dir, opens the file you'll edit, and launches Claude.

```bash
# --- env (idempotent: just re-exports) ---
export TASKFORCE_HOOKS_DISABLED=1   # kills the silent hook so /tf is the only Taskforce path
export TASKFORCE_DEMO=1              # /tf passes demo=true → TF-191 seed docs surface
export CLAUDE_MODEL=claude-opus-4-7  # savings line says "Opus 4.7"
export CLAUDE_EFFORT=xhigh           # savings line appends "xhigh effort"
export TASKFORCE_BACKEND_URL=https://enderai-backend.onrender.com

# --- worktree (idempotent: reuses any existing one on the demo branch) ---
TASKFORCE_REPO=/home/alexlee/dev/EnderAI
FIX_BRANCH=fix/stripe-webhook-double-fulfillment
DEFAULT_WORKTREE=/home/alexlee/dev/WORKTREE-stripe-fix

# Drop stale worktree refs (e.g. left over from the old taskforce-claude path).
# Safe — only removes entries whose on-disk path no longer exists.
git -C "$TASKFORCE_REPO" worktree prune

WORKTREE_PATH=$(git -C "$TASKFORCE_REPO" worktree list --porcelain | awk -v br="refs/heads/$FIX_BRANCH" '/^worktree / { wt = $2 } $1 == "branch" && $2 == br { print wt; exit }')

if [ -z "$WORKTREE_PATH" ]; then
    git -C "$TASKFORCE_REPO" worktree add "$DEFAULT_WORKTREE" "$FIX_BRANCH"
    WORKTREE_PATH="$DEFAULT_WORKTREE"
fi

cd "$WORKTREE_PATH/demo/full-stack-fastapi-template/backend"

# --- sanity print (should say fix/stripe-webhook-double-fulfillment) ---
echo "branch: $(git branch --show-current)"
echo "cwd:    $PWD"
env | grep -E "^(TASKFORCE_|CLAUDE_)" | sort

# --- launch Claude (no IDE — demo is browser left, terminal right) ---
claude
```

Inside Claude Code, optionally run `/effort xhigh` and `/model opus` to match the env (the skill reads both from env, so this is belt + suspenders). Close the welcome message and clear the input — ready for beat 2.

### C. Pre-warm `/tf` (mandatory)

The 2026-05-25 dry run showed the first `/tf` of a cold session can return `matched_specialist: null, matches: []` — an embedding/index timing artifact. The immediate retry returns the full result set. **Always burn one throwaway `/tf` before hitting record** so the real run lands clean.

Inside Claude Code, run:

```
/tf warm up the index please
```

Wait for the response (matches or no), then start your recording. Don't worry about the throwaway showing up in metrics — beat 9's savings link is scoped to a `session_id` that won't be created until the real `/tf`. (For a fully clean Jensen page across takes, the [After-each-take reset](#after-each-take--reset-for-another-take) block at the bottom of this doc nukes warm-up events too — important for beat 8, where Jensen's Recent Invocations is on camera.)

### D. Browser tabs (left to right)

1. `https://www.taskforce.tools/v2/library?demo=true` — you'll click into a match in beat 4
2. `https://www.taskforce.tools/v2/metrics` — you'll click the session-filtered link in beat 9
3. `https://www.taskforce.tools/v2/agents` — agents index for beat 3c's auto-suggestion vision cast (pre-load so the page is warm)
4. `https://www.taskforce.tools/v2/agents/jensen` — Jensen's profile, pre-warmed for beat 8's Recent Invocations reveal

### E. Recording window

- Terminal left (~60% width), browser right
- Font 18pt minimum so it reads on a phone
- Quit Slack, Discord, anything that can raise a toast
- Do Not Disturb on

---

## Beat-by-beat — target ~2:40

### Beat 1 — Positioning + setup (00:00 – 00:18)

**Say (positioning, ~10s):**
> "Coding agents are powerful, but they forget what your team already learned. Taskforce is a continual-learning memory layer for coding agents — it automatically captures useful work as stored context, and retrieves it the next time any agent hits a similar problem. Here, Claude Code is the harness, Opus is the model, and Taskforce is the memory layer."

**Say (task framing):**
> "So say I'm an engineer, and recently we had customers getting double-charged on Stripe for a plan upgrade — looks like the webhook retried and we fulfilled twice. Before I dig in, I'll ask Taskforce if we've seen this before."

**Do:** Cursor in the Claude Code prompt. (No IDE this take — browser left, terminal right.)

---

### Beat 2 — Invoke `/tf` (00:08 – 00:18)

**Type into Claude Code, exactly:**

```
/tf Stripe is double-charging some users on plan upgrades — looks like webhook retries are getting fulfilled twice. Can you fix it?
```

**Say while typing:**
> "Slash-tf is a skill we use to invoke Taskforce discovery. In Claude Code it runs as a skill; in Codex, Cursor, or anything else that speaks MCP, the same flow runs through Taskforce's MCP server."

Hit Enter.

---

### Beat 2b — Claude finds the candidate file (00:18 – 00:25)

Per the updated SKILL.md (PR #102), Claude first greps the repo for prompt nouns before invoking Taskforce. You'll see up to 2 candidates, ranked toward route/handler files:

```
🔎 Found candidate file: app/api/routes/billing.py
🔎 Found candidate file: app/core/stripe_billing.py
```

**Say:**
> "Claude hands Taskforce the prompt plus a quick scan of what part of the repo we're touching. Taskforce surfaces what we've already learned about it."

**Do:** ~5 seconds on tape. Continue to the announce + payload.

---

### Beat 3 — Payload shown (00:25 – 00:35)

The skill prints:

```
🟪 Checking Taskforce for related prior work…

📬 Sending to Taskforce:
{
  "prompt": "Stripe is double-charging some users on plan upgrades — …",
  "cwd": "/home/alexlee/dev/WORKTREE-stripe-fix/demo/full-stack-fastapi-template/backend",
  "files": ["app/api/routes/billing.py", "app/core/stripe_billing.py"],
  "git_branch": "fix/stripe-webhook-double-fulfillment"
}
```

**Say:**
> "It sends the prompt plus context — working dir, the candidate files Claude just found, the git branch. No code body, no chat history."

**Do:** Pause ~2 seconds so the viewer can read the payload. (The `files` list is exactly what beat 2b's grep returned, capped at 2 with route/handler files preferred — no silent additions.)

---

### Beat 3b — Profile selected (00:28 – 00:38)

After the discover call, the skill prints the matched profile (per TF-196 routing):

```
🧑‍💻 Bringing in profile: Jensen — Billing Reliability
  Confidence: medium (0.45)
  Why: routing triggers · linked memory · matching repo context
  [→ View profile](https://www.taskforce.tools/v2/agents/jensen)
```

**Say:**
> "Taskforce selected the Jensen profile — billing reliability. A profile isn't a separate agent; it's reusable operating context — routing triggers, linked memory, prior decisions, code touchpoints — that Claude, Codex, Cursor, or Composer can all use. Our scoring engine ranks each candidate by how well its triggers + linked memory + repo context match this prompt, then picks the top one above the medium band."

**Do:** Don't click the profile link mid-flow. Continue to beat 3c — we'll see where Jensen lives next.

> Note: pre-TF-201 Recent Invocations on Jensen's profile showed `""` for the Query column. After TF-201 deployed, new `/tf` calls write the real prompt. If you visit Jensen's profile post-recording, the take's invocation should display the actual query string.

---

### Beat 3c — Profile world + auto-suggest (00:38 – 00:52)

**Do:** Tab over to the pre-warmed `https://www.taskforce.tools/v2/agents` browser tab. Browser shows the index of every profile in this workspace — Jensen is one card among several.

**Say (~12s):**
> "And Jensen is just one of these. Every profile here is operating context the team's built up. You can create them by hand, and Taskforce auto-suggests new ones in the background as work is stored and ranked — surfacing the patterns worth promoting. You stay in control to accept, edit, or kill any suggestion. Jensen was one of those — promoted because billing-reliability work kept coming back."

**Do:** Hold ~2 seconds on the index. Tab back to Claude Code for Beat 4.

> **Honesty note for follow-up calls:** Auto-suggestion isn't shipped yet — the present-tense framing is intentional demo magic ([reviewed 2026-05-25]). If a viewer asks for a live walkthrough of the suggestion flow, fall back to: "the ranking + suggestion pipeline is rolling out next sprint; manual profile creation works today."

---

### Beat 4 — Matches land (00:52 – 01:12)

Skill prints the count attributed to Jensen, then two cards with deep-link URLs and 3-line previews:

```
📖 Jensen is bringing in 2 related documents:

1. Stripe webhook idempotency strategy — medium (0.34)
   → https://www.taskforce.tools/v2/library/<uuid>#incident-2026-04-11
   > ## Incident — 2026-04-11 double-charge
   > 30 customers on Pro upgrades got charged twice over a 90-minute
   > window. Root cause: Stripe aggressively retried webhook delivery …

2. Stripe plan upgrade webhook retries — regression test pattern — medium (0.37)
   → https://www.taskforce.tools/v2/library/<uuid>#targeted-regression-test
   > ## The targeted test
   > test_plan_upgrade_webhook_retry_short_circuits_before_dispatch …
```

**Say:**
> "Two matches. The first is the incident write-up from April — exact same root cause, the webhook fired twice on a retry. The second is the regression test we wrote right after. Both got stored in Taskforce at the time, linked to Jensen, and now they're back the moment we hit it again. That's the loop — work we've already done, ready when we need it."

**Do:** Click the first URL in the terminal. Browser opens to the library doc scrolled to the `#incident-2026-04-11` anchor. Hold for ~3 seconds.

**Say (over the browser):**
> "Written months ago, by me and Codex. Without Taskforce I'd either re-derive this from scratch or never find it."

**Do:** Cmd-Tab back to Claude Code.

---

### Beat 5 — Claude does the work (01:12 – 01:42)

Claude has the anchor content in context now. Expected behavior:
- Reads `app/api/routes/billing.py` — finds `record_stripe_event_or_skip` called *after* `_dispatch_event`
- Cites the decision doc's "WAL at the route boundary" anchor as the design constraint
- Moves the dedup call ABOVE the dispatch and adds an early-return for duplicates

**Say (over the streaming edit):**
> "Now Opus has the prior decision in context: the WAL check belongs at the route boundary, before fulfillment. Without that memory, a model might add idempotency inside the handler — which would fix the symptom but break the architectural invariant. The fix is six lines."

**Do:** Let it finish. If Claude wanders (e.g. tries to add idempotency inside the handler instead of at the route), cut and re-take. Per video-plan §8, this is the one beat that varies between takes.

Expected diff shape:

```diff
@@ app/api/routes/billing.py @@
     event = verify_webhook_signature(payload, signature_header)
+
+    if not record_stripe_event_or_skip(session, event):
+        return Message(message="Stripe webhook deduped")
+
     await _dispatch_event(event, session)
-    record_stripe_event_or_skip(session, event)
     return Message(message="Stripe webhook processed")
```

---

### Beat 6 — Test passes (01:42 – 01:52)

**Default path:** Claude runs the test on its own as part of Beat 5 — SKILL.md Beat 5 already says "read code, propose a fix, make edits, run tests." You see Claude's Bash tool call land in the terminal with the pytest command and a green PASSED line. **Don't type anything; just narrate.**

**Say (over Claude's pytest output):**
> "And there's the regression test we surfaced from Taskforce — passing. That was failing before the fix; the dedup at the route boundary short-circuits the second delivery before it gets to fulfillment."

**Fallback if Claude doesn't run the test on its own (variance):** type one short message:

```
now run the targeted regression test to confirm
```

Claude executes pytest via its Bash tool. Re-narrate over the green.

**Last-resort fallback (only if Claude is wandering badly enough that you'd otherwise re-take):** the `!` shell prefix runs a command directly without going through the model:

```
! pytest tests/api/test_billing_webhook_replay.py::test_plan_upgrade_webhook_retry_short_circuits_before_dispatch -q
```

Avoid this on tape if possible — it breaks the "Claude does the work" frame and viewers might not know what `!` is.

⚠️ **Don't run the full `tests/api/routes/test_billing.py` on camera.** Per the 2026-05-25 dry run, that file has pre-existing isolation flakes (`UniqueViolation` on `sub_existing`) unrelated to the fix. Targeted test only — and Claude has been seeing the targeted test name in the prior-work preview from Beat 4, so it usually picks the right command on its own.

---

### Beat 6b — Confirmation gate (01:52 – 02:02)

After the green test output, the skill recaps the work and asks you to confirm before recording anything as a "win." This is the gate before Beats 7 and 8 fire.

Skill prints:

```
Recap of this session:
  • Applied: dedup check now runs before _dispatch_event in app/api/routes/billing.py
  • Verified: test_plan_upgrade_webhook_retry_short_circuits_before_dispatch passed

Did this resolve the issue?
```

**Do:** Type `yes` (or `y`) and hit Enter. On any yes-shaped reply the skill proceeds to Beat 7 + 8. On `no` it stops cleanly — no references, no savings — and you'd cut the take.

**Say (over the recap, while reading + typing):**
> "Quick confirmation — Taskforce doesn't record this as a win until I say the fix actually solved the problem. Yes."

**Why this matters on tape:** It's the moment that separates Taskforce from a tool that claims a save the second an agent finishes editing. Savings only land if the human agrees the work landed.

---

### Beat 7 — Referenced-by appended (02:02 – 02:12)

The skill POSTs `/v2/taskforce/reference` on completion. Both consulted docs get a "Referenced by" row appended; Jensen gets an invocation row.

Skill prints:
```
✍️ Writing this session back to the referenced documents…
  • [Stripe webhook idempotency strategy](https://www.taskforce.tools/v2/library/<doc_id>) — Added "Referenced by" entry
  • [Stripe plan upgrade webhook retries — regression test pattern](https://www.taskforce.tools/v2/library/<doc_id>) — Added "Referenced by" entry
  • Profile [Jensen](https://www.taskforce.tools/v2/agents/jensen) — Added invocation
```

**Say:**
> "And the link goes both ways — this session is now in each document's 'Referenced by' list, and on Jensen's invocation history. Over time, the docs that get referenced most surface as the team's most-trusted memory."

**Do:** Stay in Claude Code; don't refresh the library tab. The terminal lines are the visual proof — three writes, three confirmations. Refreshing mid-recording adds a load and a scroll that's not worth the time on tape.

---

### Beat 8 — Jensen's profile (invocation just landed) (02:12 – 02:25)

The skill line you just narrated in Beat 7 ends with `Profile Jensen — Added invocation`. Cash that in: tab over to Jensen's pre-warmed profile and show the row that just appeared.

**Do:** Cmd-Tab (or click) to the pre-warmed `https://www.taskforce.tools/v2/agents/jensen` tab. Hard-refresh if needed (Cmd-Shift-R) so the Recent Invocations table picks up this session. Scroll to the **Recent Invocations** section — the top row should be the prompt you just typed, with a timestamp ~seconds old.

**Say (~13s, over Jensen's profile):**
> "And here's Jensen — the profile we routed through earlier. That top row in Recent Invocations is the session we just finished, written seconds ago. Every time Jensen handles a billing problem, it shows up here, and the linked memory underneath gets stronger. The profile compounds — same way a teammate gets sharper at billing the more billing tickets they touch."

**Do:** Hold ~2 seconds on the Recent Invocations row, then Cmd-Tab back to Claude Code so Beat 9 starts on the terminal.

> The Beat 8 narration intentionally previews the *compounding* idea that Beat 10 closes on at the team level — Jensen is the profile-level version of that story, so Beat 10 can land short and confident on the aggregate without re-explaining the concept.

> Recovery: if Recent Invocations is empty or shows `""` for the Query column, TF-201 didn't deploy or the reset script wiped this session's row. Don't try to fix on tape — narrate over the rest of the profile (linked memory, routing triggers) and re-take after the take ends.

---

### Beat 9 — Session metrics (savings receipt) (02:25 – 02:38)

Skill prints the final line:

```
💰 [Taskforce saved you 50,359 tokens on Opus 4.7 xhigh effort
(~$0.25)](https://www.taskforce.tools/v2/metrics?session_id=<uuid>)
```

**Do:** Click the link. Browser opens to a session-filtered metrics view (TF-192) showing the documents Jensen brought in, net tokens, and USD saved for this run.

**Say (~11s, over the session view):**
> "And the receipt. Fifty thousand tokens, twenty-five cents on Opus 4.7 — net of the context Taskforce injected. Two documents Jensen consulted, what we'd have spent re-deriving them, what Taskforce actually shipped. Mechanical, no agent self-report."

**Do:** Hold ~2 seconds on the session view. Continue to Beat 10.

---

### Beat 10 — Metrics overview + close (02:38 – 02:55)

**Do:** From the session view, click the **Overview** tab (or open the pre-warmed `https://www.taskforce.tools/v2/metrics` tab). Page zooms out to the team's aggregate — every session that pulled prior work, total tokens saved, savings over time.

**Say (~14s):**
> "And zoomed out — Jensen was one profile, one session. This is the team. Every session that pulled from Taskforce shows up here, the savings compound, and the memory keeps getting stronger. The more work flows through Taskforce, the more every future session benefits. That's Taskforce working."

**Do:** Hold ~3 seconds on the overview. Stop recording.

---

## If something breaks on tape

| Symptom | Cause | Recover |
|---|---|---|
| `/tf` not recognized | Skill didn't register | Quit, relaunch `claude` (a fresh launch — don't pass `--resume`), re-record |
| Beat 2b grep returns no candidate (or wrong file) | Claude's keyword pick missed (e.g. picked "fulfilled" instead of "stripe", "webhook") | Cancel → re-type the prompt with the obvious domain nouns up front ("Stripe webhook is double-charging…"). The skill greps on those. |
| Beat 3 payload shows `files: []` | Grep returned nothing → skill falls back to prompt-only → backend returns empty matches | Same fix as above — restate the prompt with concrete domain nouns |
| Zero matches returned despite a valid candidate file | `TASKFORCE_DEMO=1` not exported, OR seed not yet fired for account | Cancel → `export TASKFORCE_DEMO=1` → open `library?demo=true` in browser once → retry |
| Match list shows Alex's real working docs (Stripe Upgrade/Downgrade Flow etc.) instead of seed docs | `TASKFORCE_DEMO=1` missing — discover hit non-demo library | Same fix as above |
| Double "Related prior work" preamble | `TASKFORCE_HOOKS_DISABLED=1` missing | Set it, new shell, re-record |
| Deep-link 404 or doesn't scroll | TF-185 deploy lag, or wrong anchor id | Cancel + curl `/discover` first to grab a valid `matched_anchor_id`, retry |
| Claude wanders on the fix in beat 5 | Free-form response variance | Re-take. Per plan, this beat needs 2–3 dry runs |
| Savings line shows $0 | `/session-savings` aggregate missing this session's consults | Skill still ran; demo loses beat 7. File and re-record after fix |
| Savings line says "Sonnet" or wrong model | `CLAUDE_MODEL` env not set | Set `CLAUDE_MODEL=claude-opus-4-7`, new shell, re-record |
| Beat 7 says `(skipped N inaccessible doc(s))` | `TASKFORCE_DEMO=1` not visible to `tf-reference.sh` (older skill version) | `bash ~/dev/EnderAI/scripts/taskforce-skill/install.sh` to pull TF-202 fix, restart shell, re-record |
| First `/tf` returned 0 matches but immediate retry worked | Cold-index timing artifact (see 2026-05-25 dry run) | Pre-warm covers this — see §C-bis. If you skipped the pre-warm, do it now and re-record |

---

## After-each-take — reset for another take

Resets the three things a `/tf` run mutates so the next take starts clean. Idempotent.

```bash
# One-time per shell — paste your DATABASE_URL (External URL from
# Render → Postgres → Connect). Skip this export to run only the
# git-reset step; the script will warn about skipped DB cleanup.
export DATABASE_URL='postgresql://…@…oregon-postgres.render.com/enderai'

bash ~/dev/docs/reset-between-takes.sh
```

What it does:

1. **Git reset** — `git reset --hard origin/fix/stripe-webhook-double-fulfillment` on your worktree, drops Claude's `billing.py` edit so the bug is back.
2. **DB: delete today's `/tf` consult events** scoped to your account + `is_demo=true` — clears Recent Invocations on Jensen's page (incl. the pre-warm and any failed takes).
3. **DB: strip the `referenced-by` section** from the three TF-191 Stripe seed docs — the next take adds a fresh one instead of growing a stale list.

Then **quit Claude Code** (`Ctrl-D`) and **relaunch with `claude`** to drop the conversation state. Re-run pre-flight §B and §C before recording the next take.

Render shell fallback (no local `psql` / no `DATABASE_URL` export) is described in the comments at the bottom of `reset-between-takes.sh`.

---

## After the FINAL take (no more re-records)

- Save the keeper to `~/Recordings/tf-stripe-demo-2026-05-26-take<n>.mp4`
- Comment the take URL on TF-183 (epic) and TF-191 (seed)
- Clean up: `git worktree remove /home/alexlee/dev/WORKTREE-stripe-fix`
- Run `reset-between-takes.sh` one last time so the prod DB is clean (no stale `referenced-by` rows from the dry runs)
- Rotate the `DATABASE_URL` password in Render if you ever pasted it into chat or shared it during the recording prep

---

## Quick reference — copy-paste block

```bash
# --- Pre-flight smoke (curl) ---
TOKEN=$(cat ~/.enderai_mcp_token)
curl -s -X POST "https://enderai-backend.onrender.com/api/v1/v2/taskforce/discover?demo=true" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"prompt":"Stripe is double-charging some users on plan upgrades — looks like webhook retries are getting fulfilled twice. Can you fix it?","files":["app/api/routes/billing.py","app/core/stripe_billing.py"],"top_k":3,"min_score":0.3}' \
  | python3 -c "import sys,json; [print(m['score'],m['confidence_band'],m['title']) for m in json.load(sys.stdin)['matches']]"

# --- One-shot setup (idempotent — safe to re-run) ---
export TASKFORCE_HOOKS_DISABLED=1
export TASKFORCE_DEMO=1
export CLAUDE_MODEL=claude-opus-4-7
export CLAUDE_EFFORT=xhigh
export TASKFORCE_BACKEND_URL=https://enderai-backend.onrender.com

TASKFORCE_REPO=/home/alexlee/dev/EnderAI
FIX_BRANCH=fix/stripe-webhook-double-fulfillment
DEFAULT_WORKTREE=/home/alexlee/dev/WORKTREE-stripe-fix

git -C "$TASKFORCE_REPO" worktree prune
WORKTREE_PATH=$(git -C "$TASKFORCE_REPO" worktree list --porcelain | awk -v br="refs/heads/$FIX_BRANCH" '/^worktree / { wt = $2 } $1 == "branch" && $2 == br { print wt; exit }')

if [ -z "$WORKTREE_PATH" ]; then
    git -C "$TASKFORCE_REPO" worktree add "$DEFAULT_WORKTREE" "$FIX_BRANCH"
    WORKTREE_PATH="$DEFAULT_WORKTREE"
fi

cd "$WORKTREE_PATH/demo/full-stack-fastapi-template/backend"
echo "branch: $(git branch --show-current)"
echo "cwd:    $PWD"
env | grep -E "^(TASKFORCE_|CLAUDE_)" | sort

claude
```

Then inside Claude Code:

```
/effort xhigh
/model opus
/tf Stripe is double-charging some users on plan upgrades — looks like webhook retries are getting fulfilled twice. Can you fix it?
```
