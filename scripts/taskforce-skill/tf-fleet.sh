#!/usr/bin/env bash
# /tf — fleet knowledge-bus step ([DEMO WORK]).
#
# The "pull from another agent" beat, implemented client-side. GET /fleet,
# scope to the *sibling* agents on your own fleet session (or same cwd), keep
# the recently-active ones that have an active document, then GET each of
# those documents so the skill can surface what your fleet-mates just figured
# out — a 3-line preview the user sees plus the full content fed to the model.
#
# This is a read-only pull over existing endpoints (GET /fleet, GET
# /v2/documents/{id}); there is no server push channel. Latency is one
# discover cycle, not realtime — but a fleet-mate's fresh decision lands in
# your session the next time you run /tf instead of only via topical match.
#
# Flags:
#   --exclude-session <id>   your own session_id (from tf-discover.sh); used
#                            both to drop yourself and to find your fleet scope
#   --cwd <path>             working dir, to prefer/scope same-codebase siblings
#   --max-age-min <n>        ignore siblings idle longer than this (default 180)
#   --limit <n>              max siblings to surface (default 3)
#
# Output JSON (always exit 0; check .ok):
#   { "ok": true,
#     "scope": "fleet|cwd|any",
#     "siblings": [ { session_id, display_name, agent_kind, specialist_slug,
#                     status, minutes_ago, recent_activity, fleet_name,
#                     document_id, title, produced_by_client, href,
#                     preview, full } ],
#     "frontend_host": "https://www.taskforce.tools" }
#   { "ok": false, "reason": "no_token|backend_down|http_<code>|empty",
#     "detail": "..." }

set -uo pipefail

readonly LOG_FILE="${HOME}/.claude/taskforce-skill.log"
readonly TOKEN_FILE="${HOME}/.taskforce_mcp_token"
readonly LEGACY_TOKEN_FILE="${HOME}/.enderai_mcp_token"
readonly BACKEND_URL="${TASKFORCE_BACKEND_URL:-${ENDERAI_BACKEND_URL:-https://enderai-backend.onrender.com}}"
readonly FRONTEND_HOST="${TASKFORCE_FRONTEND_HOST:-https://www.taskforce.tools}"

# When TASKFORCE_DEMO=1, fetch demo-flagged sibling documents so the bus sees
# the same library tf-discover.sh consulted. Off by default.
case "${TASKFORCE_DEMO:-0}" in
    1|true|TRUE|yes) DEMO_FLAG="true" ;;
    *)               DEMO_FLAG="false" ;;
esac
readonly DEMO_FLAG

mkdir -p "$(dirname "$LOG_FILE")"
log() { printf '[%s] tf-fleet %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG_FILE"; }

emit_error() {
    local reason="$1" detail="${2:-}"
    log "error: ${reason} ${detail}"
    jq -cn --arg r "$reason" --arg d "$detail" '{ok:false, reason:$r, detail:$d}'
    exit 0
}

# An empty-but-OK result is not an error — the common case is "no siblings".
emit_empty() {
    local scope="$1"
    jq -cn --arg scope "$scope" --arg host "$FRONTEND_HOST" \
        '{ok:true, scope:$scope, siblings:[], frontend_host:$host}'
    exit 0
}

command -v jq >/dev/null 2>&1   || emit_error "jq_missing" "install jq"
command -v curl >/dev/null 2>&1 || emit_error "curl_missing" "install curl"

exclude_session="" cwd="" max_age=180 limit=3
while [[ $# -gt 0 ]]; do
    case "$1" in
        --exclude-session) exclude_session="$2"; shift 2 ;;
        --cwd)             cwd="$2";             shift 2 ;;
        --max-age-min)     max_age="$2";         shift 2 ;;
        --limit)           limit="$2";           shift 2 ;;
        *)                 shift ;;
    esac
done

token_file="$TOKEN_FILE"
if [[ ! -r "$token_file" && -r "$LEGACY_TOKEN_FILE" ]]; then
    token_file="$LEGACY_TOKEN_FILE"
fi
[[ -r "$token_file" ]] || emit_error "no_token" "$TOKEN_FILE not readable"

token="$(tr -d '\r\n' < "$token_file")"
[[ -z "$token" ]] && emit_error "no_token" "token file empty"

tmp_resp="$(mktemp)"
trap 'rm -f "$tmp_resp"' EXIT

http_status="$(
    curl -sS -o "$tmp_resp" -w '%{http_code}' \
        --max-time 8 \
        -H "Authorization: Bearer ${token}" \
        "${BACKEND_URL}/api/v1/v2/taskforce/fleet" 2>>"$LOG_FILE"
)" || emit_error "backend_down" "curl failed"

[[ "$http_status" != "200" ]] && \
    emit_error "http_${http_status}" "$(head -c 400 "$tmp_resp" 2>/dev/null || true)"
[[ -s "$tmp_resp" ]] || emit_error "empty" "empty body from /fleet"

