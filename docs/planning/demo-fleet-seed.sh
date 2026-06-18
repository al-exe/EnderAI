#!/usr/bin/env bash
# Seed everything the live-fleet demo needs, in one command.
# Companion to taskforce-demo-fleet-story.md §7 (the run-demo runbook) and
# demo-fleet-reset.sh (the between-takes reset).
#
# WHERE TO RUN: the Render Shell on the **EnderAI-backend** service
#   (cd /app/backend), or any environment where `python -m app.scripts.*`
#   resolves (the app + DATABASE_URL on PATH). These seeders run inside the
#   app, not over HTTP.
#
# WHAT IT SEEDS (all idempotent — each seeder wipes+reinserts its own rows):
#   1. Profiles + Library  → seed_agents          (5 specialists incl. Jensen,
#                                                   15 doc links, and the demo
#                                                   library via ensure_*_demo_seed)
#   2. Ledger + Metrics    → seed_demo_metrics_alex (12 sessions / ~106 events:
#                                                   consult/reuse/savings history
#                                                   that fills the Ledger + each
#                                                   profile's Recent Invocations)
#   3. Cross-boundary row  → seed_empty_cell_scenario (Alice/Codex → Bob/Claude
#                                                   reuse in org "Acme"; the
#                                                   canonical Ledger cross_boundary
#                                                   proof — OPTIONAL, see note)
#
# Usage:
#   bash demo-fleet-seed.sh                         # defaults to Alex's email
#   bash demo-fleet-seed.sh --email you@example.com
#   bash demo-fleet-seed.sh --skip-empty-cell       # profiles+docs+ledger only

set -uo pipefail

EMAIL="alexlee4190@gmail.com"
RUN_EMPTY_CELL=1
while [[ $# -gt 0 ]]; do
    case "$1" in
        --email)            EMAIL="$2"; shift 2 ;;
        --skip-empty-cell)  RUN_EMPTY_CELL=0; shift ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

run() {
    echo
    echo "=== $1 ==="
    shift
    if "$@"; then
        echo "  ✓ done"
    else
        echo "  ⚠ FAILED (rc=$?) — see output above" >&2
        return 1
    fi
}

echo "Seeding the live-fleet demo for ${EMAIL}…"

run "1/3 profiles + library (seed_agents)" \
    python -m app.scripts.seed_agents --email "$EMAIL" \
    || echo "  (expect: specialists=5 documents_created=true/false links=15)"

run "2/3 ledger + metrics history (seed_demo_metrics_alex)" \
    python -m app.scripts.seed_demo_metrics_alex --email "$EMAIL" \
    || echo "  (expect: sessions=12 events=106)"

if [[ "$RUN_EMPTY_CELL" == "1" ]]; then
    run "3/3 cross-boundary ledger row (seed_empty_cell_scenario)" \
        python -m app.scripts.seed_empty_cell_scenario \
        || echo "  (creates Alice/Bob in org 'Acme'; non-fatal if it already exists)"
else
    echo
    echo "=== 3/3 cross-boundary ledger row — SKIPPED (--skip-empty-cell) ==="
fi

cat <<'EOF'

────────────────────────────────────────────────────────────────────
✓ Seed pass complete. Verify on the web app (Demo mode ON):
  • Profiles  → 5 cards (Jensen/Mira/Orin/Vega/Nia), each with linked docs
  • Library   → the Stripe idempotency doc + ~14 supporting docs render
  • Ledger    → populated rows; filter cross_boundary=true shows the
                Codex→Claude reuse (needs the empty-cell org — log in as
                bob@acme.example, or run one live agent on Codex during the take)
  • Profiles routing smoke test (matched_specialist should be "jensen"):
      TASKFORCE_DEMO=1 ~/.claude/skills/tf/tf-discover.sh \
        --prompt "Stripe is double-charging on plan upgrades — webhook retries fulfilled twice. Fix it?" \
        --files "app/api/routes/billing.py,app/core/stripe_billing.py" | jq .matched_specialist
────────────────────────────────────────────────────────────────────
EOF
