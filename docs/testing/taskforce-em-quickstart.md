# Taskforce — try it yourself (EM quickstart)

_A 10-minute, do-it-yourself run-through of the exact thing an engineering
manager asked for: open multiple Claude instances and have each know what the
others did, without re-explaining. You can simulate "multiple VMs" with **two
terminals on one machine** — both share the same `~/.claude` hooks + token, so
it's a faithful test of the cross-instance loop._

For the deeper, scripted test matrix see `taskforce-e2e-test-runbook.md`.

---

## Step 0 — Get your token (web app)

1. Go to **https://www.taskforce.tools** and log in.
2. **Settings → Connect agent → Create credential.**
3. Copy the **"Connect Claude Code"** one-command block (your token is baked in).

## Step 1 — Install on your machine

Paste that block into a terminal. It saves the token to `~/.taskforce_mcp_token`
and runs the hook installer. Verify:

```sh
test -r ~/.taskforce_mcp_token && echo "token ok" || echo "TOKEN MISSING"
jq '.hooks | {UserPromptSubmit, Stop, PostToolUse}' ~/.claude/settings.json
ls ~/.claude/hooks/taskforce-*.sh
```

Want: `token ok`, all three hook types non-null, three scripts listed.

> You do **not** need the MCP server config for this — the cross-instance loop
> runs entirely off the hooks + token file.

## Step 2 — 30-second backend health check (optional but smart)

Confirm the backend loop works before involving Claude:

```sh
bash ~/dev/EnderAI/docs/testing/taskforce-smoke-test.sh
```

Want: `RESULT: 3 passed, 0 failed → ✅ Capture → recall loop works end to end.`
If it fails, stop here — it names the broken link (token, shadow mode, or recall).

---

## Step 3 — The actual test: two Claudes, no re-explaining

### Terminal 1 — "teach" Claude something

1. Open a **new terminal** and run `claude` to start a brand-new session.
2. Paste this exact prompt:

   > Note for later: our staging Postgres DSN rotates every **14 days**, and the
   > runbook is at `ops/db-rotation.md`. Write that into a file called `db-note.md`.

3. Let it create the file (this makes the session "material" so it gets captured).
4. End the session: type `/exit` (or Ctrl-D).
5. Back in a normal shell, confirm capture happened:

   ```sh
   tail -n 3 ~/.claude/taskforce-observe.log     # want: POST /v2/taskforce/observe → 202
   ```

### Terminal 2 — the "other instance" that wasn't told anything

1. Open **another new terminal** and run `claude` to start a separate session
   (this must start *after* Terminal 1's session ended — see gotchas below).
2. Paste this prompt, *without restating any facts*:

   > What's our staging Postgres rotation cadence, and where's the runbook?

---

## What success looks like

In Terminal 2, **before Claude even answers**, you should see:

- a banner: `[Taskforce] 1 related doc pulled · …`
- the prompt silently prefixed with a `─── Related prior work (Taskforce) ───`
  block containing the **14 days / `ops/db-rotation.md`** fact,
- Claude answering correctly with **14 days** and `ops/db-rotation.md` — even
  though you never told Terminal 2 those facts.

Confirm via:

```sh
tail -n 3 ~/.claude/taskforce-discover.log     # want: ok: 1 matches injected
```

That's the request demonstrated: the second Claude knew what the first one did.

---

## Two gotchas

- **Restart matters.** Hooks load only when a `claude` session *starts* — start
  both test terminals *after* Step 1.
- **Timing.** Terminal 2 only recalls what Terminal 1 already captured, so let
  Terminal 1 hit a tool call (the file write) or end the session before you
  prompt Terminal 2.

## If something's off

| Symptom | Fix |
|---|---|
| No banner in Terminal 2 | re-check Step 1 on this machine; `tail ~/.claude/taskforce-discover.log` for the skip reason; ensure `jq` is installed |
| `observe.log` shows no `202` | session wasn't "material" (touch a file / ≥3 turns); check the token |
| Smoke test `shadow=true` | `TASKFORCE_OBSERVE_SHADOW=0` isn't set on the backend |
| Smoke test 401 | token bad/expired — recreate the credential |
