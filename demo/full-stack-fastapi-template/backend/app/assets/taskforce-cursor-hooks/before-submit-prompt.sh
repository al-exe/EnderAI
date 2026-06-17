#!/usr/bin/env bash
# Cursor beforeSubmitPrompt hook -> Taskforce discovery + active doc pin.
#
# Cursor does not prepend stdout text like Claude Code, so this hook records
# consultation metrics, pins a high-confidence match when present, and relies
# on MCP `taskforce_session_start` (via Connect Agent instructions) for full
# preamble injection when hooks alone are insufficient.

set -uo pipefail

readonly LOG_FILE="${HOME}/.cursor/taskforce-discover.log"
readonly TOKEN_FILE="${HOME}/.taskforce_mcp_token"
readonly LEGACY_TOKEN_FILE="${HOME}/.enderai_mcp_token"
readonly STATE_DIR="${HOME}/.taskforce"
readonly BACKEND_URL="${ENDERAI_BACKEND_URL:-https://enderai-backend.onrender.com}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/git-context.sh"

mkdir -p "$(dirname "$LOG_FILE")" "$STATE_DIR"

log() {
    printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG_FILE"
}

response_file=""
cleanup() {
    [[ -n "$response_file" ]] && rm -f "$response_file"
}
trap 'cleanup; exit 0' EXIT

command -v jq >/dev/null 2>&1 || { log "skip: jq missing"; exit 0; }
command -v curl >/dev/null 2>&1 || { log "skip: curl missing"; exit 0; }

if [[ "${TASKFORCE_HOOKS_DISABLED:-0}" == "1" ]]; then
    log "skip: TASKFORCE_HOOKS_DISABLED=1"
    printf '%s\n' '{"continue": true}'
    exit 0
fi

token_file="$TOKEN_FILE"
if [[ ! -r "$token_file" && -r "$LEGACY_TOKEN_FILE" ]]; then
    token_file="$LEGACY_TOKEN_FILE"
fi
if [[ ! -r "$token_file" ]]; then
    log "skip: no token at $TOKEN_FILE"
    printf '%s\n' '{"continue": true}'
    exit 0
fi
token="$(tr -d '\r\n' < "$token_file")"
[[ -z "$token" ]] && { log "skip: token empty"; printf '%s\n' '{"continue": true}'; exit 0; }

payload="$(cat || true)"
[[ -z "$payload" ]] && { log "skip: empty stdin"; printf '%s\n' '{"continue": true}'; exit 0; }

prompt="$(jq -r '.prompt // empty' <<<"$payload" 2>/dev/null)"
session_id="$(
    jq -r '.session_id // .conversation_id // empty' <<<"$payload" 2>/dev/null
)"
cwd="$(taskforce_resolve_cwd_from_payload "$payload")"
[[ -z "$prompt" ]] && { log "skip: no prompt"; printf '%s\n' '{"continue": true}'; exit 0; }
[[ -z "$session_id" ]] && { log "skip: no session_id"; printf '%s\n' '{"continue": true}'; exit 0; }

git_branch="$(taskforce_resolve_git_branch_from_payload "$payload" 2>/dev/null || true)"

body="$(jq -cn \
    --arg prompt "$prompt" \
    --arg cwd "$cwd" \
    --arg session_id "$session_id" \
    --arg git_branch "$git_branch" \
    '{
        prompt: $prompt,
        cwd: (if $cwd == "" then null else $cwd end),
        session_id: $session_id,
        git_branch: (if $git_branch == "" then null else $git_branch end),
        client: "cursor",
        min_score: 0.2
    }')"

response_file="$(mktemp)"
http_status="$(
    curl -sS \
        -o "$response_file" \
        -w '%{http_code}' \
        --max-time 4 \
        -X POST \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        --data "$body" \
        "${BACKEND_URL}/api/v1/v2/taskforce/discover" 2>>"$LOG_FILE"
)" || { log "skip: curl failed"; printf '%s\n' '{"continue": true}'; exit 0; }

if [[ "$http_status" != "200" ]]; then
    log "skip: discover returned ${http_status}"
    printf '%s\n' '{"continue": true}'
    exit 0
fi

match_count="$(jq '.matches | length' "$response_file" 2>/dev/null || echo 0)"
if [[ "$match_count" == "0" ]]; then
    log "no matches"
    printf '%s\n' '{"continue": true}'
    exit 0
fi

suggested_pin="$(jq -r '.suggested_pin // empty' "$response_file" 2>/dev/null)"
if [[ -n "$suggested_pin" ]]; then
    printf '%s' "$suggested_pin" > "${STATE_DIR}/${session_id}.active"
fi

log "ok: ${match_count} matches discovered"
printf '%s\n' '{"continue": true}'
