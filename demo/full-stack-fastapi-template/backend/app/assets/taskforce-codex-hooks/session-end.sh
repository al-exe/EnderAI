#!/usr/bin/env bash
# Codex SessionEnd hook -> Taskforce observe.
#
# Sends a cheap session_end payload so the backend marks the archive ended,
# moves it out of the active Sessions roster, and clears per-session state.

set -uo pipefail

readonly LOG_FILE="${HOME}/.codex/taskforce.log"
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

trap 'exit 0' EXIT

command -v jq >/dev/null 2>&1 || { log "skip session_end: jq missing"; exit 0; }
command -v curl >/dev/null 2>&1 || { log "skip session_end: curl missing"; exit 0; }

if [[ "${TASKFORCE_HOOKS_DISABLED:-0}" == "1" ]]; then
    log "skip session_end: TASKFORCE_HOOKS_DISABLED=1"
    exit 0
fi

token_file="$TOKEN_FILE"
if [[ ! -r "$token_file" && -r "$LEGACY_TOKEN_FILE" ]]; then
    token_file="$LEGACY_TOKEN_FILE"
fi
if [[ ! -r "$token_file" ]]; then
    log "skip session_end: no token at $TOKEN_FILE"
    exit 0
fi
token="$(tr -d '\r\n' < "$token_file")"
[[ -z "$token" ]] && { log "skip session_end: token empty"; exit 0; }

payload="$(cat || true)"
[[ -z "$payload" ]] && { log "skip session_end: empty stdin"; exit 0; }

session_id="$(jq -r '.session_id // empty' <<<"$payload" 2>/dev/null)"
cwd="$(taskforce_resolve_cwd_from_payload "$payload")"
branch="$(taskforce_resolve_git_branch_from_payload "$payload" 2>/dev/null || true)"

body="$(jq -cn \
    --arg session_id "$session_id" \
    --arg cwd "$cwd" \
    --arg branch "$branch" \
    '{
        kind: "session_end",
        prompt: "",
        session_id: (if $session_id == "" then null else $session_id end),
        cwd: (if $cwd == "" then null else $cwd end),
        branch: (if $branch == "" then null else $branch end),
        client: "codex"
    }' 2>>"$LOG_FILE")"

if [[ -z "$body" ]]; then
    log "skip session_end: could not build observe body"
    exit 0
fi

http_status="$(
    curl -sS \
        -o /dev/null \
        -w '%{http_code}' \
        --max-time 30 \
        -X POST \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        --data "$body" \
        "${BACKEND_URL}/api/v1/v2/taskforce/observe" 2>>"$LOG_FILE"
)" || { log "skip session_end: curl failed"; exit 0; }

log "POST /v2/taskforce/observe (session_end) -> ${http_status}"

if [[ -n "$session_id" ]]; then
    rm -f \
        "${STATE_DIR}/${session_id}.active" \
        "${STATE_DIR}/${session_id}.codex-counter"
fi
