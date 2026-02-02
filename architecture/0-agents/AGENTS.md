# EnderAI — Layer 0 Agent Rules (Repo-Wide)

Last updated: 2026-02-02 05:46 UTC

These rules define the highest-precedence behavior for any agent operating in this repository.
EnderAI’s differentiator is **continuity with trust**: past work informs the present, and present work teaches the future — but only through explicit, scoped, inspectable memory.

Optional overrides (if present): `level-0-agents/agents.override` (takes precedence over this file).

## Memory Layers (Canonical)
- **Layer 0 — Rules Context:** `AGENTS.md` (this file)
- **Layer 1 — Ground Truth:** `architecture/1-ground-truth/` (citeable facts captured for the task)
- **Layer 2 — Knowledge Base:** `architecture/2-knowledge-base/` (curated, reusable context; not guaranteed 1==1)
- **Layer 3 — Task Context:** `architecture/3-task-context/` (in-flight notes and experiments to unblock execution)

## Rules (Descending Importance)
1) **User control + least privilege**
   - Default to read-only behavior and reversible actions.
   - Treat anything with external side effects as “risky” (deploys, prod access, DB writes, pushing branches, opening PRs, schema changes, deleting data/files) and require explicit user confirmation before proceeding.
   - Never store secrets in repo docs; redact tokens/keys and store references instead.

2) **Ground truth + audit trail (timestamped)**
   - Don’t guess: if an answer matters, anchor it in ground truth (code, tests, tool output, or recorded Layer 1 artifacts).
   - Capture enough evidence to replay the work: commands tried, key outputs/errors, and code pointers (file paths + important symbols).
   - Timestamp any notes/artifacts you create or materially update (prefer UTC).

3) **Layer 1 first; Layer 2 only after completion; Layer 3 during execution**
   - Before starting a user-defined task/ticket, consult `architecture/1-ground-truth/`; if it’s missing or stale, add new ground truth or mark older entries as superseded.
   - Use `architecture/2-knowledge-base/` to accelerate execution, but treat it as non-authoritative and overrideable.
   - Do not write to `architecture/2-knowledge-base/` while a task is in progress; only update the knowledge base after the user confirms the task/ticket is completed.
   - During the task, write `.mdc` notes in `architecture/3-task-context/` as needed to unblock progress (code pointers, workarounds, commands tried, what worked, what failed, and why).

4) **Freshness and pruning (7-day TTL for Layer 2/3)**
   - For `.mdc` files in `architecture/2-knowledge-base/` and `architecture/3-task-context/`, include `Created` and `Last used` (or `Last reviewed`) dates.
   - Update `Last used` when the file meaningfully helps current work.
   - Prune, refresh, or consolidate anything in Layer 2/3 not used in the last **7 days**.

5) **Documentation hygiene**
   - Read relevant docs before answering or changing code, then keep them accurate and runnable.
   - If behavior/workflows change, update the corresponding docs in the same patch.
   - Remove or consolidate stale/duplicated docs; keep one canonical source whenever possible.

6) **Do updates before responding (with one exception)**
   - When a request implies repo changes (docs/code/memory artifacts), make the change first, then respond with pointers to the updated files.
   - Exception: Layer 2 updates are deferred until completion per Rule 3.
