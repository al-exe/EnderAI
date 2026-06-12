# Taskforce end-to-end test runbook

_Companion to `taskforce-em-handoff-plan.md`. Proves the thing the EM actually
asked for: open multiple Claude instances and have each know what the others did._

There are four parts, fastest/cheapest first. Run them in order — each one
de-risks the next, and if an early part fails you don't need the later ones.

| Part | Proves | Time | Type |
|---|---|---|---|
| A — Onboard | a clean machine can connect | ~3 min | manual |
| B — API smoke test | capture→recall loop closes (shadow off + write + read) | ~30 sec | **scripted** |
| C — Hook integration | the hooks fire on a real Claude Code session | ~5 min | manual |
| D — Two-instance recall | **the EM's actual request** | ~5 min | manual |

---

## Prerequisites (one-time, backend side)

These are the env switches the loop depends on — confirm before testing:

- `TASKFORCE_OBSERVE_SHADOW=0` on the backend (else capture is a no-op).
- `ANTHROPIC_API_KEY` set on the backend (needed for the **hook** path, which
  ships a raw transcript and summarizes with Haiku; Part B uses a structured
  payload that skips the summarizer, so it works even without this).
- The test account has `user.v2 = true` (only needed for the **web UI**; the
  terminal loop authenticates fine without it).
- Each test machine has `bash`, `curl`, `jq`.

---

## Part A — Fresh onboarding

On each machine you'll test from:

1. In the app → **Settings → Connect agent** → create a credential. Copy the
   one-command "Connect Claude Code" block (it saves the token to
   `~/.taskforce_mcp_token` and runs the hook installer).
2. Run it in a terminal. Then verify:
   ```sh
   test -r ~/.taskforce_mcp_token && echo "token ok" || echo "token MISSING"
   jq '.hooks.UserPromptSubmit, .hooks.Stop, .hooks.PostToolUse' ~/.claude/settings.json
   ls ~/.claude/hooks/taskforce-*.sh
   ```
   All three hook types should be non-null and the three scripts present.
3. **Restart Claude Code** so it loads the new hooks.

> Use the **same credential token** on every machine — the token resolves to
> your user, and that's what makes the library shared across terminals/VMs.

---

## Part B — Automated API smoke test (the core proof)

This is the fast, deterministic proof that the capture→recall loop closes. It
writes a uniquely-marked document via `/observe`, then confirms `/discover`
finds it — no Claude session needed.

```sh
bash docs/testing/taskforce-smoke-test.sh
```

Expected tail:
```
[1/3] auth + discover reachable      PASS
[2/3] observe writes a document      PASS: document created
[3/3] discover surfaces the document PASS: the marked document was recalled
RESULT: 3 passed, 0 failed
✅ Capture → recall loop works end to end.
```

- Defaults to the **demo** library so it doesn't clutter your real one.
- `TASKFORCE_SMOKE_DEMO=0 bash docs/testing/taskforce-smoke-test.sh` runs the
  **live** path the hooks actually use (creates one real `SMOKE-…` doc you can
  delete from the Library afterward).
- `TASKFORCE_BACKEND_URL=…` to point at a non-default backend.

If this passes, the backend half of the EM's feature is proven. Parts C–D just
confirm the hooks wire a real Claude session into the same loop.

---

## Part C — Hook integration (single machine)

Confirms the hooks actually fire on a real session (not just direct API calls).

1. In a Claude Code session, do a small, **distinctive** task — e.g.:
   > "Note for later: our staging Postgres DSN rotates every **14 days**, and the
   > runbook lives at `ops/db-rotation.md`. Make a one-line note file."
   Let it edit a file (so the session is "material") and end the session.
2. Verify capture fired:
   ```sh
   tail -n 5 ~/.claude/taskforce-observe.log     # expect: POST /v2/taskforce/observe → 202
   ```
3. Verify a document was written (reuse the smoke test's discover, or):
   ```sh
   TOKEN=$(cat ~/.taskforce_mcp_token)
   curl -sS -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -X POST --data '{"prompt":"staging postgres dsn rotation cadence","k":3,"min_score":0.1}' \
     https://enderai-backend.onrender.com/api/v1/v2/taskforce/discover | jq '.matches[] | {title, score}'
   ```
   You should see a doc about the 14-day rotation.
4. In a **new prompt in the same session**, you should also see the
   `[Taskforce] N related doc(s) pulled` banner once a matching doc exists.
   ```sh
   tail -n 5 ~/.claude/taskforce-discover.log    # expect: ok: N matches injected
   ```

---

## Part D — Two-instance recall (the EM's actual request)

The money shot: a second Claude knows what the first did, with no re-explaining.

1. **Instance A** (terminal/VM #1, onboarded per Part A): do the distinctive
   task from Part C if you haven't. Confirm capture (`taskforce-observe.log` →
   202) and that the doc exists (Part C step 3).
2. **Instance B** (a *different* terminal — ideally a different VM — onboarded
   with the **same token**): start Claude Code and submit a prompt that brushes
   the same topic **without restating the facts**:
   > "What's our staging Postgres rotation cadence, and where's the runbook?"
3. **Success criteria:**
   - Instance B shows the `[Taskforce] … related doc(s) pulled` banner.
   - The prompt is silently prefixed with a `─── Related prior work (Taskforce) ───`
     block containing A's "14 days / `ops/db-rotation.md`" fact.
   - B answers correctly **from that injected context**, though you never told B.

That is the EM's request demonstrated end to end. Latency note: B sees A's work
after A's next checkpoint (every tool call) or session end — seconds to minutes,
not live keystrokes.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Smoke `[1/3]` HTTP 401 | bad/expired/wrong token | recreate the credential; check `~/.taskforce_mcp_token` |
| Smoke `[1/3]` HTTP 000/5xx | wrong backend or backend asleep (Render cold start) | re-run; set `TASKFORCE_BACKEND_URL`; wait for warmup |
| `observe … shadow=true` | `TASKFORCE_OBSERVE_SHADOW` not `0` | set it `0` on the backend, redeploy |
| `observe … skipped reason=no_managed_anthropic_key` | no managed key (only bites the **hook** raw-transcript path) | set `ANTHROPIC_API_KEY` on backend (Part B avoids this via structured payload) |
| `observe … skipped reason=cost_capped` | daily $1/user summarizer cap hit | wait until UTC midnight, or raise the cap |
| `observe … skipped reason=trivial session` | materiality gate (too few turns/files/commands) | do more in the session (≥3 turns, or touch a file) |
| `[3/3]` recalled nothing | capture wrote nothing (shadow), or score < `min_score` | fix shadow first; lower `min_score`; use a more on-topic prompt |
| No banner in Instance B | hooks not installed / token missing / `jq` absent on B | re-run Part A on B; `tail ~/.claude/taskforce-discover.log` for the skip reason |
| Banner appears but prompt unchanged | older Claude Code that doesn't inject UserPromptSubmit stdout | upgrade Claude Code |

---

## Cleanup

- Demo-mode smoke docs are isolated and ignorable. Live-mode (`TASKFORCE_SMOKE_DEMO=0`)
  creates one real `SMOKE-…` doc — delete it from the Library if you want.
- Temp response bodies land in `/tmp/tf_smoke_*.json`.
