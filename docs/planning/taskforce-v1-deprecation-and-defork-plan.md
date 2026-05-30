# V1 Deprecation + De-fork — Execution Plan

*2026-05-30. Decisions: V1 deprecated, de-fork approved (Alex). Companion to `taskforce-codebase-audit.md`.*
*Backend currently at `EnderAI/demo/full-stack-fastapi-template/backend/` (→ target `EnderAI/backend/`).*

> **Status:** approved; **execution deferred** to a later session (Alex, 2026-05-30). Living source of truth — keep updated as decisions evolve; resume at *Prerequisites* when executing.

> **Key finding that de-risks this:** V2 imports **zero** V1 code (`core/metrics`, `core/v2_documents`, `v2_documents.py`, `v2_metrics.py` have no topics/cases/skills imports). V1 is severable. **Skills is V1-coupled** (`Skill.source_topic_id`/`source_case_ids`) → cut with V1.

## Prerequisites (confirm before any deletion)
- [ ] **All users on V2.** `User.v2` is a rollout flag. Flip it on for 100% (or confirm already universal) **before** removing the V1 UI/endpoints — otherwise V1-flag users get a dead app.
- [ ] **No V1 prod data to preserve.** The drop-tables migration is irreversible. Confirm topics/cases/skills hold nothing worth exporting first (or export to a one-off dump).
- [ ] **PR workflow:** branch from `origin/main` (current local branch `feature/nested-document-folders` is `[gone]` on origin — likely merged; verify before branching). All changes via PR; no direct main pushes.

## Part A — Cut V1 (do first; self-contained, no deploy-path risk)
Order matters: stop *callers* before removing *endpoints* before dropping *tables*.

**PR A1 — remove V1 usage (frontend + MCP):**
- Frontend: delete `routes/_layout/{cases,topics,skills}.tsx`, `routes/v2`-ify defaults, delete `components/{Cases,Topics,Skills}/`, remove sidebar links. Ship; confirm V2 is the only surface.
- MCP: remove `enderai_begin_case/update_case/finish_case` tool handlers from `mcpServer.ts`; delete `skillSync.ts`; keep all `taskforce_*` document tools. Update `test/caseWorkflowTools.test.ts` (delete or repoint).

**PR A2 — remove V1 backend code:**
- `api/main.py`: drop `include_router` for `topics, cases, search, context_packs, skills`.
- Delete `api/routes/{topics,cases,context_packs,search,skills}.py`; `core/{topics,cases,search,skills}.py` + context-pack builder; V1 demo seeding in `core/demo.py`.
- `models.py`: delete `Topic, CaseRecord, CaseEvent, Skill` tables + all V1 DTOs (`TopicPublic`, `CasePublic`, `ContextPack*`, `Skill*`, `CommandRecord`, `HypothesisRecord`, etc.). Keep `User/Organization/AgentCredential/V2Document*/Metrics*`.
- Verify: importlib sweep over `app/**` (per the package-shadows-module lesson), boot locally on prod's Dockerfile Python version, run the suite.

**PR A3 — drop V1 tables (migration, last):**
- New Alembic migration dropping `topic, case_record, case_event, skill` (+ any V1-only indexes). Reversible `downgrade` recreating empty tables for rollback sanity (addresses the CONCERNS "no migration safety rails" flag).
- Deploys with the normal backend release (entrypoint runs `alembic upgrade`).

## Part B — De-fork the directory (separate PR; needs Render coordination)
**PR B1 — move + repath (in-repo, mine to do):**
- `git mv demo/full-stack-fastapi-template/backend → backend` (preserve history). Remove the now-empty `demo/full-stack-fastapi-template/` shell.
- Repath: `backend/Dockerfile` (WORKDIR/COPY), `entrypoint.sh`, `scripts/prestart.sh`, `alembic.ini`/`alembic/env.py` if path-bound, `.gitignore`, the planning/`docs/*` references, and **delete the dead `.github/workflows/deploy-frontend-pages.yml`** (it targets a nonexistent `frontend/` dir).
- MCP is unaffected (stays at `mcp/enderai-api-mcp`).

**⚠️ PR B1 merge = coordinated with Render (Alex):**
- Update backend service **Root Directory**: `demo/full-stack-fastapi-template/backend` → `backend`. Recheck Docker build context + build/start commands. Merge + dashboard flip together, then watch one deploy.

**PR B2 — doc/CI cleanup:** rewrite the stale template `backend/README.md`, fix `docs/architecture-overview.md` paths, add the missing `.env.example` and a backend CI workflow (the no-regret hygiene items from the audit) now that paths are stable.

## Sequencing & rollback
1. Prereqs → **A1 → A2 → A3** (V1 gone, no deploy-path risk).
2. Then **B1 (+ Render flip) → B2** in a window you can watch.
- Rollback: A-series reverts cleanly (downgrade recreates tables); B-series rollback = revert PR **and** flip Render root-dir back.

## Open items
- Re-home the "reusable artifact" concept onto `V2Document` later? (Skills' only redeeming idea.) Out of scope for the cut; note for the axis decision.
- Fold in the audit's no-regret adds (provenance envelope, secret-scrub, MCP hardening) *after* the repo is clean — easier on de-forked paths.
