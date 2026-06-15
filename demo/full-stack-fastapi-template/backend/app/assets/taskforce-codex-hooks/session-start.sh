#!/usr/bin/env bash
# Codex SessionStart hook -> Taskforce Fleet heartbeat.

set -uo pipefail

readonly LOG_FILE="${HOME}/.codex/taskforce.log"
readonly TOKEN_FILE="${HOME}/.taskforce_mcp_token"
readonly LEGACY_TOKEN_FILE="${HOME}/.enderai_mcp_token"
readonly BACKEND_URL="${ENDERAI_BACKEND_URL:-https://enderai-backend.onrender.com}"

mkdir -p "$(dirname "$LOG_FILE")"

log() {
    printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG_FILE"
}

trap 'exit 0' EXIT

command -v jq >/dev/null 2>&1 || { log "skip: jq missing"; exit 0; }
command -v curl >/dev/null 2>&1 || { log "skip: curl missing"; exit 0; }

if [[ "${TASKFORCE_HOOKS_DISABLED:-0}" == "1" ]]; then
    log "skip: TASKFORCE_HOOKS_DISABLED=1"
    exit 0
fi

token_file="$TOKEN_FILE"
if [[ ! -r "$token_file" && -r "$LEGACY_TOKEN_FILE" ]]; then
    token_file="$LEGACY_TOKEN_FILE"
fi
if [[ ! -r "$token_file" ]]; then
    log "skip: no token at $TOKEN_FILE"
    exit 0
fi
token="$(tr -d '\r\n' < "$token_file")"
[[ -z "$token" ]] && { log "skip: token empty"; exit 0; }

payload="$(cat || true)"
[[ -z "$payload" ]] && { log "skip: empty stdin"; exit 0; }

session_id="$(jq -r '.session_id // empty' <<<"$payload" 2>/dev/null)"
cwd="$(jq -r '.cwd // empty' <<<"$payload" 2>/dev/null)"
model="$(jq -r '.model // empty' <<<"$payload" 2>/dev/null)"
source="$(jq -r '.source // empty' <<<"$payload" 2>/dev/null)"
[[ -z "$session_id" ]] && { log "skip: no session_id"; exit 0; }

git_branch=""
if [[ -n "$cwd" && -d "$cwd" ]] && command -v git >/dev/null 2>&1; then
    git_branch="$(git -C "$cwd" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
fi

body="$(jq -cn \
    --arg session_id "$session_id" \
    --arg cwd "$cwd" \
    --arg git_branch "$git_branch" \
    --arg model_id "$model" \
    --arg source "$source" \
    '{
        session_id: $session_id,
        cwd: (if $cwd == "" then null else $cwd end),
        git_branch: (if $git_branch == "" then null else $git_branch end),
        client: "codex",
        model_id: (if $model_id == "" then null else $model_id end),
        source: (if $source == "" then null else $source end)
    }')"

http_status="$(
    curl -sS \
        -o /dev/null \
        -w '%{http_code}' \
        --max-time 8 \
        -X POST \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        --data "$body" \
        "${BACKEND_URL}/api/v1/v2/taskforce/session/heartbeat" 2>>"$LOG_FILE"
)" || { log "skip: curl failed"; exit 0; }

log "POST /v2/taskforce/session/heartbeat -> ${http_status}"
