# Taskforce — Engineering Manager Handoff Plan

_Status: draft for Alex's review · 2026-06-11_

## 1. The ask

Hand Taskforce to an engineering manager (EM) so he can play with it himself. His
stated need, from the source:

> "He mostly wants to be able to open multiple Claude instances, and have those
> Claudes know what's going on between, so [he] doesn't need to re-explain across
> terminals or across VMs etc."

So the headline he must feel within 5 minutes of signing up:

> Terminal A does some work → Terminal B (or a Claude on another VM) opens, and
> **without being told**, already knows what A figured out.

On top of making that work, we need to **clean up onboarding** and **tuck away
the demo / dead-end surfaces** so a real user lands in a coherent product, not a
half-lit internal workbench.

This doc is the audit + plan. Nothing here is built yet.

---

## 2. The good news: the loop already exists end-to-end

The "shared brain across terminals" loop is already implemented. It is three
moving parts, all present in the codebase today:

```
        ┌─────────────────────────── Terminal A (Claude Code) ──────────────────────────┐
        │                                                                                 │
prompt ─┤ UserPromptSubmit hook ── POST /v2/taskforce/discover ──► (recall: inject        │
        │   (user-prompt-submit.sh)                                 "Related prior work")  │
        │                                                                                 │
work ───┤ PostToolUse hook (every 10 calls) ─┐                                            │
        │ Stop hook (session end) ───────────┴─ POST /v2/taskforce/observe ──► (capture:  │
        │   (post-tool-use.sh / stop.sh)                          summarize → write doc)   │
        └─────────────────────────────────────────────────────────────────────────────────┘
                                              │
                                  V2 Document library (per-user)
                                              │
        ┌─────────────────────────────────────▼───────────────────────────────────────────┐
        │ Terminal B opens, submits a prompt → discover finds A's doc → injects it.         │
        └──────────────────────────────────────────────────────────────────────────────────┘
```

- **Capture** — `scripts/taskforce-hooks/{stop.sh,post-tool-use.sh}` ship a
  redacted transcript digest to `POST /api/v1/v2/taskforce/observe`. The backend
  (`app/core/taskforce/observe.py`) runs a materiality check
  (`materiality.py`), summarizes via Haiku (`summarizer.py`), and patches/creates
  a **V2 Document**.
- **Recall** — `scripts/taskforce-hooks/user-prompt-submit.sh` calls
  `POST /api/v1/v2/taskforce/discover` on every prompt. The backend
  (`app/core/taskforce/discover.py`) scores the user's document library against
  the prompt and returns the top matches; the hook prepends them as a
  "Related prior work" preamble.
- **Scoping** — discover reads `list_v2_documents_for_actor`
  (`app/core/v2_documents.py:3502`). For a single user with the **same token on
  every VM/terminal**, this returns *that user's* documents. So cross-VM,
  same-person recall is just owner-scoping — no org required.

This is exactly the EM's use case. **We are not building the feature — we are
un-gating and de-risking a feature that already exists.**

---

## 3. The bad news: the loop is broken in three specific places

All three are small, surgical, and independently verifiable.

### 🔴 Blocker 1 — Observe is in shadow mode by default (capture is a no-op)

`app/core/taskforce/observe.py:69`

```python
def _shadow_mode() -> bool:
    return os.environ.get("TASKFORCE_OBSERVE_SHADOW", "1") not in {"0", "false", "False"}
```

Default is **on**. In shadow mode, observe records an audit event and a session
archive but **never patches or creates the document** — it returns
`action="skipped", reason="shadow_mode"`. So Terminal A's work is never written
to the library, and Terminal B's discover has nothing fresh to find. **The
capture half of the loop is disabled out of the box.**

> Note: `upsert_session_archive_from_observe` *does* run in shadow mode, so the
> Ledger's session archive fills up — but discover only searches `V2Document`,
> not archives (`discover.py` → `list_v2_documents_for_actor`). Archives alone
> don't close the loop.

### 🔴 Blocker 2 — Onboarding writes the token to the wrong path (recall + capture can't authenticate)

The Connect Agent UI and the cross-session hooks disagree on where the token
lives:

| | Path it uses | Source |
|---|---|---|
| **Connect Agent UI** | writes `~/.taskforce_mcp_token`, exports `ENDERAI_MCP_TOKEN` | `ConnectAgent.tsx:84-101` |
| **Cross-session hooks** | read `~/.enderai_mcp_token` (file, not env var) | `user-prompt-submit.sh`, `stop.sh`, `post-tool-use.sh` → `TOKEN_FILE="${HOME}/.enderai_mcp_token"` |

