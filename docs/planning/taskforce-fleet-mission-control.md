# Taskforce — Fleet as "Mission Control" (enhancement roadmap)

*Plan (2026-06-13). Builds on `taskforce-fleet-tab.md` (the shipped MVP) and
`taskforce-active-sessions-roster.md` (the data source). Read those first — this
doc is the "make Fleet a flagship sell feature" pass on top of them.*

## Goal

Turn Fleet from a **passive grouping board** into an **operable control plane**:
observe what every agent is doing in real time, act on running agents, let agents
pull from each other, and carry a session's context across terminals, VMs, and
teammates. The pitch: *Mission Control for your agent fleet.*

## Where Fleet is today (grounded read, 2026-06-13)

- **Telemetry is one-way / pull-based.** Each prompt hits `POST
  /v2/taskforce/discover` → `touch_session_heartbeat`
  (`active_sessions.py:48`) upserts a `TaskforceSessionArchive` (cwd, repo,
  branch, model_id, specialist_slug, active_document_id,
  referenced_document_ids, last_seen_at, fleet_session_id). Tool-use hooks hit
  `/observe` (`observe.py:116`) → summarize → write a `V2Document`.
- **Fleet polls `GET /fleet` every 30s** (`FleetPage.tsx:653`) and renders the
  `active_sessions_for_actor` shape (`active_sessions.py:226`).
- **"Controls" today are metadata, not actions on the agent.** Create / rename /
  delete a fleet, assign / unassign an agent (`v2Taskforce.ts:105-155`). Nothing
  in Fleet touches a *running* agent — there is no channel back to it.
- **Cross-agent sharing is implicit.** Agents share knowledge only by one finding
  another's document via semantic match in `/discover`. But `observe.py:280`
  already stamps `fleet_session_id` onto created docs — fleet-scoped knowledge
  already exists in the data; it is neither surfaced nor pushed.

### Two ceilings to fix first (prerequisites)

- **`ROSTER_LIMIT = 5`** (`active_sessions.py:45`) — Fleet only ever shows the 5
  most-recent live sessions. Too small for something sold as a "fleet." Raise +
  paginate.
- **`MAX_AGE = 8h`** presence backstop (`active_sessions.py:42`) — fine, but
  pair it with explicit force-end so the roster stays clean.
- (Minor) `active_sessions_for_actor` passes `demo=None`
  (`active_sessions.py:247`), so Fleet mixes demo + real sessions. Decide whether
  that is intended for the live product.

## The unlock: a directive channel on `/discover`

The single most important architectural fact: **the discover round-trip is a
latent command channel.** Every agent already calls home on every prompt.
Piggyback a `pending_directives: [...]` array on the discover response; the local
hook applies them (inject context, pause, switch specialist, soft-stop). Latency
is one prompt cycle — no websockets required. This one move unlocks roughly half
of the "control" and "collaborate" features below.

Directive lifecycle (sketch): Fleet UI writes a `TaskforceDirective` row
(target session_id or fleet_session_id, kind, payload, status); `/discover`
drains pending directives for the calling session and marks them delivered;
optional ack on the next `/observe`.

## Five pillars

Feasibility tags: ✅ data already captured (UI/read only) · 🟡 new
aggregation/endpoint, no agent change · 🔶 needs the directive channel · 🔵 needs
realtime transport.

### 1. Observe — know what every agent is doing right now

- **Live cost + token + savings rollup per agent / fleet / total.** 🟡 The data
  already flows: `observe.py:438` writes `tokens.consumed` (subkind
  `agent_session`, carrying `session_id`) plus summarizer cost into
  `MetricsEvent`. Aggregate by `session_id` → `fleet_session_id`. Surface "this
  fleet: $4.20 · 1.2M tok last hour · $0.31 saved." **This is the ROI ledger made
  live — the strongest single sell.**
- **"Currently editing" on the card.** ✅ `files_touched` / `commands_run` arrive
  on every `/observe` (`observe.py:99-104`) and are currently discarded by the
  UI. Showing "editing billing.py, webhook.py" is the most direct
  what's-it-doing signal available.
- **Stall / stuck detection.** 🟡 Today "Idle" is just `minutes_ago ≥ 5`
  (`FleetPage.tsx:148`). Distinguish *running-but-no-doc-progress-in-15m*
  (looping/stuck) from *cleanly idle* using `taskforce.observed` audit cadence.
  A ⚠️ "no progress 15m" badge is genuinely actionable.
- **Capture-paused reasons.** ✅ `/observe` returns `skipped` with `cost_capped`
  / `no_managed_anthropic_key` / `empty_summary` (`observe.py:159-196`). Surface
  "⚠️ capture paused — daily cost cap hit" so a silent agent is not a mystery.
