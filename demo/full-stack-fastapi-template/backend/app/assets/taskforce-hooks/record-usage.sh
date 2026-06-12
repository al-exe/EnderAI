#!/usr/bin/env bash
# Claude Code Stop hook → Taskforce metrics (per-turn token usage).
#
# Wired into ~/.claude/settings.json as a Stop hook. Fires every time the
# agent finishes a turn and goes idle. Reads the last assistant turn from the
# session transcript and ships its token counts to /v2/metrics/usage so the
# Taskforce Metrics page populates cost charts on its own — independent of
# whether the agent went through the V2 document lifecycle.
#
# - Never blocks the session (all failures exit 0).
# - Fire-and-forget: one cheap POST of the most recent turn's usage.
#
# Required:
#   ~/.taskforce_mcp_token  (Connect Agent flow)
# Optional:
#   ENDERAI_BACKEND_URL     (default https://enderai-backend.onrender.com;
#                            TASKFORCE_BACKEND_URL accepted for back-compat)
#   TASKFORCE_HOOK_DEBUG    (set to 1 to mirror logs to stderr)
#   TASKFORCE_HOOKS_DISABLED (set to 1 to disable all Taskforce hooks)
#
# Plan: ~/dev/docs/claude-mcp-brainstorm.md §4, §7.4

set -uo pipefail

readonly LOG_FILE="${HOME}/.claude/taskforce-observe.log"
readonly TOKEN_FILE="${HOME}/.taskforce_mcp_token"
readonly LEGACY_TOKEN_FILE="${HOME}/.enderai_mcp_token"
readonly BACKEND_URL="${ENDERAI_BACKEND_URL:-${TASKFORCE_BACKEND_URL:-https://enderai-backend.onrender.com}}"

mkdir -p "$(dirname "$LOG_FILE")"

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

# The Stop payload (stdin) points at the session transcript; take the last
# assistant turn carrying usage — scanning from the end keeps it cheap.
transcript="$(jq -r '.transcript_path // empty' <<<"$payload" 2>/dev/null)"
[[ -r "$transcript" ]] || { log "skip: no readable transcript"; exit 0; }
turn="$(tac "$transcript" | awk '/"type":"assistant"/ && /"usage":/ {print; exit}')"
[[ -n "$turn" ]] || { log "skip: no assistant turn with usage"; exit 0; }

usage="$(jq -c '{
  model_id: (.message.model // "unknown"),
  input_tokens: (.message.usage.input_tokens // 0),
  output_tokens: (.message.usage.output_tokens // 0),
  cache_read_input_tokens: (.message.usage.cache_read_input_tokens // 0),
  cache_creation_input_tokens: (.message.usage.cache_creation_input_tokens // 0)
}' <<<"$turn" 2>/dev/null)"
[[ -n "$usage" ]] || { log "skip: could not build usage payload"; exit 0; }

# Skip empty finalization turns where nothing was generated.
[[ "$(jq -r '[.[] | numbers] | add' <<<"$usage")" == 0 ]] && { log "skip: zero-token turn"; exit 0; }

http_status="$(
    curl -sS \
        -o /dev/null \
        -w '%{http_code}' \
        --max-time 8 \
        -X POST \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        --data "$usage" \
        "${BACKEND_URL}/api/v1/v2/metrics/usage?source=hook" 2>>"$LOG_FILE"
)" || { log "skip: curl failed"; exit 0; }

log "POST /v2/metrics/usage → ${http_status}"
