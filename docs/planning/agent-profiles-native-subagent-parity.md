# Agent Profiles → Native Subagent Files (Cursor parity + inject)

*Planning doc. Status: design locked on the key forks (2026-07-01), pre-build.*

## Goal

Reach ~80% functional parity with Cursor's agent-customization surface **without diluting our moat**, and in doing so close the **inject** half of the Taskforce loop: an earned/curated Taskforce **agent profile** should materialize as a **native subagent file** that Claude Code, Codex, and Cursor read directly.

Thesis tie-in (north-star §): the moat is the *accruing, earned record*, not the config knobs. Cursor's subagent files are hand-written commodity. Ours can be **emitted from earned profiles + curated library documents** and pushed back into every harness. Cursor can't reciprocate — they have nothing to earn from. Bias order for harness support: **Claude Code → Codex → Cursor.**

## Cursor vs. us (condensed)

Cursor's analog to our profile is the **custom subagent** (`.cursor/agents/*.md`, `~/.cursor/agents/*.md`) — frontmatter `name`, `description` (routing signal), `model` (`inherit`|id), `readonly`, `is_background`; body = system prompt; tools inherited unless `readonly`/policy restricts. Notably Cursor also reads `.claude/agents/` and `.codex/agents/`.

| | Cursor subagent | Taskforce `AgentSpecialist` |
|---|---|---|
| name / description / instructions | ✅ | ✅ (`name`, `role`, `short_description`, `instructions[]`) |
| routing / negative routing | description prose | ✅ `routing_triggers` + `negative_triggers` + `domain_tags` |
| **model binding** | ✅ | ❌ → **add `model_hint`** |
| **tool/permission scope** | ✅ `readonly` | ❌ → **add `permission_scope`** |
| curated knowledge | rules/skills refs | ✅ `linked_knowledge` (docs w/ anchors, reasons, `is_pinned`) |
| **earned / provenance** | ❌ hand-written | ✅ `created_from`, `evolution_provenance` |
| **reputation / ledger** | ❌ | ✅ invocations, tokens/USD saved, reuse rate, recent invocations |
| org sharing | repo-committed | ✅ `visibility` |
| emit as harness file | ✅ (is the file) | ❌ → **build exporter** |

We win on earned/reputation/knowledge; we're behind on model+permission binding and on being an *executable, injectable* file. The pareto pick closes exactly those.

## Locked decisions (from design Q&A)

1. **Sync model:** *Both* — an explicit "Sync to harness" action **and** hook-driven auto-refresh each session (extends existing per-harness bundles).
2. **Assigned-doc payload in the file:** *Embed the doc's AI-friendly Details + a backlink.* Compact, useful offline, full body still hydratable by the live hook.
3. **Assign UX:** *Both directions* — "Add documents" picker on the agent page **and** "Add to agent" on a library document.
4. **Document model:** **Summary = human-readable** (Confluence/Notion/Docs style), **Details = AI-friendly** (frontmatter/metadata, inject-ready). **Remove the Split view** and evidence-anchoring for now.
5. **Section name in emitted files:** **"Documents"** (never "runbooks").
6. **Harness priority:** Claude Code → Codex → Cursor.

## Workstreams