A user who follows the Connect Agent flow to the letter ends up with a token the
hooks **cannot read**, so every hook silently exits 0 ("skip: no token"). Worse,
the Connect Agent UI doesn't install the cross-session hooks at all — its "Claude
Code cost tracking" card installs a *different* Stop hook
(`taskforce-record-usage.sh`) for billing, not the discover/observe hooks. **The
two onboarding mechanisms are disjoint and the token paths don't line up.**

### 🔴 Blocker 3 — The Haiku summarizer needs a managed key the hook path can't supply

`observe.py` only runs the summarizer when `settings.ANTHROPIC_API_KEY` is set
(`app/core/config.py:132`, default `None`). The hooks ship a **raw transcript**
(not a pre-structured digest), so they take the summarizer path. With no managed
key, observe returns `action="skipped", reason="no_managed_anthropic_key"` —
capture fails even with shadow mode off.

> The MCP `enderai_*_document` tools take a different, structured path
> (`_has_structured_payload`) that skips the summarizer — but that path requires
> the agent to diligently call begin/update/finish, which is exactly the manual
> re-explaining we're trying to kill. For "it just works," the hook path is the
> spine, and it needs the managed key.

---

## 4. Plan Part A — Make cross-instance context actually work

Goal: a freshly onboarded EM, same token on two machines, gets automatic recall.

### A1. Turn off shadow mode for the EM's environment
- Set `TASKFORCE_OBSERVE_SHADOW=0` on the backend (Render env).
- **Decision needed (see §7):** global flip vs. per-user gate. Recommendation:
  flip it globally on a staging/preview backend the EM points at, OR add a
  lightweight per-user `observe_writes_enabled` gate if we're nervous about other
  tenants. For a single-EM handoff, the global flip on a dedicated backend is the
  fastest safe option.

### A2. Provision a managed Anthropic key for the summarizer
- Set `ANTHROPIC_API_KEY` on the backend so the hook (raw-transcript) path can
  summarize. The daily per-user USD cap already exists
  (`DEFAULT_DAILY_USD_CAP = $1.00`, `observe.py`) so runaway cost is bounded.

### A3. Tighten capture latency for a live demo
- Default checkpoint cadence is every 10 tool calls
  (`TASKFORCE_CHECKPOINT_EVERY`, `post-tool-use.sh:22`). For a snappy "B sees A
  almost immediately" demo, drop to ~3–5 for the EM. (Stop-hook capture at
  session end already works regardless.)
- Confirm discover's `min_score` threshold isn't so high that a single-user
  library with a handful of docs returns nothing. Worth a quick tune for the
  cold-start case (few docs, want generous recall).

### A4. Verify the same-user-across-machines scoping end-to-end
- `list_v2_documents_for_actor` returns owner + shared + org-visible docs. For
  the solo EM, owner-scoping is the path. Confirm the EM uses **one credential
  token** across all VMs (the token *is* the identity). Document this explicitly
  in onboarding — "use the same token everywhere" is the whole trick.

### A5. (Stretch, only if we want multi-person) Org visibility
- If the EM wants his *teammates'* Claudes to share context too, that needs an
  org + `visibility="organization"` docs + the Ledger (which 422s for solo
  users). **Out of scope for the stated ask** (he said his own terminals/VMs);
  noted so we don't accidentally design for it now.

---

## 5. Plan Part B — Collapse onboarding into one coherent path

Today onboarding is three half-paths (Connect Agent UI token, the cost-tracking
Stop hook, and the separate `taskforce-hooks/install.sh`). A real user can't
self-assemble them. Converge on **one** flow.

### B1. Unify the token path
- Pick **one** canonical location and make everything agree. Recommendation:
  standardize on `~/.enderai_mcp_token` (what the hooks already read) — or rename
  both to `~/.taskforce_mcp_token` as part of the TF-180 rebrand, updating the
  three hook scripts in lockstep. Either way: **one path, referenced identically**
  in `ConnectAgent.tsx` and all hooks.
- Have the Connect Agent "persist token" snippet write that one file.

### B2. Make the hook installer part of the UI flow
- Add the cross-session hooks (`install.sh`) to the Connect Agent card as the
  primary "Connect Claude Code" action — one copy-paste block that (a) writes the
  token to the canonical path and (b) runs the hook installer. The installer is
  already idempotent.
- Re-point the install URL/env: `install.sh` and the hooks default
  `ENDERAI_BACKEND_URL` to `https://enderai-backend.onrender.com`. Make sure
  that's the backend the EM's account lives on (or override it in the snippet).

