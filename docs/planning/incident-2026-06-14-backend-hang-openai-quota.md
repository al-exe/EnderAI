# Incident: backend wedged by OpenAI quota exhaustion (2026-06-14)

**Status:** Resolved (mitigated by restart). Root cause requires follow-up.
**Severity:** Full public outage of the authenticated app (`/v2/*`).
**Author:** Claude (with Alex)

## Symptom

`https://taskforce.tools/v2/library/` and all in-app links appeared "down."
The Render dashboard showed **green** for backend, db, and mcp services, so it
looked like nothing was wrong.

## What was actually happening

- **Static frontend was fine.** `/`, `/v2/library/`, and `/landing/` all served
  HTTP 200 with the JS/CSS bundles loading. `/landing/` worked because it is a
  purely static route that never calls the backend; every `/v2/*` page fetches
  live data on load, so it rendered the shell and then hung.
- **The backend accepted TCP/TLS connections but returned 0 bytes** on every
  external request — including a nonexistent `/health` — timing out at 10s+.
  TCP/TLS handshake completed in ~30ms, then no HTTP response ever arrived.
- **Logs showed a continuous retry storm** of:
  ```
  openai.RateLimitError: 429 - insufficient_quota
  "You exceeded your current quota, please check your plan and billing details"
  ```
  originating in `backend/app/core/search/embeddings.py` (`embed_batch` /
  `safe_embed_batch`). Every embedding batch 429'd, retried with backoff, and the
  backlog of retrying tasks saturated the single web instance. Internal calls
  (`/observe` → 202, `/fleet` → 200) occasionally squeaked through, but fresh
  external connections were never serviced.

## Root cause

The OpenAI account's **quota/billing was exhausted** → every embedding call
returned `429 insufficient_quota` → the embedding retry path flooded the single
backend worker's event loop → all public-facing requests starved and timed out.

The library page depends on the search/embedding path, so it failed hardest, but
the saturation degraded the whole public API.

## Why the dashboard showed green

The backend service has **no `healthCheckPath` configured**, so Render only
performs a TCP port check. The port stayed open the entire time, so Render
reported the service healthy even though the app could not serve a single public
HTTP request. The dashboard could not see an application-level hang.

## Resolution

Restarted `enderai-backend` (`srv-d60o01qli9vc73fcv3u0`) via the Render CLI
(`render restart`). The backend returned to answering in ~130ms immediately
after restart:

| Endpoint | Before | After |
|---|---|---|
| backend `/docs` | timeout (0 bytes) | 200 in ~0.16s |
| backend `/api/v1/v2/taskforce/fleet` | timeout | 401 (auth) in ~0.13s |
| frontend `/v2/library/` | shell only, data hung | 200 in ~0.12s |

The restart clears the backlog of retrying tasks. It is a **temporary** fix: if
the OpenAI quota is still exhausted, the retry storm can rebuild under load.

## Follow-ups

1. **(Owner: Alex) Top up / raise the OpenAI quota** in the OpenAI billing
   dashboard. This is the true root cause; until resolved, fresh
   `insufficient_quota` 429s will keep appearing in the logs.
2. **Harden the embedding path** so a provider outage degrades gracefully instead
   of taking the whole API down: cap/circuit-break retries, bound background-task
   concurrency, and treat embeddings as best-effort (fail the search feature, not
   the process). Tracked in **TF-247** (for Codex):
   https://alexlee4190.atlassian.net/browse/TF-247
3. **Configure a real `healthCheckPath`** on the Render backend service — one
   that does NOT depend on OpenAI/embeddings — so Render can detect this class of
   hang and stop reporting false green.

## Timeline (UTC)

- 2026-06-14 18:37 — Deploy `b2b43a9` goes Live (most recent change before the
  outage; not confirmed as causal).
- 2026-06-15 ~05:51 — Logs show sustained `429 insufficient_quota` embedding
  failures and retry storm; external requests timing out with 0 bytes.
- 2026-06-15 (investigation) — Diagnosed quota exhaustion + worker saturation;
  restarted backend; public endpoints confirmed responsive again.