### WS1 — Agent profile config fields + editable context
- **`AgentSpecialist.model_hint: str`** (default `"inherit"`). Free-ish string mapping to harness model aliases (`inherit`/`sonnet`/`opus`/`haiku` for Claude; passthrough for others).
- **`AgentSpecialist.permission_scope: str`** (`"readonly"` | `"full"`, default `"readonly"`). Earned profiles default safe.
- Make **`instructions[]`, `routing_triggers`, `negative_triggers`** editable via PATCH + UI (today they're seed/earned-only; the edit dialog only touches name/role/short_description/tags/status). "Edit the subagent context" = edit these.
- API: extend `AgentSpecialistUpdate` (backend + `src/api/v2Agents.ts`) with `model_hint`, `permission_scope`, `instructions`, `routing_triggers`, `negative_triggers`.

### WS2 — Library document ↔ agent assignment
Reuse the existing join table **`AgentSpecialistDocumentLink`** (`specialist_id`, `document_id`, `anchor_id`, `reason`, `weight`, `is_pinned`). Manual assignment = a link with `is_pinned=true`, `reason="added by <user>"` — cleanly distinct from earned links (which the compounding job writes with `reason="earned: …"`).
- **New endpoints** on `agents.py`:
  - `POST /v2/agents/{slug}/documents` `{document_id, reason?}` → upsert pinned link.
  - `DELETE /v2/agents/{slug}/documents/{document_id}` → unlink.
  - (list already flows through `linked_knowledge` in the detail response.)
- **UI, both directions:**
  - Agent detail page: replace the read-only "Linked knowledge" with an editable **Documents** section — an "Add documents" button opens a library picker (search by title/description, filter by folder/favorite; multi-select). Rows show remove + pin.
  - Library document: an **"Add to agent"** control (reuses the same link endpoint).
- Guardrail: cap manual pins per profile (reuse `MAX_LINKS_PER_SPECIALIST`, keep pinned first — mirrors earned-profiles design).

### WS3 — Document model redo (human / AI split)
The fields largely exist; the **Details** semantics and the view change.
- **Summary (human-readable)** ← `main_body` narrative. Render like a normal doc (Notion/Confluence feel). `human_summary`/`description` stay as the one-line abstract for cards/listing.
- **Details (AI-friendly)** ← repurpose `details_markdown_sections` into a single inject-ready markdown payload with an optional **frontmatter/metadata** block (the structured context an agent consumes). This is what the exporter embeds.
- **Remove the Split view + evidence anchoring for now:** drop `viewMode === "split"`, `anchorMode`, `summaryPick`/`detailsPick`, `confirmAnchor`, `AnchorHelper`, "Link evidence"/"Confirm anchor", the auto-split `showEvidence`, and the hash→evidence scroll. `ViewMode` becomes `"summary" | "details"` (two tabs).
- Migration: keep existing `details_markdown_sections`/`evidence_anchor_id` data in place (revertable); stop rendering the split interaction. Fold `ai_generated_summary` into the Details payload or keep as its short abstract (decide in build).
- **Reconciliation with WS4:** "embed summary + backlink" = embed the doc's **Details (AI-friendly)** content + backlink to the human Summary.

### WS4 — Exporter → native subagent files
An `AgentSpecialist` → harness-file writer, slotting into the existing per-harness bundles (`app/assets/taskforce-hooks/` = Claude, `taskforce-codex-hooks/`, `taskforce-cursor-hooks/`).
- **Canonical target = `.claude/agents/<slug>.md`.** Bonus: Cursor also reads `.claude/agents/`, so one canonical file already covers Claude Code + Cursor; mirror to `.cursor/agents/` only if a Cursor-specific field is needed.
- **Codex:** verify current Codex subagent support before building. If `.codex/agents/*.md` isn't natively consumed, fall back to a scoped section in `AGENTS.md` via the existing `taskforce-codex-hooks`. (Flag — see open questions.)
- **Two triggers:** (a) on-demand "Sync to harness" action on the agent; (b) hook auto-refresh — the installed prompt-submit hook re-materializes changed profiles each session (idempotent write; only rewrite on content-hash change).
- **Field mapping (Claude Code):**
  - `name` ← `slug` (lowercase-hyphen)
  - `description` ← `short_description` + `Use when: {routing_triggers}` + `Do NOT use when: {negative_triggers}`
  - `model` ← `model_hint`
  - `tools` ← from `permission_scope` (`readonly` → `Read, Grep, Glob, WebFetch`; `full` → omit to inherit)
  - body ← `instructions[]`, then a **`## Documents`** section built from pinned `linked_knowledge` (title + one-line purpose + embedded **Details** excerpt + backlink)

### WS5 — Emitted file format (canonical, Claude Code)

```markdown
---
name: billing-specialist
description: |
  Use for Stripe billing & webhooks.
  Do NOT use for refunds UI or dunning emails.
model: sonnet
tools: Read, Grep, Glob, WebFetch
---
You own Stripe billing & webhooks. Prefer idempotent handlers;
never trust unverified events.

## Documents
### Webhook signature verification
Verify every event with STRIPE_WEBHOOK_SECRET before parsing; reject on skew > 5m.
↳ taskforce.tools/v2/library/abc

### Refund idempotency notes
Key refunds by charge_id; retries must no-op.
↳ taskforce.tools/v2/library/def
```
Under each `### <doc title>` we embed the doc's **Details (AI-friendly)** content (bounded by a token budget); the `↳` backlink points to the human-readable Summary. The live hook can hydrate full bodies at prompt time.

## Sequencing

1. **WS3** document redo (Details = AI-friendly, drop Split) — unblocks a clean embeddable payload.
2. **WS1** config fields + editable context.
3. **WS2** doc↔agent assignment (link CRUD + both-direction UI).
4. **WS4/WS5** exporter + emitted format, Claude Code first (covers Cursor for free), then Codex, then Cursor-specific.
5. Wire on-demand + hook auto-refresh; verify with an installed harness.

## Open questions
- **Codex subagent surface:** does current Codex read `.codex/agents/*.md`, or is `AGENTS.md` the reliable inject path? Verify before WS4 Codex step.
- **Token budget** for embedded Details per doc and per file (start conservative; prune lowest-weight, keep pinned).
- **`ai_generated_summary`** fate in the redo — fold into Details vs. keep as short abstract.
- **`model_hint` translation** per harness (aliases differ across Claude/Codex/Cursor).
- Auto-refresh writing into a user's repo: guard behind opt-in + only touch `.<harness>/agents/` we own (never clobber hand-written files with the same slug — namespace or `taskforce-` prefix?).