### B3. Reframe the Connect Agent card for a real user
- Current subtitle is "Token and config snippets for local MCP testing." — reads
  as an internal tool. Reframe to "Connect your coding agent" with a clear
  two-step: **1) create credential → 2) run this one command in each terminal/VM.**
- The MCP-config + AGENTS.md instruction snippets (`enderai_begin_document` etc.)
  are the *explicit Tier-1* path. Keep them, but **demote them below** the
  zero-effort hook path so the default story is "install hooks, done," not "edit
  your AGENTS.md."

### B4. First-run state
- Post-login lands on `/v2/library` (`DEFAULT_FRONTEND_PATH`). For a brand-new
  account the library is empty ("No documents yet."). Add a first-run nudge that
  routes to Connect Agent ("Connect a terminal to start capturing work") so the
  empty library isn't a dead end.
- Confirm the EM's account has `user.v2 = True` (`app/models.py:170`, default
  `False`) or the V2 UI 403s into `TaskforceNoAccess`.

---

## 6. Plan Part C — Tuck away demo / dead-end surfaces

These are surfaces that, for a real solo user, are empty, demo-only, or
plan-gated — i.e. dead ends that make the product feel broken.

| Surface | Problem for a real user | Recommended action |
|---|---|---|
| **Top-bar document search** (`TaskforceShell.tsx` `DocumentSearch`) | Only works in **demo mode** — otherwise shows "Turn on demo mode to search documents." | Either wire it to the real library search, or hide the top-bar search for non-demo users. Don't ship a search box that tells users to turn on demo mode. |
| **Ledger tab** (`/v2/ledger`) | `422 "User does not belong to an organization"` for solo users (`taskforce.py` ledger routes). | Hide the Ledger nav item for solo (non-org) users, or show a clean "Ledger is for teams" empty state instead of an error. |
| **Search / chat (RAG)** (`/v2/search`, `SearchPage` + `ByokSetup`) | Plan + BYOK gated; a fresh account hits an eligibility gate / upsell, not a working feature. | Confirm the EM's plan unlocks it, or down-rank the Search tab so it isn't the first thing he clicks. Decide if Search is in-scope for the handoff at all. |
| **Profiles / Agents** (`/v2/agents`) | Empty for a new user; copy says "Agents will appear here after Taskforce packages reusable profile knowledge from your work." | Fine as-is (honest empty state), but verify the compounding job that populates it (`compounding.py`, `compound_specialists.py`) actually runs for live (non-demo) data, else it's permanently empty. |
| **Demo mode + Experimental mode toggles** | Already gated to superusers (`InternalModeAccessGate`, `SidebarUtilityDrawer showInternalModes`). | ✅ No action — internal toggles are correctly hidden from the EM. Just confirm the EM is **not** a superuser. |
| **Discord button** | Placeholder, "Discord link coming soon," `TASKFORCE_DISCORD_URL = ""`. | Set the real URL or hide the button. Minor. |
| **Demo seed data** (`seed_agents.py`, `seed_demo_metrics_alex.py`, `seed_empty_cell_scenario.py`) | Demo docs are `is_demo=True` and isolated from live (`demo` flag throughout). | ✅ Already isolated. Just make sure the EM's account has **no** demo seed and demo mode defaults off (it does — `demo-mode-provider.tsx` defaults `false`). |

Net: the only hard dead-ends to fix are **top-bar search** (demo-only) and
**Ledger** (422 for solo). The rest are honest empty states or already gated.

---

## 7. Open decisions (need Alex's call)

1. **Which backend does the EM point at?** A dedicated/staging backend where we
   can safely flip `TASKFORCE_OBSERVE_SHADOW=0` and set a managed key, vs. prod
   with a per-user gate. → drives A1/A2.
2. **Shadow-off blast radius.** Global env flip (simple, affects all tenants on
   that backend) vs. add a per-user `observe_writes_enabled` column (safer,
   ~small migration). Recommendation: dedicated backend + global flip for the
   handoff; add the per-user gate later if we open it to more users.
3. **Token path canonicalization.** Standardize on `~/.enderai_mcp_token` (zero
   hook changes) vs. rename to `~/.taskforce_mcp_token` (aligns with TF-180
   rebrand, touches 3 hook scripts + ConnectAgent). Recommendation: do the rename
   now since we're touching onboarding anyway and the rebrand is in flight.
4. **Is Search (RAG chat) in scope for the handoff?** If yes, the EM's plan/BYOK
   must be provisioned. If no, down-rank the tab.
5. **Solo vs. team.** Confirm the ask is genuinely "his own terminals/VMs" (solo,
   owner-scoped) and we are *not* on the hook for multi-person org sharing yet.

---

