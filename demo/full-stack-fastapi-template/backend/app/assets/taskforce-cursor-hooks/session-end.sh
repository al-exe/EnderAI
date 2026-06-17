#!/usr/bin/env bash
# Cursor SessionEnd hook → Taskforce observe (TF-228).
#
# Wired into ~/.claude/settings.json as a SessionEnd hook. Fires once when
# the user's Claude Code session truly terminates (exit, /clear, etc.) —
# unlike the Stop hook (stop.sh), which fires on every agent-idle turn.
# Ships a minimal digest to /v2/taskforce/observe with
# `kind: "session_end"`, which marks the session archive's `ended_at` and
# removes it from the active Sessions roster.
#
# - Never blocks the session (all failures exit 0).
# - Sends no transcript/structured fields, so the payload is "not material"
#   and the backend skips the summarizer entirely — this is a cheap
#   heartbeat-style call.
#
# Required:
#   ~/.taskforce_mcp_token  (Connect Agent flow)
# Optional:
#   ENDERAI_BACKEND_URL     (default https://enderai-backend.onrender.com)
#   TASKFORCE_HOOK_DEBUG    (set to 1 to mirror logs to stderr)
#
# Plan: ~/dev/docs/claude-mcp-brainstorm.md §4, §7.4
# Ticket: TF-228

set -uo pipefail

readonly LOG_FILE="${HOME}/.cursor/taskforce-observe.log"
readonly TOKEN_FILE="${HOME}/.taskforce_mcp_token"
readonly LEGACY_TOKEN_FILE="${HOME}/.enderai_mcp_token"
readonly STATE_DIR="${HOME}/.taskforce"
readonly BACKEND_URL="${ENDERAI_BACKEND_URL:-https://enderai-backend.onrender.com}"

mkdir -p "$(dirname "$LOG_FILE")" "$STATE_DIR"

log() {
    local msg="[$(date -u +%FT%TZ)] $*"
    printf '%s\n' "$msg" >> "$LOG_FILE"
    if [[ "${TASKFORCE_HOOK_DEBUG:-0}" == "1" ]]; then
        printf '%s\n' "$msg" >&2
    fi
}

trap 'exit 0' EXIT

command -v jq   >/dev/null 2>&1 || { log "skip: jq missing";   exit 0; }
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

session_id="$(jq -r '.session_id // .conversation_id // empty' <<<"$payload" 2>/dev/null)"
cwd="$(jq -r '.cwd // empty' <<<"$payload" 2>/dev/null)"

# Active git branch (best effort; the hook runs in the session cwd).
branch=""
if [[ -n "$cwd" && -d "$cwd" ]]; then
    branch="$(git -C "$cwd" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
fi

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
        client: "cursor"
    }' 2>>"$LOG_FILE")"

if [[ -z "$body" ]]; then
    log "skip: could not build observe body"
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
)" || { log "skip: curl failed"; exit 0; }

log "POST /v2/taskforce/observe (session_end) → ${http_status}"

# Clear per-session state now that the session has truly ended.
if [[ -n "$session_id" ]]; then
    rm -f "${STATE_DIR}/${session_id}.active" "${STATE_DIR}/${session_id}.counter"
fi
