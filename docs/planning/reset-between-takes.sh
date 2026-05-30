#!/usr/bin/env bash
# Reset everything the /tf demo touches so the next take starts from the
# same state as the first. Run AFTER a take, BEFORE the next pre-warm.
#
# What it resets (in order):
#   1. fix/stripe-webhook-double-fulfillment worktree → drops Claude's billing.py edit
#   2. All non-seeded /tf consult events for Alex → empties Recent
#      Invocations on every profile's page (Jensen, Mira, etc.).
#      Preserves the seeded baseline (rows tagged payload->>'seeded'='true'
#      by core/agents/seed.py). Covers stale dry runs from any date and
#      any TASKFORCE_DEMO state, which the old "today + is_demo=true"
#      filter missed.
#   3. "Referenced by" sections appended to TF-191 seed docs by
#      tf-reference.sh → next take starts with the original details only
#
# Requirements:
#   - DATABASE_URL env exported (Render Postgres external URL).
#     Get it: Render → Postgres → "Connect" → "External Database URL".
#     If unset, only step 1 runs and the script warns about the DB skips.
#   - psql available locally OR substitute the Render shell path described
#     at the bottom of this file.
#
# Usage:
#   export DATABASE_URL='postgresql://…'
#   bash ~/dev/docs/reset-between-takes.sh
#
# Idempotent — safe to re-run.

set -uo pipefail

TASKFORCE_REPO=/home/alexlee/dev/EnderAI
FIX_BRANCH=fix/stripe-webhook-double-fulfillment
USER_EMAIL=alexlee4190@gmail.com

echo "=== 1/3: reset demo worktree ==="
git -C "$TASKFORCE_REPO" worktree prune
WORKTREE_PATH=$(git -C "$TASKFORCE_REPO" worktree list --porcelain \
  | awk -v br="refs/heads/$FIX_BRANCH" '/^worktree / { wt = $2 } $1 == "branch" && $2 == br { print wt; exit }')

if [ -z "$WORKTREE_PATH" ]; then
    echo "  ⚠ no worktree on $FIX_BRANCH — nothing to reset"
else
    git -C "$TASKFORCE_REPO" fetch origin "$FIX_BRANCH" --quiet
    git -C "$WORKTREE_PATH" reset --hard "origin/$FIX_BRANCH"
    echo "  ✓ $WORKTREE_PATH reset to origin/$FIX_BRANCH"
fi

if [ -z "${DATABASE_URL:-}" ]; then
    echo
    echo "⚠ DATABASE_URL not set — skipping DB cleanup (steps 2 + 3)."
    echo "  Export it and re-run, or use the Render-shell Python fallback"
    echo "  block at the bottom of this script."
    exit 0
fi

if ! command -v psql >/dev/null 2>&1; then
    echo "⚠ psql not installed locally — install it or use the Render-shell"
    echo "  Python fallback block at the bottom of this script."
    exit 0
fi

echo
echo "=== 2/3: delete all non-seeded /tf consult events for Alex ==="
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "
DELETE FROM metrics_event
WHERE kind = 'document.consulted'
  AND user_id = (SELECT id FROM \"user\" WHERE email = '$USER_EMAIL')
  AND (payload->>'seeded') IS DISTINCT FROM 'true'
RETURNING occurred_at, payload->>'session_id' AS session_id, is_demo;
" || { echo "  ⚠ DB cleanup failed — bailing"; exit 1; }

echo
echo "=== 3/3: strip 'referenced-by' sections from seed docs ==="
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "
UPDATE v2_document
SET details_markdown_sections = COALESCE(
        (SELECT jsonb_agg(section)
         FROM jsonb_array_elements(details_markdown_sections::jsonb) AS section
         WHERE section->>'anchor_id' != 'referenced-by'),
        '[]'::jsonb
    )::json
WHERE owner_id = (SELECT id FROM \"user\" WHERE email = '$USER_EMAIL')
  AND is_demo = true
  AND title IN (
      'Stripe webhook idempotency strategy',
      'Stripe plan upgrade webhook retries — regression test pattern',
      'Debugging Stripe webhook retries and double-fire fulfillment'
  )
  AND details_markdown_sections::jsonb @> '[{\"anchor_id\":\"referenced-by\"}]'::jsonb
RETURNING id, title;
"

echo
echo "✓ Reset complete — next take starts from the baseline state."
echo
echo "Recommended next steps:"
echo "  - Quit Claude Code (Ctrl-D) and relaunch with \`claude\` to drop session state"
echo "  - Re-run pre-flight §B + §C from the demo script before recording"

# ---------------------------------------------------------------
# Render-shell fallback (no local psql, no exported DATABASE_URL)
# ---------------------------------------------------------------
# If you'd rather run the DB cleanup from the Render shell on
# EnderAI-backend (where DATABASE_URL is already exported via the
# service env), paste this base64'd Python block. It does steps 2 + 3
# using SQLAlchemy through the app's engine. Step 1 (git reset) still
# needs to run on your local machine.
#
#   echo '<BASE64>' | base64 -d | python
#
# Regenerate the base64 with:
#   base64 -w 0 <<'PY'
#   from app.core.db import engine
#   from sqlalchemy import text
#   with engine.begin() as conn:
#       d = conn.execute(text("""
#           DELETE FROM metrics_event
#           WHERE kind = 'document.consulted'
#             AND user_id = (SELECT id FROM "user" WHERE email = 'alexlee4190@gmail.com')
#             AND (payload->>'seeded') IS DISTINCT FROM 'true'
#           RETURNING occurred_at, payload->>'session_id', is_demo
#       """))
#       print(f"deleted {sum(1 for _ in d)} consult events")
#       u = conn.execute(text("""
#           UPDATE v2_document
#           SET details_markdown_sections = COALESCE(
#                   (SELECT jsonb_agg(section)
#                    FROM jsonb_array_elements(details_markdown_sections::jsonb) AS section
#                    WHERE section->>'anchor_id' != 'referenced-by'),
#                   '[]'::jsonb
#               )::json
#           WHERE owner_id = (SELECT id FROM "user" WHERE email = 'alexlee4190@gmail.com')
#             AND is_demo = true
#             AND title IN (
#                 'Stripe webhook idempotency strategy',
#                 'Stripe plan upgrade webhook retries — regression test pattern',
#                 'Debugging Stripe webhook retries and double-fire fulfillment'
#             )
#             AND details_markdown_sections::jsonb @> '[{"anchor_id":"referenced-by"}]'::jsonb
#           RETURNING id, title
#       """))
#       for r in u: print("stripped referenced-by from:", r[1])
#   PY
