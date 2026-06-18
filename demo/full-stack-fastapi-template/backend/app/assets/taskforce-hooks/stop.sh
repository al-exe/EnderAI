#!/usr/bin/env bash
# Claude Code Stop hook → Taskforce observe (TF-178 / Phase 4).
#
# Wired into ~/.claude/settings.json as a Stop hook. Fires every time the
# agent finishes a turn and goes idle — NOT just when the session truly
# ends (see session-end.sh for that, TF-228). Reads the session transcript,
# redacts obvious secrets, ships a digest to /v2/taskforce/observe with
# `kind: "checkpoint"`. The backend runs materiality → summarizer → PATCH
# the active document (or creates a new one).
#
# - Never blocks the session (all failures exit 0).
# - Defaults to shadow mode server-side (TASKFORCE_OBSERVE_SHADOW=1 on the
#   backend env until manual review confirms it's safe to flip).
#
# Required:
#   ~/.taskforce_mcp_token  (Connect Agent flow)
# Optional:
#   ENDERAI_BACKEND_URL     (default https://enderai-backend.onrender.com)
#   TASKFORCE_HOOK_DEBUG    (set to 1 to mirror logs to stderr)
#
# Plan: ~/dev/docs/claude-mcp-brainstorm.md §4, §7.4
# Ticket: TF-178

set -uo pipefail

readonly LOG_FILE="${HOME}/.claude/taskforce-observe.log"
readonly TOKEN_FILE="${HOME}/.taskforce_mcp_token"
readonly LEGACY_TOKEN_FILE="${HOME}/.enderai_mcp_token"
readonly STATE_DIR="${HOME}/.taskforce"
readonly BACKEND_URL="${ENDERAI_BACKEND_URL:-https://enderai-backend.onrender.com}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly TRANSCRIPT_JQ="${SCRIPT_DIR}/transcript-extract.jq"
readonly COMMANDS_JQ="${SCRIPT_DIR}/commands-extract.jq"

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

session_id="$(jq -r '.session_id // empty' <<<"$payload" 2>/dev/null)"
transcript_path="$(jq -r '.transcript_path // empty' <<<"$payload" 2>/dev/null)"
cwd="$(jq -r '.cwd // empty' <<<"$payload" 2>/dev/null)"

prompt_user="$(
    jq -r '
        (.prompt // "")
        | if length > 8000 then .[:7997] + "..." else . end
    ' <<<"$payload" 2>/dev/null
)"

# Build a compact transcript from the session JSONL (best effort).
transcript_array="[]"
files_touched="[]"
commands_run="[]"
harness_payload="null"

