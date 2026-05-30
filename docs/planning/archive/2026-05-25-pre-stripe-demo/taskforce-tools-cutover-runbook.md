# taskforce.tools cutover — dashboard runbook

Last updated: 2026-05-23

The code-side changes shipped in [PR #77](https://github.com/al-exe/EnderAI/pull/77) (CORS alias logic) and [PR #78](https://github.com/al-exe/EnderAI/pull/78) (render.yaml reconcile). This is the by-hand sequence for the actual cutover: env vars, custom domains, OAuth allowlist.

Do these in order. Each step is independent — you can stop after any one of them and the previous ones still work.

## Order of operations

```
1. Backend env vars (Render)
   ↓
2. GitHub Pages custom domain
   ↓
3. Re-run frontend deploy
   ↓
4. Firebase authorized domains
   ↓
5. Smoke test
   ↓
6. (Optional) enderai.xyz redirect
```

---

## 1. Backend env vars (Render)

**Where:** Render dashboard → `EnderAI-backend` → Environment

**Why:** This is what tells the backend which origins to accept for CORS and which URL to use when building redirect/email URLs. Has to be set in the dashboard because every backend env var is marked `sync: false` in render.yaml — the blueprint sync can't push these.

**Set:**

```
BACKEND_CORS_ORIGINS
  → https://al-exe.github.io,http://localhost:5173,https://taskforce.tools,https://enderai.xyz

FRONTEND_HOST
  → https://www.taskforce.tools
```

The `expand_cors_origin_aliases()` helper in `app/core/config.py` adds the www/apex sibling for both taskforce.tools and enderai.xyz, so you don't need to list `https://www.taskforce.tools` or `https://www.enderai.xyz` explicitly — they're auto-added.

**Saving these triggers a redeploy.** Watch the deploy log for "alembic upgrade head" + "fastapi run --workers 4" before moving on.

**Verify:**

```bash
curl -i https://enderai-backend.onrender.com/api/v1/utils/health-check/
# expect 200

curl -i -H "Origin: https://www.taskforce.tools" \
     -H "Access-Control-Request-Method: POST" \
     -X OPTIONS \
     https://enderai-backend.onrender.com/api/v1/v2/taskforce/discover
# expect access-control-allow-origin: https://www.taskforce.tools

curl -i -H "Origin: https://al-exe.github.io" \
     -X OPTIONS \
     https://enderai-backend.onrender.com/api/v1/v2/taskforce/discover
# expect access-control-allow-origin: https://al-exe.github.io
```

---

## 2. GitHub Pages custom domain

**Where:** `al-exe/EnderAI-frontend` repo → Settings → Pages → Custom domain

**Why:** GitHub Pages serves the frontend. The "Custom domain" field controls the CNAME committed into the deployment artifact and which hostname GitHub provisions SSL for.

**Set:**

```
Custom domain: www.taskforce.tools
☑ Enforce HTTPS
```

Click Save. GitHub will run a DNS check and provision an SSL cert (takes a minute).

**If GitHub says "Domain does not resolve":** verify DNS is set:

```bash
dig +short www.taskforce.tools CNAME
# expect: al-exe.github.io.
```

If wrong, fix DNS first, then come back.

---

## 3. Re-run frontend deploy

**Where:** `al-exe/EnderAI-frontend` repo → Actions → "Deploy Frontend to GitHub Pages" → "Run workflow" → main

**Why:** The custom-domain change updates the CNAME file inside the deployed artifact, which only happens on the next deploy. Push a no-op commit OR just click "Run workflow" — the workflow has `workflow_dispatch:` so it can be triggered manually.

**Verify:**

```bash
curl -sI https://www.taskforce.tools | head -3
# expect HTTP/2 200

curl -sI https://www.taskforce.tools/v2/library | head -3
# expect HTTP/2 200 (workflow pre-generates per-route index.html)
```

Open `https://www.taskforce.tools` in a fresh incognito window → app loads, no console errors.

---

## 4. Firebase authorized domains

**Where:** Firebase console → Authentication → Settings → Authorized domains

**Why:** Firebase Auth blocks sign-in redirects coming from origins not on this list. `/login/firebase-token` will fail silently with a cryptic CORS-ish error if you skip this.

**Add:**

```
www.taskforce.tools
taskforce.tools
```

Keep `www.enderai.xyz` and `enderai.xyz` in the list for now (transition).

**Verify:**

- Sign out of the app
- Hit `https://www.taskforce.tools/login`
- Complete the Firebase sign-in flow
- Expect to land on `/v2/library` with a valid `access_token` in localStorage

---

## 5. Smoke test

Once 1–4 are done, walk through the golden path:

- [ ] `https://www.taskforce.tools` loads
- [ ] Log in via Firebase
- [ ] Land on `/v2/library` — docs render
- [ ] Open a doc → the V2 doc viewer renders
- [ ] Demo mode toggle works
- [ ] `https://www.enderai.xyz` still loads (until step 6 redirects it)
- [ ] No CORS errors in browser console anywhere
- [ ] Render deploy log for `EnderAI-backend` is clean

If anything red here, **rollback the relevant env var in step 1** — that's the easiest single revert.

---

## 6. (Optional) enderai.xyz → taskforce.tools redirect

GitHub Pages can't redirect for you because the custom-domain slot is now taking taskforce.tools.

Options:

- **Cloudflare** (if enderai.xyz DNS is on Cloudflare): add a Page Rule on `*enderai.xyz/*` → Forwarding URL (301) → `https://www.taskforce.tools/$1`. Cheapest, fastest.
- **A redirect host**: point enderai.xyz DNS at a redirect-as-a-service (Netlify, Vercel, redirect.pizza, etc.) that 308s to the new domain.
- **Skip it**: let enderai.xyz 404. Cleaner, but users with bookmarks have to learn the new URL.

Whatever you pick, do it AFTER step 5 confirms taskforce.tools works.

---

## Cleanup (later, separate PR)

Once you've watched logs for ~1 week and seen no CORS rejections from `enderai.xyz` origins:

1. Remove `https://enderai.xyz` from `BACKEND_CORS_ORIGINS` (dashboard).
2. Open a PR removing the `enderai.xyz` aliases from `expand_cors_origin_aliases()` in `app/core/config.py` and from `test_config.py`.
3. Remove `enderai.xyz` from Firebase authorized domains.
4. Optional: rename `EnderAI-backend` → `taskforce-backend` in Render and the `enderai-api-mcp` package → `taskforce-mcp` (Phase 6 of TF-174 / TF-180; rebrand maintenance window).

---

## Rollback summary

| If this breaks… | Fastest rollback |
|---|---|
| Backend CORS after step 1 | Revert `BACKEND_CORS_ORIGINS` to the pre-change value in Render dashboard |
| `www.taskforce.tools` doesn't load after step 2/3 | In GitHub Pages settings, change Custom domain back to `www.enderai.xyz`, re-run deploy |
| Firebase login broken | Add `www.taskforce.tools` to authorized domains (probably just missed step 4) |
| Stripe checkout broken | Verify `FRONTEND_HOST` was set correctly in step 1 — checkout success/cancel URLs are built from it |