## 8. Acceptance test (the demo we must be able to run)

This is the script that proves the handoff is ready. Run it before handing over.

1. Create a fresh EM-like account (`v2=True`, not superuser, no demo seed).
2. Connect Agent → create credential → run the one-command setup in **Terminal A
   on VM 1**. Confirm token at the canonical path + hooks installed
   (`jq '.hooks.UserPromptSubmit' ~/.claude/settings.json`).
3. In Terminal A, do a small real task (e.g. "set up the X config, here's the
   gotcha: Y"). Let the session end (Stop hook fires) or hit a checkpoint.
4. Confirm a document appears in `/v2/library` (proves shadow-off + managed key +
   capture).
5. Open **Terminal B** (different terminal, ideally different VM, **same token**).
   Submit a prompt that brushes the same topic.
6. Confirm the `[Taskforce] N related docs pulled` banner appears and the
   "Related prior work" preamble includes A's gotcha **without B being told.**
   ← _This is the money shot._
7. Walk the UI: Library has the doc, no tab throws a 422/"turn on demo mode"
   dead-end, internal toggles hidden.

If step 6 lands, the EM's core ask is satisfied.

---

## 9. Sequenced work breakdown

Ordered so the loop is provably working before we polish the shell.

**Milestone 1 — Close the loop (functional core).** _Highest priority._
- [ ] A1 Flip `TASKFORCE_OBSERVE_SHADOW=0` on the chosen backend.
- [ ] A2 Set managed `ANTHROPIC_API_KEY`.
- [ ] A4 Verify same-user owner-scoped recall end-to-end (acceptance steps 3–6).
- [ ] A3 Tune `TASKFORCE_CHECKPOINT_EVERY` + discover `min_score` for cold-start.

**Milestone 2 — One onboarding path.**
- [ ] B1 Canonicalize the token path across ConnectAgent + 3 hook scripts.
- [ ] B2 Add the hook installer to the Connect Agent UI as the primary action.
- [ ] B3 Reframe Connect Agent copy for a real user; demote the explicit-MCP path.
- [ ] B4 First-run nudge from empty library → Connect Agent; verify `v2=True`.

**Milestone 3 — Remove dead ends.**
- [ ] C Hide/fix top-bar search for non-demo users.
- [ ] C Hide Ledger nav (or clean empty state) for solo users.
- [ ] C Decide Search-tab scope; Discord URL or hide.

**Milestone 4 — Dress rehearsal.**
- [ ] Run §8 acceptance test on a clean account; fix whatever leaks.

Milestone 1 is the whole ballgame — it's mostly **environment config, not code**,
which matches the intuition that "we have a lot of supporting functionality, so
it will not be very challenging." Milestones 2–3 are modest frontend + hook/script
edits. None of it requires new backend feature work.

---

## 10. Risks / watch-items

- **Shadow-off on a shared backend** writes real documents for every tenant on
  that backend, not just the EM. Use a dedicated backend or a per-user gate.
- **Summarizer cost.** Capped at $1/user/day, but confirm the cap is acceptable
  and the managed key has budget.
- **Redaction.** The hooks redact obvious secrets (`redaction.py`) before
  shipping transcripts, but the EM should be told transcripts (redacted) leave his
  machine — relevant if he's working on anything sensitive.
- **Latency of recall.** B only sees A's work after A checkpoints or ends. Set
  expectations: it's near-real-time, not live keystroke sharing.
- **`ENDERAI_*` vs `TASKFORCE_*` naming** is mid-rename (TF-180). Keep the token
  path / env var changes consistent with that migration so we don't add a third
  naming convention.

---

### Appendix — key files

| Concern | File |
|---|---|
| Recall hook | `scripts/taskforce-hooks/user-prompt-submit.sh` |
| Capture hooks | `scripts/taskforce-hooks/{post-tool-use,stop}.sh` |
| Hook installer | `scripts/taskforce-hooks/install.sh` |
| Discover (recall) | `app/core/taskforce/discover.py`, `scoring.py` |
| Observe (capture) | `app/core/taskforce/observe.py`, `materiality.py`, `summarizer.py` |
| Shadow flag | `app/core/taskforce/observe.py:69` |
| Doc ACL / scoping | `app/core/v2_documents.py:3502` (`list_v2_documents_for_actor`) |
| Route surface | `app/api/routes/taskforce.py` |
| Onboarding UI | `src/components/UserSettings/ConnectAgent.tsx` |
| App shell / nav / top search | `src/components/V2/TaskforceShell.tsx` |
| Demo/experimental gating | `src/components/demo-mode-provider.tsx`, `InternalModeAccessGate` |
