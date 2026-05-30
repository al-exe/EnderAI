# Library Document Organization Sharing Handoff

Saved: 2026-05-19

## User Request

Implement library/document organization so documents can be organized into folders and assigned/shared with other organization members.

User paused due to token budget. Continue later from this state.

## Repository State

Backend/API repo:
- Path: `/home/alexlee/dev/EnderAI`
- Branch: `feature/library-document-organization-sharing`
- Base: tracks `origin/main`
- Not committed or pushed.
- There are unrelated local planning files from earlier backlog capture:
  - `.planning/ROADMAP.md`
  - `.planning/phases/`

Frontend repo:
- Path: `/home/alexlee/dev/taskforce-codex`
- Remote: `git@github.com:al-exe/EnderAI-frontend.git`
- Branch: `feature/library-document-organization-sharing`
- Base: tracks `origin/main`
- Not committed or pushed.

## Backend Work Completed

Files changed in `/home/alexlee/dev/EnderAI`:
- `demo/full-stack-fastapi-template/backend/app/models.py`
- `demo/full-stack-fastapi-template/backend/app/core/v2_documents.py`
- `demo/full-stack-fastapi-template/backend/app/api/routes/v2_documents.py`
- `demo/full-stack-fastapi-template/backend/tests/api/test_v2_documents_api.py`
- `demo/full-stack-fastapi-template/backend/tests/conftest.py`
- `demo/full-stack-fastapi-template/backend/app/alembic/versions/e9f1b2c3d4a5_add_v2_document_folders_and_member_shares.py`

Implemented:
- Added `V2DocumentFolder` table for flat library folders.
- Added `V2DocumentShare` table for explicit per-member shares.
- Added `folder_id` to `V2Document`.
- Added folder create/list/update/delete endpoints under `/api/v1/v2/documents/folders/`.
- Added share get/replace endpoints under `/api/v1/v2/documents/{document_id}/shares/`.
- Extended document responses with:
  - `folder_id`
  - `folder_name`
  - `visibility`
  - `user_access`
  - `shared_with`
- Kept existing organization visibility behavior.
- Added access resolution:
  - owner: full management
  - organization visibility: editor for same-org users
  - explicit share `editor`: can edit content
  - explicit share `viewer`: read-only
- Restricted folder assignment and share assignment to accessible org/user scope.
- Added tests for:
  - folder create/list/assign/unassign/rename
  - explicit editor share
  - viewer read-only share
  - rejecting shares outside owner org

Validation already run:
- Backend ruff on changed backend files: passed after import fix.
- Backend compileall: passed.

Validation not yet run:
- Backend pytest, because previous local pytest attempts were blocked by local Postgres not running on `localhost:5432`.

Known backend follow-up:
- Re-run ruff/compileall once more after resuming.
- If Postgres is available, run:
  `PROJECT_NAME=EnderAI POSTGRES_SERVER=localhost POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres POSTGRES_DB=app FIRST_SUPERUSER=admin@example.com FIRST_SUPERUSER_PASSWORD=notdefaultpassword .venv/bin/python -m pytest tests/api/test_v2_documents_api.py tests/api/test_organizations_api.py`

## Frontend Work Completed

Files changed in `/home/alexlee/dev/taskforce-codex`:
- `src/api/v2Documents.ts`
- `src/api/organizations.ts`
- `src/routes/v2/library.tsx`
- `src/routes/v2/library.$documentId.tsx`

Implemented so far:
- Added typed wrappers for folders and document shares.
- Added typed `readMyOrganization()` API wrapper.
- Library page now:
  - loads folders
  - creates folders
  - shows folder nav with All/Unfiled/folders
  - filters documents by folder
  - shows document access badges and folder name on cards
- Document detail page now:
  - loads folders
  - loads organization members for owners
  - loads shares for owners
  - has Share dialog with member checkbox and viewer/editor permission select
  - lets owners edit folder assignment and visibility in metadata
  - hides edit controls for viewer-only docs

Validation not yet run:
- Frontend TypeScript build.
- Frontend Playwright tests.

Known frontend follow-up:
- Update `tests/fixtures/v2-documents.ts` with new document response fields:
  - `owner_id`
  - `organization_id`
  - `folder_id`
  - `folder_name`
  - `visibility`
  - `user_access`
  - `shared_with`
- Update the live document fixture in `tests/taskforce-shell.spec.ts` with the same fields.
- Mock:
  - `GET /api/v1/v2/documents/folders/`
  - `GET /api/v1/organizations/me`
  - `GET /api/v1/v2/documents/{id}/shares/`
  where tests enter owner-only screens.
- Run `npm run build` or `bun run build` in `/home/alexlee/dev/taskforce-codex`.
- Fix any TS/lint fallout from the newly added UI.

## Next Steps

1. Resume on backend first:
   - `cd /home/alexlee/dev/EnderAI`
   - `git status --short --branch`
   - Run ruff/compileall.
   - Fix any backend issues.

2. Resume frontend:
   - `cd /home/alexlee/dev/taskforce-codex`
   - `git status --short --branch`
   - Update fixtures/mocks.
   - Run frontend build.
   - Fix TypeScript and test issues.

3. Commit each repo separately on the existing feature branch.

4. Push both branches and open PRs:
   - Backend repo: `EnderAI`
   - Frontend repo: `EnderAI-frontend`

5. Do not merge unless Alex explicitly asks after PR creation/validation.

## Important Constraints

- Do not use Jira/Atlassian.
- Do not use EnderAI/Taskforce MCP tools.
- Do not commit local planning docs into product repos.
- Code must go through PR before landing on `main`.
- Do not wait on deploy results unless Alex explicitly asks.