- **Per-agent activity sparkline** from `taskforce.observed` events
  (files/commands/duration over time). 🟡

### 2. Control — act on the fleet

With the directive channel:
- **Pause / resume capture** 🔶 (cheap flag) · **soft stop** 🔶 · **broadcast a
  steering instruction to a whole fleet** ("all agents: rebase on main first"),
  injected as context on the next prompt 🔶.
- **Reassign specialist/profile** to a running agent 🔶 — routing already exists;
  let the operator force one.
- **Per-fleet cost cap** 🟡 — `DEFAULT_DAILY_USD_CAP` is a global constant today
  (`observe.py:66`); make it editable per fleet. A real lever, not metadata.

No-channel-needed controls available now:
- **Bulk select + move/unassign** ✅ · **force-end a stale session** (set
  `ended_at`, clean the roster) 🟡 · **pin a friendly agent name** (today `title`
  is prompt-derived, `active_sessions.py:98`) ✅ · **drag-and-drop between
  fleets** (replace the dropdown at `FleetPage.tsx:170-208`) ✅.

### 3. Collaborate — each agent pulls from the others

- **Fleet knowledge bus.** 🟡 Docs are already `fleet_session_id`-scoped. Inject
  the fleet's recent docs as candidate context into every member's next
  `/discover`, so agent B gets agent A's decision *immediately*, not via eventual
  semantic match.
- **Collision guard.** 🟡 Flag when two live agents' `files_touched` overlap on
  the same repo/branch — "⚠️ A and B both editing billing.py." This alone
  justifies a multi-agent control plane.
- **"Send context to →".** 🔶 In agent detail, push agent X's active document
  into agent Y's (or a fresh session's) next discover. Literal "pull from another
  agent."
- **Continuous fleet digest** — one synthesized "what this fleet accomplished"
  doc, the fleet's collective memory. 🟡

### 4. Carry — flexible, movable across sessions / terminals / VMs

Fleet's empty state already promises "context carries across terminals and VMs"
(`FleetPage.tsx:824`). Make it real:
- **Resume / clone a session.** 🟡 The archive has everything (cwd, branch,
  active + referenced docs, summary). Emit a `tf resume <session_id>` command /
  deep link that seeds a *new* terminal with that context — pick up a crashed or
  closed agent exactly where it stopped. **The flagship "movable" feature.**
- **Hand off to a teammate.** 🟡 Same bundle, scoped to an org user
  (`visibility=organization` docs already exist, `observe.py:354`). "Hand this
  session to a colleague."
- **Promote session → specialist profile.** 🟡 A productive session becomes a
  reusable profile (routing already exists). "This agent nailed billing — save it
  as the Billing specialist."

### 5. Feel — fluid + powerful

- **Realtime roster** via SSE/WebSocket instead of the 30s poll; pulse the dot
  when an `/observe` lands. 🔵
- **Filter / group** by repo · branch · model · specialist · status. ✅
- **Raise `ROSTER_LIMIT` + paginate** — prerequisite for fleet-scale. 🟡

## Sequencing

- **Now** (data already there, pure surfacing): live cost/token/savings rollup ·
  "currently editing" files · capture-paused reasons · stall badge · friendly
  rename · bulk move · raise/paginate the 5-agent cap.
- **Next** (server-side, no agent change): per-fleet cost cap · collision guard ·
  fleet knowledge bus · resume/handoff bundle · force-end stale sessions.
- **Bets** (multipliers): the **directive channel** on `/discover`
  (pause/resume/stop/broadcast/reassign + "send context to") · realtime
  transport · promote-to-specialist.

## Why this is *the* sell feature

The thesis is **capture + seams + ROI**. Fleet is where all three become visible
and operable at once: the cost/savings rollup *is* the ROI ledger live; the
knowledge bus + collision guard *are* the seams; resume/handoff *is* capture made
portable across terminals, VMs, and teammates. Competitors ship memory ops —
almost nobody ships a **mission-control plane that observes, steers, and hands off
a live multi-agent fleet.** That is the differentiated wedge.

## Open questions

- Directive channel: deliver on `/discover` only, or add a dedicated poll for
  lower latency? How does the local hook *apply* a directive (inject as context
  vs. true harness control like stop)?
- Resume bundle: deep link that prints a `tf resume` command, or a one-shot token
  the hook redeems on first discover?
- Should demo and real sessions stay merged in Fleet, or split
  (`active_sessions.py:247`)?
- Per-fleet cost cap: hard stop vs. warn-and-continue when exceeded?

## Related tickets / prior art

- TF-225 active-sessions roster · TF-227 Fleet agent roster · TF-229 fleet
  session membership · TF-178 observe orchestrator · TF-181 structured observe
  payload.
