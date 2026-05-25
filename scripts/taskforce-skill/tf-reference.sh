#!/usr/bin/env bash
# /tf — reference step (TF-188).
#
# POST /v2/taskforce/reference. Append a "Referenced by:" row to each
# document the agent actually consulted. Always exits 0; emits a JSON
# envelope so the skill can degrade gracefully.
#
# Flags:
#   --session-id <uuid>         (required)
#   --document-ids <comma-list> (required; ids returned by tf-discover.sh)
#   --user-prompt <str>         (required; the original prompt)
#
# Output JSON:
#   { "ok": true, "updated_document_ids": [...], "skipped_document_ids": [...] }
#   { "ok": false, "reason": "...", "detail": "..." }

set -uo pipefail

readonly LOG_FILE="${HOME}/.claude/taskforce-skill.log"
readonly TOKEN_FILE="${HOME}/.enderai_mcp_token"
readonly BACKEND_URL="${TASKFORCE_BACKEND_URL:-${ENDERAI_BACKEND_URL:-https://enderai-backend.onrender.com}}"

# When TASKFORCE_DEMO=1, scope the reference call to demo-flagged documents
# so the ACL filter matches the same library tf-discover.sh consulted. Without
# this, demo-seed docs are skipped because the default endpoint scope returns
# only non-demo documents.
case "${TASKFORCE_DEMO:-0}" in
    1|true|TRUE|yes) DEMO_FLAG="true" ;;
    *)               DEMO_FLAG="false" ;;
esac
readonly DEMO_FLAG

log() { printf '[%s] tf-reference %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG_FILE"; }
emit_error() {
    local reason="$1" detail="${2:-}"
    log "error: ${reason} ${detail}"
    jq -cn --arg r "$reason" --arg d "$detail" '{ok:false, reason:$r, detail:$d}'
    exit 0
}

command -v jq >/dev/null 2>&1   || emit_error "jq_missing" "install jq"
command -v curl >/dev/null 2>&1 || emit_error "curl_missing" "install curl"

session_id="" doc_ids_csv="" user_prompt=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --session-id)     session_id="$2";   shift 2 ;;
        --document-ids)   doc_ids_csv="$2";  shift 2 ;;
        --user-prompt)    user_prompt="$2";  shift 2 ;;
        *)                shift ;;
    esac
done

[[ -z "$session_id" ]]  && emit_error "missing_session_id"
[[ -z "$doc_ids_csv" ]] && emit_error "missing_document_ids"
[[ -z "$user_prompt" ]] && emit_error "missing_user_prompt"
[[ -r "$TOKEN_FILE" ]]  || emit_error "no_token" "$TOKEN_FILE not readable"

token="$(tr -d '\r\n' < "$TOKEN_FILE")"
[[ -z "$token" ]] && emit_error "no_token" "token file empty"

doc_ids_json="$(jq -cn --arg csv "$doc_ids_csv" '
    $csv | split(",") | map(select(. != ""))
')"

body="$(jq -cn \
    --arg session_id "$session_id" \
    --arg user_prompt "$user_prompt" \
    --argjson document_ids "$doc_ids_json" '
    { session_id: $session_id, document_ids: $document_ids, user_prompt: $user_prompt }
')"

tmp_resp="$(mktemp)"; trap 'rm -f "$tmp_resp"' EXIT

http_status="$(
    curl -sS -o "$tmp_resp" -w '%{http_code}' \
        --max-time 8 \
        -X POST \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        --data "$body" \
        "${BACKEND_URL}/api/v1/v2/taskforce/reference?demo=${DEMO_FLAG}" 2>>"$LOG_FILE"
)" || emit_error "backend_down" "curl failed"

if [[ "$http_status" != "200" ]]; then
    emit_error "http_${http_status}" "$(head -c 400 "$tmp_resp" 2>/dev/null || true)"
fi

jq -c '{
    ok: true,
    updated_document_ids: (.updated_document_ids // []),
    skipped_document_ids: (.skipped_document_ids // [])
}' "$tmp_resp"

log "ok: session_id=${session_id}"
