# EnderAI.xyz Taskforce V2-Only Migration Plan

## Goal

Move `enderai.xyz` from the legacy EnderAI product surface to the Taskforce V2 product surface as the default and only public app experience.

The intended product shape is:

- Primary app: Taskforce V2.
- Primary navigation: Search, Library, Agents, Metrics, Upgrade, Settings/User.
- Legacy concepts hidden from normal users: Topics, Cases, legacy global search, legacy Home.
- No visible "Taskforce" mode switch. Users should not choose between EnderAI V1 and Taskforce V2.
- Keep backend/API paths as they are for now, including `/api/v1/v2/...` and frontend `/v2/...` routes if that avoids backend churn.

## Current Frontend State

Inspected worktree:

`/home/alexlee/dev/WORKTREE-taskforce-community-upgrade-org-removal-frontend`

Current branch:

`feature/community-upgrade-tab`

Relevant files:

- `src/routes/index.tsx` renders `HomePage mode="public"` at `/`; public copy still centers Topics/Cases.
- `src/routes/_layout.tsx` is the authenticated legacy shell with `AppSidebar` and `GlobalSearchBar`.
- `src/components/Sidebar/AppSidebar.tsx` exposes Home, Topics, Cases, Skills, optional Admin, plus `V2ModeSwitch`.
- `src/components/Sidebar/ModeSwitches.tsx` defines `V2ModeSwitch`, which navigates between `/home` and `/v2/library`.
- `src/routes/v2.tsx` is the Taskforce V2 authenticated shell and still blocks users when `currentUser.v2` is false.
- `src/components/V2/TaskforceShell.tsx` exposes Search, Library, Agents, Metrics, Upgrade, optional Admin, plus an active `V2ModeSwitch` that returns to `/home`.
- `src/routes/v2/index.tsx` already redirects `/v2/` to `/v2/library`.
- `src/hooks/useAuth.ts`, `src/routes/login.tsx`, `src/routes/signup.tsx`, `src/routes/recover-password.tsx`, and `src/routes/reset-password.tsx` still redirect logged-in users to `/home`.
- Legacy direct routes exist under `_layout`: `/home`, `/topics`, `/cases`, `/skills`, `/admin`, `/settings`.
- V2 direct routes exist under `/v2`: `/v2/search`, `/v2/library`, `/v2/library/$documentId`, `/v2/agents`, `/v2/metrics`, `/v2/metrics/methodology`, `/v2/pricing`, `/v2/admin`.

## Product Decisions

1. Canonical signed-in landing page should be `/v2/library`.

Library is the best default because it is the durable workspace where Taskforce documents are visible. Search, Agents, and Metrics stay one click away in the shell.

2. Keep `/v2` route names and API names temporarily.

The migration should be UI/navigation-first. Renaming APIs or removing `/v2` can happen later after the product surface is stable.

3. Hide legacy V1 UI from normal navigation before deleting it.

Topics/Cases/Skills can stay in code temporarily, but users should not reach them through default redirects, public copy, primary nav, or the Taskforce shell. Direct legacy URLs should redirect or be quarantined.

4. Remove the Taskforce switch.

`V2ModeSwitch` should disappear from both the legacy shell and the Taskforce shell. Once V2 is the default app, the switch is conceptually wrong.

5. Decide how to handle users where `currentUser.v2` is false.

If all live users should now see Taskforce, the backend should already return `v2: true` for them or the frontend should stop treating `v2` as an access gate. If some users should still be blocked, send them to `/v2/pricing` or a membership/no-access screen instead of the legacy `/home` app.

## Migration Phases

### Phase 1: Make Taskforce V2 the Default Entry Point

Change all authenticated success and already-authenticated redirects from `/home` to `/v2/library`.

Files to update:

- `src/hooks/useAuth.ts`
- `src/routes/login.tsx`
- `src/routes/signup.tsx`
- `src/routes/recover-password.tsx`
- `src/routes/reset-password.tsx`
- `src/routes/_layout/admin.tsx` if the legacy admin route stays temporarily

Expected behavior:

- Login, Google login, signup, and already-logged-in auth pages land at `/v2/library`.
- `/v2/` continues redirecting to `/v2/library`.
- Unauthenticated `/v2/*` still redirects to `/login`.

### Phase 2: Remove the Visible Mode Switch

Remove `V2ModeSwitch` from:

- `src/components/Sidebar/AppSidebar.tsx`
- `src/components/V2/TaskforceShell.tsx`

Then remove or leave unused temporarily:

- `V2ModeSwitch` in `src/components/Sidebar/ModeSwitches.tsx`

Expected behavior:

- Taskforce shell no longer shows a switch that returns users to `/home`.
- Legacy shell no longer advertises Taskforce as a separate mode.
- Tests that query `data-testid="v2-mode-switch"` should be rewritten or removed.

### Phase 3: Make the Public Surface Taskforce-Oriented

The current `/` route uses `HomePage` copy built around Topics/Cases. Replace that public copy with Taskforce V2 positioning, or redirect signed-in users directly to `/v2/library` and keep only unauthenticated marketing/signup content.

Files to update:

- `src/routes/index.tsx`
- `src/components/Home/HomePage.tsx`
- `tests/home-docs.spec.ts`

Options:

- Minimal: keep `HomePage`, rewrite visible copy and CTAs to Search, Library, Agents, Metrics, and membership.
- Cleaner: create a new Taskforce public landing component and stop using the legacy `HomePage` for `/`.

Expected behavior:

- Public enderai.xyz no longer says Topics/Cases are the product.
- Signed-in users who visit `/` should be redirected to `/v2/library` instead of seeing legacy public content.

