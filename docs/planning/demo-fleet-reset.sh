#!/usr/bin/env bash
# Reset the live-fleet demo between takes — one command.
# Companion to taskforce-demo-fleet-story.md §7 and demo-fleet-seed.sh.
#
# Run this LOCALLY after a take, before the next pre-warm. It undoes exactly
# what a take mutates, leaving the seeded baseline intact:
#
#   1. Captured docs   — deletes the docs tf-capture.sh wrote this take (their
#                        ids are in the demo capture log) via
#                        DELETE /v2/documents/{id}?demo=true. Token only.
#                        Surgical: it only touches what the demo captured,
#                        never the seeded library.   [always runs]
#   2. Consult events  — deletes non-seeded document.consulted rows for the
#                        user so every profile's "Recent invocations" returns
#                        to the seeded baseline.       [needs DATABASE_URL+psql]
#   3. Referenced-by   — strips the "Referenced by" sections tf-reference.sh
#                        appended to seeded demo docs.  [needs DATABASE_URL+psql]
#   4. Code edits      — git-resets the demo working tree(s) the agents edited
#                        (set TASKFORCE_DEMO_REPO / _BRANCH).  [optional]
#
# Usage:
#   bash demo-fleet-reset.sh
#   DATABASE_URL='postgresql://…' bash demo-fleet-reset.sh      # full reset
#   TASKFORCE_DEMO_REPO=~/dev/taskforce-claude \
#     TASKFORCE_DEMO_BRANCH=demo/stripe-double-charge \
#     DATABASE_URL='postgresql://…' bash demo-fleet-reset.sh    # + code reset
#
# Idempotent — safe to re-run. Get DATABASE_URL from Render → Postgres →
# "External Database URL" (or run steps 2+3 from the Render shell — see the
# fallback block at the bottom of reset-between-takes.sh).

set -uo pipefail

USER_EMAIL="${TASKFORCE_DEMO_EMAIL:-alexlee4190@gmail.com}"
BACKEND_URL="${TASKFORCE_BACKEND_URL:-${ENDERAI_BACKEND_URL:-https://enderai-backend.onrender.com}}"
TOKEN_FILE="${HOME}/.taskforce_mcp_token"
LEGACY_TOKEN_FILE="${HOME}/.enderai_mcp_token"
CAPTURE_LOG="${TASKFORCE_DEMO_CAPTURE_LOG:-${HOME}/.claude/taskforce-demo-captures.log}"

command -v jq   >/dev/null 2>&1 || { echo "jq required"; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "curl required"; exit 1; }

token_file="$TOKEN_FILE"
[[ ! -r "$token_file" && -r "$LEGACY_TOKEN_FILE" ]] && token_file="$LEGACY_TOKEN_FILE"
token=""
[[ -r "$token_file" ]] && token="$(tr -d '\r\n' < "$token_file")"

# ── 1/4: delete this take's captured docs ────────────────────────────────
echo "=== 1/4: delete captured demo docs ==="
if [[ -z "$token" ]]; then
    echo "  ⚠ no token at $TOKEN_FILE — skipping captured-doc cleanup"
elif [[ ! -s "$CAPTURE_LOG" ]]; then
    echo "  (capture log empty — nothing captured this take: $CAPTURE_LOG)"
else
    deleted=0 missing=0
    while IFS= read -r doc_id; do
        [[ -z "$doc_id" ]] && continue
        code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 12 \
            -X DELETE -H "Authorization: Bearer ${token}" \
            "${BACKEND_URL}/api/v1/v2/documents/${doc_id}?demo=true" 2>/dev/null)"
        case "$code" in
            204) deleted=$((deleted+1)); echo "  ✓ deleted ${doc_id}" ;;
            404) missing=$((missing+1)); echo "  · already gone ${doc_id}" ;;
            *)   echo "  ⚠ ${doc_id} → HTTP ${code}" ;;
        esac
    done < "$CAPTURE_LOG"
    : > "$CAPTURE_LOG"   # truncate so the next take starts clean
    echo "  deleted=${deleted} already-gone=${missing}; capture log cleared"
fi

# ── 2/4 + 3/4: DB cleanup (consult events + referenced-by) ────────────────
if [[ -z "${DATABASE_URL:-}" ]] || ! command -v psql >/dev/null 2>&1; then
    echo
    echo "=== 2/4 + 3/4: DB cleanup — SKIPPED ==="
    echo "  Set DATABASE_URL and have psql installed to also reset consult"
    echo "  events + 'Referenced by' rows (or run reset-between-takes.sh's"
    echo "  Render-shell Python fallback)."
else
    echo
    echo "=== 2/4: delete non-seeded consult events for ${USER_EMAIL} ==="
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "
    DELETE FROM metrics_event
    WHERE kind = 'document.consulted'
      AND user_id = (SELECT id FROM \"user\" WHERE email = '${USER_EMAIL}')
      AND (payload->>'seeded') IS DISTINCT FROM 'true'
    RETURNING occurred_at, payload->>'session_id' AS session_id;
    " || echo "  ⚠ consult-event cleanup failed"

    echo
    echo "=== 3/4: strip 'Referenced by' from seeded demo docs ==="
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "
    UPDATE v2_document
    SET details_markdown_sections = COALESCE(
            (SELECT jsonb_agg(section)
             FROM jsonb_array_elements(details_markdown_sections::jsonb) AS section
             WHERE section->>'anchor_id' != 'referenced-by'),
            '[]'::jsonb
        )::json
    WHERE owner_id = (SELECT id FROM \"user\" WHERE email = '${USER_EMAIL}')
      AND is_demo = true
      AND details_markdown_sections::jsonb @> '[{\"anchor_id\":\"referenced-by\"}]'::jsonb
    RETURNING id, title;
    " || echo "  ⚠ referenced-by strip failed"
fi

# ── 4/4: git-reset the demo working tree(s) ───────────────────────────────
echo
echo "=== 4/4: reset demo code edits ==="
if [[ -n "${TASKFORCE_DEMO_REPO:-}" && -d "${TASKFORCE_DEMO_REPO}/.git" ]]; then
    branch="${TASKFORCE_DEMO_BRANCH:-}"
    git -C "$TASKFORCE_DEMO_REPO" fetch origin ${branch:+"$branch"} --quiet 2>/dev/null || true
    if [[ -n "$branch" ]]; then
        git -C "$TASKFORCE_DEMO_REPO" reset --hard "origin/${branch}" \
            && echo "  ✓ ${TASKFORCE_DEMO_REPO} reset to origin/${branch}" \
            || echo "  ⚠ could not reset to origin/${branch}"
    else
        echo "  (set TASKFORCE_DEMO_BRANCH to hard-reset; left untouched)"
    fi
else
    echo "  (set TASKFORCE_DEMO_REPO=/path/to/repo and TASKFORCE_DEMO_BRANCH to"
    echo "   git-reset the agents' edits; skipped)"
fi

cat <<'EOF'

────────────────────────────────────────────────────────────────────
✓ Reset complete — next take starts from the seeded baseline.
Next:
  • Quit each agent (Ctrl-D) and relaunch so session state is fresh.
  • If you re-seed, run demo-fleet-seed.sh (idempotent).
  • Pre-warm the backend before rolling.
────────────────────────────────────────────────────────────────────
EOF
