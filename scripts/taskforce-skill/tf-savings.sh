#!/usr/bin/env bash
# /tf — savings step (TF-188).
#
# GET /v2/taskforce/session-savings?session_id=...&pricing_model_id=claude-opus-4-7.
# Always exits 0; emits a JSON envelope.
#
# Demo-locked decision (plan §0 / TF-190): pricing_model_id is hardcoded
# to claude-opus-4-7 regardless of what model is actually running so the
# savings number is reproducible across recording takes. TF-190 swaps
# this for auto-detect post-demo.
#
# Flags:
#   --session-id <uuid>  (required)
#
# Output JSON:
#   { "ok": true, "session_id", "net_saved_tokens", "usd_saved",
#     "doc_count", "metrics_url" }
#   { "ok": false, "reason": "...", "detail": "..." }

set -uo pipefail

readonly LOG_FILE="${HOME}/.claude/taskforce-skill.log"
readonly TOKEN_FILE="${HOME}/.enderai_mcp_token"
readonly BACKEND_URL="${TASKFORCE_BACKEND_URL:-${ENDERAI_BACKEND_URL:-https://enderai-backend.onrender.com}}"
readonly FRONTEND_HOST="${TASKFORCE_FRONTEND_HOST:-https://www.taskforce.tools}"
readonly PRICING_MODEL_ID="claude-opus-4-7"

log() { printf '[%s] tf-savings %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG_FILE"; }
emit_error() {
    local reason="$1" detail="${2:-}"
    log "error: ${reason} ${detail}"
    jq -cn --arg r "$reason" --arg d "$detail" '{ok:false, reason:$r, detail:$d}'
    exit 0
}

command -v jq >/dev/null 2>&1   || emit_error "jq_missing" "install jq"
command -v curl >/dev/null 2>&1 || emit_error "curl_missing" "install curl"

session_id=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --session-id) session_id="$2"; shift 2 ;;
        *)            shift ;;
    esac
done

[[ -z "$session_id" ]]  && emit_error "missing_session_id"
[[ -r "$TOKEN_FILE" ]]  || emit_error "no_token" "$TOKEN_FILE not readable"

token="$(tr -d '\r\n' < "$TOKEN_FILE")"
[[ -z "$token" ]] && emit_error "no_token" "token file empty"

tmp_resp="$(mktemp)"; trap 'rm -f "$tmp_resp"' EXIT

# session_id + pricing_model_id are URL-encoded via curl --data-urlencode + -G.
http_status="$(
    curl -sS -o "$tmp_resp" -w '%{http_code}' \
        --max-time 8 \
        -G \
        --data-urlencode "session_id=${session_id}" \
        --data-urlencode "pricing_model_id=${PRICING_MODEL_ID}" \
        -H "Authorization: Bearer ${token}" \
        "${BACKEND_URL}/api/v1/v2/taskforce/session-savings" 2>>"$LOG_FILE"
)" || emit_error "backend_down" "curl failed"

if [[ "$http_status" != "200" ]]; then
    emit_error "http_${http_status}" "$(head -c 400 "$tmp_resp" 2>/dev/null || true)"
fi

jq -c \
    --arg metrics_url "${FRONTEND_HOST}/v2/metrics?session_id=${session_id}" '
    {
        ok: true,
        session_id: .session_id,
        net_saved_tokens: (.net_saved_tokens // 0),
        usd_saved: (.usd_saved // 0),
        doc_count: (.doc_count // 0),
        pricing_model_id: (.pricing_model_id // "claude-opus-4-7"),
        metrics_url: $metrics_url
    }' "$tmp_resp"

log "ok: session_id=${session_id}"