### Phase 4: Retire the Legacy Authenticated Shell

The legacy `_layout` shell currently exists to host `/home`, `/topics`, `/cases`, `/skills`, `/admin`, and `/settings`.

Recommended approach:

- Keep `_layout/settings` only if it has user/account controls not yet present in Taskforce shell.
- Move settings access into the Taskforce shell through the user menu or a Taskforce nav item.
- Redirect `/home`, `/topics`, `/cases`, and `/skills` to `/v2/library`.
- Redirect legacy `/admin` to `/v2/admin` for superusers.

Files to evaluate:

- `src/routes/_layout.tsx`
- `src/routes/_layout/home.tsx`
- `src/routes/_layout/topics.tsx`
- `src/routes/_layout/cases.tsx`
- `src/routes/_layout/skills.tsx`
- `src/routes/_layout/admin.tsx`
- `src/routes/_layout/settings.tsx`
- `src/components/Sidebar/AppSidebar.tsx`
- `src/components/Search/GlobalSearchBar.tsx`

Expected behavior:

- Normal signed-in app chrome is always `TaskforceShell`.
- Users cannot navigate to Topics/Cases/Skills from visible UI.
- Old bookmarks do not 404; they redirect to the closest Taskforce destination.

### Phase 5: Adjust V2 Access Handling

Current `src/routes/v2.tsx` throws an error if `currentUser.v2` is false and shows `TaskforceNoAccess`, which links back to `/home`.

Plan:

- Replace the `/home` fallback in `TaskforceNoAccess`.
- Decide whether `currentUser.v2` remains a real entitlement gate.
- If it remains, route blocked users to `/v2/pricing` or a membership screen.
- If Taskforce is available to all users, remove the `!currentUser.v2` block from the frontend route guard.

Expected behavior:

- There is no path from V2 no-access state back to legacy V1.
- A user who cannot access Taskforce sees a membership/account action, not the old app.

### Phase 6: Update Tests Around the New Contract

Tests that currently assert Topics/Cases as the default product should change.

Known test areas:

- `tests/login.spec.ts`
- `tests/home-docs.spec.ts`
- `tests/topics-cases-ui.spec.ts`
- `tests/global-search.spec.ts`
- `tests/taskforce-shell.spec.ts`

New assertions:

- Login lands on `/v2/library`.
- Sidebar shows Search, Library, Agents, Metrics, Upgrade.
- Sidebar does not show Topics, Cases, Skills, or the Taskforce switch.
- `/v2/library`, `/v2/search`, `/v2/agents`, `/v2/metrics`, and `/v2/pricing` are reachable.
- `/home`, `/topics`, `/cases`, and `/skills` redirect to `/v2/library` or another chosen V2 destination.
- Public `/` no longer presents Topics/Cases copy.

### Phase 7: Cleanup After Verification

After the V2-only contract is stable in production:

- Delete unused legacy components if no route imports them:
  - `src/components/Home/HomePage.tsx`
  - `src/components/Topics/TopicsPage.tsx`
  - `src/components/Cases/CasesPage.tsx`
  - `src/components/Search/GlobalSearchBar.tsx`
  - legacy CSS modules tied only to those pages
- Delete unused legacy API wrappers if no frontend code imports them:
  - `src/api/topics.ts`
  - `src/api/cases.ts`
  - legacy search API wrappers
- Remove stale Playwright coverage that only tested V1 behavior.

Do this as a separate cleanup PR so the routing migration remains easy to review.

## Suggested PR Breakdown

### PR 1: V2 Default Routing + Switch Removal

Scope:

- Redirect auth success and already-authenticated flows to `/v2/library`.
- Remove `V2ModeSwitch` from both shells.
- Update V2 no-access fallback away from `/home`.
- Update Taskforce shell tests.

Validation:

- `npm run build`
- Targeted Playwright tests for login and Taskforce shell.

### PR 2: Public Copy + Legacy Route Redirects

Scope:

- Replace public `/` Topics/Cases copy with Taskforce V2 copy or redirect behavior.
- Redirect `/home`, `/topics`, `/cases`, `/skills` to V2 destinations.
- Redirect `/admin` to `/v2/admin`.
- Keep settings reachable from Taskforce shell if still needed.

Validation:

- `npm run build`
- Playwright coverage for public `/`, legacy redirects, and settings access.

### PR 3: Legacy UI Cleanup

Scope:

- Remove unused V1 components, route files, API wrappers, styles, and tests after redirects have shipped.

Validation:

- `npm run build`
- Full Playwright suite.

## Risk Areas

- `currentUser.v2` gating: if any real users still receive `v2: false`, routing every login to `/v2/library` will expose the no-access state. Resolve this before PR 1 ships.
- Settings access: `_layout/settings` may contain account, billing, organization, and connect-agent controls that Taskforce users still need. Keep or move this before retiring `_layout`.
- Admin access: there are legacy and V2 admin routes. Superuser navigation should point to `/v2/admin`; legacy `/admin` should redirect.
- Tests encode V1 as product truth. Several tests will fail intentionally until they are rewritten around the V2-only contract.
- Public SEO/title copy still says EnderAI/Product memory. Decide whether the public brand is still EnderAI with Taskforce as product, or Taskforce everywhere.

## Definition of Done

- A signed-in user lands in Taskforce Library by default.
- No visible UI offers a switch back to the V1 product surface.
- Public pages no longer describe Topics/Cases as the primary product.
- Legacy V1 routes are either redirected or deliberately hidden behind an internal-only path.
- Taskforce nav exposes Library, Agents, Metrics, Search, and membership/upgrade.
- Existing V2 API paths continue to work unchanged.
- Build and Playwright validation pass after test expectations are updated.
