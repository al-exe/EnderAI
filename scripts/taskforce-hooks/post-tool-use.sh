#!/usr/bin/env bash
# Claude Code PostToolUse hook → Taskforce checkpoint observe (TF-178).
#
# Fires after every tool call. We don't actually call /observe every tool
# call — that's too noisy and expensive. Instead we tick a counter in
# ~/.taskforce/<session_id>.counter and only POST when the counter
# rolls over the threshold (default 10).
#
# When the threshold trips, the script forwards to stop.sh's body
# builder by re-using the same transcript-path logic, but ships
# `kind: "checkpoint"` with a monotonically-increasing checkpoint_index.
#
# Plan: ~/dev/docs/claude-mcp-brainstorm.md §4.5, §7.4
# Ticket: TF-178

set -uo pipefail

readonly LOG_FILE="${HOME}/.claude/taskforce-observe.log"
readonly TOKEN_FILE="${HOME}/.enderai_mcp_token"
readonly STATE_DIR="${HOME}/.taskforce"
readonly BACKEND_URL="${ENDERAI_BACKEND_URL:-https://enderai-backend.onrender.com}"
readonly CHECKPOINT_EVERY="${TASKFORCE_CHECKPOINT_EVERY:-10}"

mkdir -p "$(dirname "$LOG_FILE")" "$STATE_DIR"

log() {
    local msg="[$(date -u +%FT%TZ)] $*"
    printf '%s\n' "$msg" >> "$LOG_FILE"
    if [[ "${TASKFORCE_HOOK_DEBUG:-0}" == "1" ]]; then
        printf '%s\n' "$msg" >&2
    fi
}

trap 'exit 0' EXIT

command -v jq   >/dev/null 2>&1 || exit 0
command -v curl >/dev/null 2>&1 || exit 0

if [[ "${TASKFORCE_HOOKS_DISABLED:-0}" == "1" ]]; then
    log "skip: TASKFORCE_HOOKS_DISABLED=1"
    exit 0
fi

if [[ ! -r "$TOKEN_FILE" ]]; then
    exit 0
fi
token="$(tr -d '\r\n' < "$TOKEN_FILE")"
[[ -z "$token" ]] && exit 0

payload="$(cat || true)"
[[ -z "$payload" ]] && exit 0

session_id="$(jq -r '.session_id // empty' <<<"$payload" 2>/dev/null)"
transcript_path="$(jq -r '.transcript_path // empty' <<<"$payload" 2>/dev/null)"
cwd="$(jq -r '.cwd // empty' <<<"$payload" 2>/dev/null)"

if [[ -z "$session_id" ]]; then
    exit 0
fi

counter_file="${STATE_DIR}/${session_id}.counter"
current="$(cat "$counter_file" 2>/dev/null || echo 0)"
next=$((current + 1))
printf '%s' "$next" > "$counter_file"

if (( next % CHECKPOINT_EVERY != 0 )); then
    exit 0
fi

# It's a checkpoint turn — build a minimal payload from recent transcript.
checkpoint_index=$((next / CHECKPOINT_EVERY))

if [[ -z "$transcript_path" || ! -r "$transcript_path" ]]; then
    log "skip checkpoint: transcript unreadable"
    exit 0
fi

# Recent 80 turns is enough for a mid-session delta.
transcript_array="$(
    tail -n 80 "$transcript_path" 2>/dev/null \
        | jq -sc '[.[] | select(.type == "assistant" or .type == "user" or .type == "tool_result") | {
            role: (if .type == "user" then "user" elif .type == "assistant" then "assistant" else "tool" end),
            content: (
                if .type == "assistant" then ([.message.content[]? | select(.type == "text") | .text] | join("\n"))
                elif .type == "user" then (.message.content // "")
                else (.content // "" | tostring) end
            )
        }]' 2>/dev/null
)"
[[ -z "$transcript_array" || "$transcript_array" == "null" ]] && transcript_array="[]"

# Pull the same files-touched / commands-run shape Stop builds.
files_touched="$(
    tail -n 200 "$transcript_path" 2>/dev/null \
        | jq -sc '[
            .[] | select(.message?.content?[]? | (.type == "tool_use" and (.name == "Edit" or .name == "Write" or .name == "MultiEdit")))
            | .message.content[] | select(.type == "tool_use" and (.name == "Edit" or .name == "Write" or .name == "MultiEdit"))
            | .input.file_path? // empty
        ] | unique | map(select(. != ""))' 2>/dev/null
)"
[[ -z "$files_touched" || "$files_touched" == "null" ]] && files_touched="[]"

commands_run="$(
    tail -n 200 "$transcript_path" 2>/dev/null \
        | jq -sc '[
            .[] | select(.message?.content?[]? | (.type == "tool_use" and .name == "Bash"))
            | .message.content[] | select(.type == "tool_use" and .name == "Bash")
            | { cmd: (.input.command // ""), exit_code: null }
        ] | map(select(.cmd != ""))' 2>/dev/null
)"
[[ -z "$commands_run" || "$commands_run" == "null" ]] && commands_run="[]"

active_doc_id="null"
if [[ -f "${STATE_DIR}/${session_id}.active" ]]; then
    active_doc_id="\"$(cat "${STATE_DIR}/${session_id}.active" | tr -d '\r\n')\""
fi

body="$(jq -cn \
    --arg session_id "$session_id" \
    --arg cwd "$cwd" \
    --argjson transcript "$transcript_array" \
    --argjson files "$files_touched" \
    --argjson commands "$commands_run" \
    --argjson active "$active_doc_id" \
    --argjson checkpoint_index "$checkpoint_index" \
    '{
        kind: "checkpoint",
        prompt: "",
        transcript: $transcript,
        active_document_id: $active,
        session_id: $session_id,
        cwd: (if $cwd == "" then null else $cwd end),
        files_touched: $files,
        commands_run: $commands,
        duration_ms: 0,
        harness: null,
        checkpoint_index: $checkpoint_index
    }')"

http_status="$(
    curl -sS \
        -o /dev/null \
        -w '%{http_code}' \
        --max-time 15 \
        -X POST \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        --data "$body" \
        "${BACKEND_URL}/api/v1/v2/taskforce/observe" 2>>"$LOG_FILE"
)" || { log "skip checkpoint: curl failed"; exit 0; }

log "checkpoint ${checkpoint_index} → ${http_status}"