# Select the sibling agents to surface. Scope rules, in order of preference:
#   1. fleet — if our own session is in the roster, only its fleet-mates
#   2. cwd   — else, agents reporting the same working dir
#   3. any   — else, the most recently active agents anywhere
# Within the chosen scope, prefer same-cwd siblings, then most recent.
selection="$(jq -c \
    --arg self "$exclude_session" \
    --arg cwd "$cwd" \
    --argjson max_age "$max_age" \
    --argjson limit "$limit" '
    [ .fleet_sessions[]
      | .name as $fname | (.is_history // false) as $hist
      | .agents[]
      | . + { _fleet_name: $fname, _is_history: $hist } ] as $all
    | ( $all | map(select(.session_id == $self)) | first ) as $me
    | ( $me.fleet_session_id ) as $my_fleet
    | [ $all[]
        | select(.session_id != $self)
        | select(._is_history | not)
        | select(.active_document_id != null)
        | select(.minutes_ago <= $max_age)
        | select(.status == "running" or .status == "waiting"
                 or .status == "paused" or .status == "idle") ] as $cands
    | ( if $my_fleet != null then "fleet"
        elif $cwd != "" then "cwd"
        else "any" end ) as $scope
    | ( if $scope == "fleet" then [ $cands[] | select(.fleet_session_id == $my_fleet) ]
        elif $scope == "cwd" then [ $cands[] | select(.cwd == $cwd) ]
        else $cands end ) as $scoped
    | { scope: $scope,
        agents: ( $scoped
          | sort_by( (if (.cwd == $cwd and $cwd != "") then 0 else 1 end), .minutes_ago )
          | .[0:$limit]
          | map({ session_id, display_name, title, agent_kind, specialist_slug,
                  status, minutes_ago,
                  recent_activity: (.recent_activity // []),
                  active_document_id, fleet_name: ._fleet_name }) ) }
' "$tmp_resp")"

scope="$(jq -r '.scope' <<<"$selection")"
sib_count="$(jq '.agents | length' <<<"$selection")"
[[ "$sib_count" -eq 0 ]] && emit_empty "$scope"

# Enrich each sibling with its active document's title + a preview + full body.
enriched="[]"
for ((i=0; i<sib_count; i++)); do
    sib="$(jq -c ".agents[$i]" <<<"$selection")"
    doc_id="$(jq -r '.active_document_id' <<<"$sib")"

    doc_resp="$(mktemp)"
    doc_http="$(
        curl -sS -o "$doc_resp" -w '%{http_code}' \
            --max-time 6 \
            -H "Authorization: Bearer ${token}" \
            "${BACKEND_URL}/api/v1/v2/documents/${doc_id}?demo=${DEMO_FLAG}" 2>>"$LOG_FILE"
    )" || doc_http="000"

    if [[ "$doc_http" != "200" ]]; then
        log "sibling doc fetch ${doc_id} → ${doc_http}, skipping"
        rm -f "$doc_resp"
        continue
    fi

    # Best summary text: human first, then AI, then description. Full context
    # also tacks on the freshest details section (the latest decision), capped.
    doc_title="$(jq -r '.title // "Untitled"' "$doc_resp")"
    produced_by="$(jq -r '.produced_by_client // ""' "$doc_resp")"
    summary_text="$(jq -r '
        (.human_summary // "") as $h | (.ai_generated_summary // "") as $a
        | (.description // "") as $d
        | if ($h | gsub("\\s";"") | length) > 0 then $h
          elif ($a | gsub("\\s";"") | length) > 0 then $a
          else $d end' "$doc_resp")"
    latest_section="$(jq -r '
        (.details_markdown_sections // []) | last | (.markdown // "")' "$doc_resp")"

    preview="$(printf '%s\n' "$summary_text" \
        | awk 'NF { print "> " $0; n++; if (n >= 3) exit }')"
    full="$(printf '%s\n\n%s\n' "$summary_text" "$latest_section" | head -c 2400)"

    enriched="$(jq -cn \
        --argjson prior "$enriched" \
        --argjson sib "$sib" \
        --arg doc_id "$doc_id" \
        --arg title "$doc_title" \
        --arg produced_by "$produced_by" \
        --arg href "${FRONTEND_HOST}/v2/library/${doc_id}" \
        --arg preview "$preview" \
        --arg full "$full" '
        $prior + [ $sib + {
            document_id: $doc_id,
            title: $title,
            produced_by_client: $produced_by,
            href: $href,
            preview: $preview,
            full: $full
        } ]')"
    rm -f "$doc_resp"
done

jq -cn \
    --arg scope "$scope" \
    --argjson siblings "$enriched" \
    --arg host "$FRONTEND_HOST" '
    { ok: true, scope: $scope, siblings: $siblings, frontend_host: $host }'

log "ok: scope=${scope} surfaced=$(jq '.|length' <<<"$enriched") of ${sib_count} candidate(s)"
