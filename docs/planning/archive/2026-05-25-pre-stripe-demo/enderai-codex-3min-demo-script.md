# EnderAI + Codex Demo Script

Goal: record a sub-3-minute engineering demo where Codex uses EnderAI end to end on a real backend task: global search currently returns Topics and Cases, while the frontend already expects generated Skills too.

## Pre-Recording Setup

- Use `/home/alexlee/dev/EnderAI` as the Codex working directory.
- Keep the backend bug unfixed before recording. In this branch, `app/core/search.py` and `app/models.py` only model Topic/Case search results.
- No production DB seed is needed for the UI demo. EnderAI demo mode lazily seeds demo Topics, Cases, and Skills per user.
- A live generated Skill is already prepared for the Codex MCP flow: `Global Search Skills Backend Workflow`, id `7fa1da5d-9f15-427a-9a1f-e032887628fd`.
- If you show the app UI, turn on `Demo mode` and search for `pgbouncer` after the fix to show a deterministic skill result.

## Paste This Prompt Into Codex

```text
Use EnderAI. In /home/alexlee/dev/EnderAI, fix backend global search so generated Skills are returned alongside Topics and Cases.

The frontend already expects a skills group and /skills?skillId=... routing in EnderAI-frontend, but this backend branch only returns Topics and Cases.
≈
Start with enderai_begin_case, hydrate prior context, then call enderai_use_skill before editing. Add focused backend test coverage and run only the targeted search tests. Do not use Jira, do not open a PR, and keep scope to backend search models/core/tests.
```

## Expected Codex Flow

1. `enderai_begin_case` creates a new Case under the existing global-search Topic and hydrates prior context.
2. ContextPack should surface the prior Case `Global search should return Skills`.
3. `enderai_use_skill` should return `Global Search Skills Backend Workflow` and sync a local Skill markdown file.
4. Codex inspects `app/models.py`, `app/core/search.py`, and `tests/api/test_search_api.py`.
5. Codex patches the backend search response shape to include Skills and adds a regression test.
6. Codex runs `uv run pytest tests/api/test_search_api.py -q`.
7. `enderai_update_case` records findings, changed files, and test evidence.
8. `enderai_finish_case` closes the Case with the outcome.

## Voiceover Timeline

0:00-0:15: “This is Codex doing a normal engineering task. EnderAI is the memory layer behind it, not a separate chat app.”

0:15-0:40: Paste the prompt. Let the `enderai_begin_case` call be visible. Say: “EnderAI starts a Case, reuses the right Topic, and hydrates prior work before Codex edits anything.”

0:40-1:05: Let `enderai_use_skill` be visible. Say: “Now Codex asks for generated Skills. This Skill was generated from previous Cases, so it carries the checklist, known files, prior outcomes, and guardrails.”

1:05-1:45: Show Codex inspecting and patching. Say: “The actual bug is simple: frontend search already has a Skills group, but this backend response only knows Topics and Cases. Codex uses the prior context to make a narrow backend fix.”

1:45-2:20: Show the targeted pytest command passing. Say: “The validation is scoped. It adds coverage for the behavior and only runs the relevant search tests.”

2:20-2:45: Show `enderai_finish_case`. Say: “The work closes back into EnderAI as a Case with files, commands, changes, and outcome, so the next agent does not start cold.”

2:45-3:00: Optional browser proof. Show EnderAI global search with `pgbouncer` in demo mode returning Topics, Cases, and Skills. Say: “That loop is the product: prompt, Topic, Case, generated Skill, code change, validation, and reusable memory.”

## Screen Guidance

- Keep the Codex terminal dominant. The interesting proof is the visible MCP tool chain and patch/test loop.
- If showing the browser, use it only at the end. Do not spend time logging in during the recording.
- Keep narration sparse. Let the tool calls show the system working.
- Do not explain the database. Say “demo mode seeds deterministic Topics, Cases, and Skills” once if needed.

## Backup Lines

- If `enderai_use_skill` returns more than one match: “EnderAI ranked the generated Skills from the hydrated context; Codex is using the top match as advisory guidance.”
- If tests take too long: cut after the targeted command starts, then resume when it finishes.
- If the app UI is not ready: skip the browser proof. The Codex tool flow already shows Topic, Case, Skill, update, and finish.
