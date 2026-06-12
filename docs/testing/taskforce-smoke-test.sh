#!/usr/bin/env bash
# Taskforce end-to-end smoke test — proves the capture → recall loop closes.
#
# Writes a uniquely-marked document via POST /observe, then confirms
# POST /discover surfaces it again. That single round-trip exercises the
# three things that have to be true for cross-instance context to work:
#   1. the token authenticates,
#   2. /observe actually writes a document (shadow mode is OFF + capture works),
#   3. /discover scores it back above threshold (recall works).
#
# Runs against the DEMO library by default so it never clutters your real
# library. Set TASKFORCE_SMOKE_DEMO=0 to exercise the live library the hooks
# actually use (creates one real "SMOKE-…" doc you can delete afterward).
#
# Usage:
#   bash taskforce-smoke-test.sh
#   TASKFORCE_SMOKE_DEMO=0 bash taskforce-smoke-test.sh        # live path
#   TASKFORCE_BACKEND_URL=http://localhost:8000 bash taskforce-smoke-test.sh

set -uo pipefail

BACKEND="${TASKFORCE_BACKEND_URL:-https://enderai-backend.onrender.com}"
API="$BACKEND/api/v1/v2/taskforce"
DEMO="${TASKFORCE_SMOKE_DEMO:-1}"
[ "$DEMO" = "1" ] && DEMO_Q="true" || DEMO_Q="false"

command -v jq   >/dev/null 2>&1 || { echo "FAIL: jq not installed";   exit 2; }
command -v curl >/dev/null 2>&1 || { echo "FAIL: curl not installed"; exit 2; }

# --- resolve token (new path, legacy fallback) ---
token_file="$HOME/.taskforce_mcp_token"
[ -r "$token_file" ] || token_file="$HOME/.enderai_mcp_token"
if [ ! -r "$token_file" ]; then
  echo "FAIL: no token at ~/.taskforce_mcp_token (or legacy ~/.enderai_mcp_token)"
  echo "      create one in Connect Agent and save it first."
  exit 1
fi
TOKEN="$(tr -d '\r\n' < "$token_file")"
[ -n "$TOKEN" ] || { echo "FAIL: token file is empty"; exit 1; }

auth=(-H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json")
marker="SMOKE-$(date +%s)-${RANDOM}"
sid="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || python3 -c 'import uuid;print(uuid.uuid4())')"

pass=0; fail=0
ok(){ echo "  PASS: $1"; pass=$((pass+1)); }
no(){ echo "  FAIL: $1"; fail=$((fail+1)); }

echo "Taskforce smoke test"
echo "  backend: $BACKEND"
echo "  space:   $([ "$DEMO" = 1 ] && echo 'demo (isolated)' || echo 'LIVE')"
echo "  marker:  $marker"
echo

# --- 1. token authenticates + discover reachable ---
echo "[1/3] auth + discover reachable"
code="$(curl -sS -o /tmp/tf_smoke_disc0.json -w '%{http_code}' "${auth[@]}" -X POST \
  --data "{\"prompt\":\"ping\",\"k\":1,\"min_score\":0.9,\"session_id\":\"$sid\"}" \
  "$API/discover?demo=$DEMO_Q")" || code="000"
if [ "$code" = 200 ]; then
  ok "discover returned 200"
else
  no "discover HTTP $code — token invalid/expired, wrong backend, or backend down"
  echo; echo "RESULT: FAIL (cannot reach the API)"; exit 1
fi

# --- 2. observe writes a document (proves shadow OFF + capture) ---
echo "[2/3] observe writes a document"
read -r -d '' body <<JSON
{
  "kind":"final",
  "prompt":"Smoke: record the widget cache TTL decision ($marker)",
  "transcript":[
    {"role":"user","content":"What TTL should the widget cache use? $marker"},
    {"role":"assistant","content":"900s, matching the upstream refresh window."},
    {"role":"tool","content":"edited config/widget_cache.yaml"}
  ],
  "active_document_id":null,
  "session_id":"$sid",
  "cwd":"/tmp/taskforce-smoke",
  "branch":"main",
  "client":"smoke-test",
  "files_touched":["config/widget_cache.yaml"],
  "commands_run":[{"cmd":"grep ttl config/widget_cache.yaml","exit_code":0}],
  "duration_ms":1000,
  "harness":null,
  "summary_points":["$marker: widget cache TTL set to 900s to match the upstream refresh window"],
  "details_sections":[{"anchor_id":"decision","markdown":"# Decision\\nWidget cache TTL = 900s. Marker $marker."}],
  "decisions":["Widget cache TTL = 900s"],
  "outcome":"shipped"
}
JSON
code="$(curl -sS -o /tmp/tf_smoke_obs.json -w '%{http_code}' "${auth[@]}" -X POST \
  --data "$body" "$API/observe?demo=$DEMO_Q")" || code="000"
action="$(jq -r '.action // empty'     /tmp/tf_smoke_obs.json 2>/dev/null)"
shadow="$(jq -r '.shadow // empty'     /tmp/tf_smoke_obs.json 2>/dev/null)"
docid="$( jq -r '.document_id // empty' /tmp/tf_smoke_obs.json 2>/dev/null)"
reason="$(jq -r '.reason // empty'     /tmp/tf_smoke_obs.json 2>/dev/null)"
echo "  observe HTTP $code · action=$action shadow=$shadow reason=$reason doc=${docid:-none}"
if [ "$shadow" = "true" ]; then
  no "shadow mode is ON — set TASKFORCE_OBSERVE_SHADOW=0 on the backend and redeploy"
fi
if [ "$action" = "created" ] || [ "$action" = "updated" ]; then
  ok "document $action"
elif [ "$action" = "skipped" ]; then
  no "observe skipped (reason: $reason)"
else
  no "unexpected observe response (HTTP $code) — see /tmp/tf_smoke_obs.json"
fi

# --- 3. discover surfaces it (proves recall) ---
echo "[3/3] discover surfaces the document"
sleep 1
code="$(curl -sS -o /tmp/tf_smoke_disc.json -w '%{http_code}' "${auth[@]}" -X POST \
  --data "{\"prompt\":\"what did we decide about the widget cache TTL $marker\",\"k\":3,\"min_score\":0.1,\"session_id\":\"$sid\"}" \
  "$API/discover?demo=$DEMO_Q")" || code="000"
nmatch="$(jq '.matches | length' /tmp/tf_smoke_disc.json 2>/dev/null || echo 0)"
found="$(jq -r --arg id "$docid" --arg m "$marker" \
  '[.matches[] | select(.document_id==$id or (.title|contains($m)))] | length' \
  /tmp/tf_smoke_disc.json 2>/dev/null || echo 0)"
top="$(jq -r '.matches[0] | "\(.title) (score \(.score))"' /tmp/tf_smoke_disc.json 2>/dev/null)"
echo "  discover HTTP $code · matches=$nmatch · top: ${top:-none}"
if [ "${found:-0}" -ge 1 ] 2>/dev/null; then
  ok "the marked document was recalled"
else
  no "the document was NOT recalled — the loop is broken (capture wrote nothing, or scoring filtered it)"
fi

echo
echo "RESULT: $pass passed, $fail failed"
if [ "$fail" -eq 0 ]; then
  echo "✅ Capture → recall loop works end to end."
  [ "$DEMO" = "0" ] && echo "   (live mode created doc $docid — delete it from the Library if you want it gone.)"
  exit 0
else
  echo "❌ See failures above and the troubleshooting table in taskforce-e2e-test-runbook.md."
  exit 1
fi
