#!/usr/bin/env bash
# /tf — savings step (TF-188 / TF-190).
#
# GET /v2/taskforce/session-savings?session_id=...&pricing_model_id=$CLAUDE_MODEL.
# Always exits 0; emits a JSON envelope.
#
# Uses CLAUDE_MODEL when present, falling back to claude-opus-4-7. Uses
# CLAUDE_EFFORT for display when present; Claude Code does not always expose
# effort in env, so an empty effort label is valid.
#
# Flags:
#   --session-id <uuid>  (required)
#
# Output JSON:
#   { "ok": true, "session_id", "net_saved_tokens", "usd_saved",
#     "doc_count", "pricing_model_id", "model_display", "effort_label",
#     "metrics_url" }
#   { "ok": false, "reason": "...", "detail": "..." }

set -uo pipefail

readonly LOG_FILE="${HOME}/.claude/taskforce-skill.log"
readonly TOKEN_FILE="${HOME}/.taskforce_mcp_token"
readonly LEGACY_TOKEN_FILE="${HOME}/.enderai_mcp_token"
readonly BACKEND_URL="${TASKFORCE_BACKEND_URL:-${ENDERAI_BACKEND_URL:-https://enderai-backend.onrender.com}}"
readonly FRONTEND_HOST="${TASKFORCE_FRONTEND_HOST:-https://www.taskforce.tools}"
readonly PRICING_MODEL_ID="${CLAUDE_MODEL:-claude-opus-4-7}"
readonly CLAUDE_EFFORT_LABEL="${CLAUDE_EFFORT:-}"

log() { printf '[%s] tf-savings %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG_FILE"; }
model_display_name() {
    case "$1" in
        claude-opus-4-7)   printf 'Opus 4.7' ;;
        claude-sonnet-4-6) printf 'Sonnet 4.6' ;;
        claude-haiku-4-5)  printf 'Haiku 4.5' ;;
        *)                printf '%s' "$1" ;;
    esac
}

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
token_file="$TOKEN_FILE"
if [[ ! -r "$token_file" && -r "$LEGACY_TOKEN_FILE" ]]; then
    token_file="$LEGACY_TOKEN_FILE"
fi
[[ -r "$token_file" ]] || emit_error "no_token" "$TOKEN_FILE not readable"

token="$(tr -d '\r\n' < "$token_file")"
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
    --arg fallback_model_id "$PRICING_MODEL_ID" \
    --arg model_display "$(model_display_name "$PRICING_MODEL_ID")" \
    --arg effort_label "$CLAUDE_EFFORT_LABEL" \
    --arg metrics_url "${FRONTEND_HOST}/v2/metrics?session_id=${session_id}" '
    {
        ok: true,
        session_id: .session_id,
        net_saved_tokens: (.net_saved_tokens // 0),
        usd_saved: (.usd_saved // 0),
        doc_count: (.doc_count // 0),
        pricing_model_id: (.pricing_model_id // $fallback_model_id),
        model_display: $model_display,
        effort_label: $effort_label,
        metrics_url: $metrics_url
    }' "$tmp_resp"

log "ok: session_id=${session_id} pricing_model_id=${PRICING_MODEL_ID}"