if [[ -n "$transcript_path" && -r "$transcript_path" ]]; then
    # Last ~200 turns is plenty for a checkpoint summary.
    transcript_array="$(
        tail -n 200 "$transcript_path" 2>/dev/null \
            | jq -sf "$TRANSCRIPT_JQ" 2>/dev/null
    )"
    [[ -z "$transcript_array" || "$transcript_array" == "null" ]] && transcript_array="[]"

    # Rough heuristic: pull file paths the assistant emitted via Edit/Write tool calls.
    files_touched="$(
        tail -n 400 "$transcript_path" 2>/dev/null \
            | jq -sc '[
                .[] | select(.message?.content?[]? | (.type == "tool_use" and (.name == "Edit" or .name == "Write" or .name == "MultiEdit")))
                | .message.content[] | select(.type == "tool_use" and (.name == "Edit" or .name == "Write" or .name == "MultiEdit"))
                | .input.file_path? // empty
            ] | unique | map(select(. != ""))' 2>/dev/null
    )"
    [[ -z "$files_touched" || "$files_touched" == "null" ]] && files_touched="[]"

    # Shell commands run via Bash tool.
    commands_run="$(
        tail -n 400 "$transcript_path" 2>/dev/null \
            | jq -sf "$COMMANDS_JQ" 2>/dev/null
    )"
    [[ -z "$commands_run" || "$commands_run" == "null" ]] && commands_run="[]"

    # Sum assistant turn usage as the authoritative harness total.
    harness_payload="$(
        tail -n 400 "$transcript_path" 2>/dev/null \
            | jq -sc '
                [.[] | select(.type == "assistant" and .message.usage)] as $turns
                | if ($turns | length) == 0 then null else {
                    model_id: ($turns[-1].message.model // "unknown"),
                    total_input_tokens: ([$turns[].message.usage.input_tokens // 0] | add),
                    total_output_tokens: ([$turns[].message.usage.output_tokens // 0] | add),
                    total_cache_read_tokens: ([$turns[].message.usage.cache_read_input_tokens // 0] | add),
                    total_cache_write_tokens: ([$turns[].message.usage.cache_creation_input_tokens // 0] | add)
                  } end' 2>/dev/null
    )"
    [[ -z "$harness_payload" ]] && harness_payload="null"
fi

# Session duration: span between the first and last transcript timestamps.
duration_ms=0
if [[ -n "$transcript_path" && -r "$transcript_path" ]]; then
    duration_ms="$(
        tail -n 400 "$transcript_path" 2>/dev/null \
            | jq -sr '
                [.[] | .timestamp // empty
                       | (try (fromdateiso8601 * 1000) catch empty)] as $ts
                | if ($ts | length) >= 2 then (($ts | max) - ($ts | min)) else 0 end
                | floor' 2>/dev/null
    )"
    [[ -z "$duration_ms" || "$duration_ms" == "null" ]] && duration_ms=0
fi

# Active git branch (best effort; the hook runs in the session cwd).
branch=""
if [[ -n "$cwd" && -d "$cwd" ]]; then
    branch="$(git -C "$cwd" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
fi

# Pin the active document if the user-prompt-submit hook stashed one.
active_doc_id="null"
if [[ -n "$session_id" && -f "${STATE_DIR}/${session_id}.active" ]]; then
    active_doc_id="\"$(cat "${STATE_DIR}/${session_id}.active" | tr -d '\r\n')\""
fi

body="$(jq -cn \
    --arg session_id "$session_id" \
    --arg cwd "$cwd" \
    --arg branch "$branch" \
    --arg prompt "$prompt_user" \
    --argjson transcript "$transcript_array" \
    --argjson files "$files_touched" \
    --argjson commands "$commands_run" \
    --argjson harness "$harness_payload" \
    --argjson active "$active_doc_id" \
    --argjson duration_ms "${duration_ms:-0}" \
    '{
        kind: "checkpoint",
        prompt: $prompt,
        transcript: $transcript,
        active_document_id: $active,
        session_id: (if $session_id == "" then null else $session_id end),
        cwd: (if $cwd == "" then null else $cwd end),
        branch: (if $branch == "" then null else $branch end),
        client: "claude-code",
        files_touched: $files,
        commands_run: $commands,
        duration_ms: $duration_ms,
        harness: $harness
    }' 2>>"$LOG_FILE")"

if [[ -z "$body" ]]; then
    log "skip: could not build observe body"
    exit 0
fi

http_status="$(
    curl -sS \
        -o "${STATE_DIR}/${session_id}.observe-response.json" \
        -w '%{http_code}' \
        --max-time 30 \
        -X POST \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        --data "$body" \
        "${BACKEND_URL}/api/v1/v2/taskforce/observe" 2>>"$LOG_FILE"
)" || { log "skip: curl failed"; exit 0; }

if [[ -n "$session_id" && ( "$http_status" == "200" || "$http_status" == "202" ) ]]; then
    doc_id="$(
        jq -r '.document_id // empty' \
            "${STATE_DIR}/${session_id}.observe-response.json" 2>/dev/null || true
    )"
    if [[ -n "$doc_id" ]]; then
        printf '%s' "$doc_id" > "${STATE_DIR}/${session_id}.active"
    fi
fi
rm -f "${STATE_DIR}/${session_id}.observe-response.json"

log "POST /v2/taskforce/observe → ${http_status}"

# Mark turn finished last so checkpoint observe cannot advance last_seen_at past
# last_turn_ended_at and flip Fleet back to running.
if [[ -n "$session_id" ]]; then
    turn_status="$(
        curl -sS \
            -o /dev/null \
            -w '%{http_code}' \
            --max-time 5 \
            -X POST \
            -H "Authorization: Bearer ${token}" \
            -H "Content-Type: application/json" \
            --data "$(jq -cn --arg sid "$session_id" '{session_id: $sid, demo: false}')" \
            "${BACKEND_URL}/api/v1/v2/taskforce/session/turn-ended" 2>>"$LOG_FILE"
    )" || turn_status="curl-failed"
    log "POST /v2/taskforce/session/turn-ended → ${turn_status}"
fi

# ── Inbox: deliver any queued "reply to agent" prompt (TF-260). ──────
# When the user has queued a prompt for this now-idle agent from the
# Sessions page, claim it and re-inject it as a fresh user turn via the
# Stop-hook decision:block contract — Claude treats "reason" as the next
# user prompt. The claim is one-shot server-side, so when the queue is
# empty we print nothing and the agent stops normally (no infinite loop).
# This is the LAST thing the hook does: stdout must carry only this JSON.
if [[ -n "$session_id" ]]; then
    claim_response="$(
        curl -sS \
            --max-time 5 \
            -X POST \
            -H "Authorization: Bearer ${token}" \
            -H "Content-Type: application/json" \
            --data "$(jq -cn --arg sid "$session_id" '{session_id: $sid, demo: false}')" \
            "${BACKEND_URL}/api/v1/v2/taskforce/session/inbox/claim" 2>>"$LOG_FILE"
    )" || claim_response=""
    if [[ -n "$claim_response" ]]; then
        queued_prompt="$(jq -r '.message // empty' <<<"$claim_response" 2>/dev/null)"
        if [[ -n "$queued_prompt" ]]; then
            log "inbox: injecting queued prompt (${#queued_prompt} chars)"
            jq -cn --arg reason "$queued_prompt" '{decision: "block", reason: $reason}'
            exit 0
        fi
    fi
fi
