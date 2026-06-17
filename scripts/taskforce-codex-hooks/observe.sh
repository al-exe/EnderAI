#!/usr/bin/env bash
# Codex Stop/PostToolUse hook -> Taskforce observe.

set -uo pipefail

readonly LOG_FILE="${HOME}/.codex/taskforce.log"
readonly TOKEN_FILE="${HOME}/.taskforce_mcp_token"
readonly LEGACY_TOKEN_FILE="${HOME}/.enderai_mcp_token"
readonly STATE_DIR="${HOME}/.taskforce"
readonly BACKEND_URL="${ENDERAI_BACKEND_URL:-https://enderai-backend.onrender.com}"
readonly CHECKPOINT_EVERY="${TASKFORCE_CODEX_CHECKPOINT_EVERY:-4}"

mkdir -p "$(dirname "$LOG_FILE")" "$STATE_DIR"

hook_event_name=""
did_emit=0

log() {
    printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG_FILE"
}

emit_continue() {
    if [[ "$hook_event_name" == "Stop" && "$did_emit" == "0" ]]; then
        printf '{"continue":true,"suppressOutput":true}\n'
        did_emit=1
    fi
}

trap 'emit_continue; exit 0' EXIT

command -v jq >/dev/null 2>&1 || { log "skip observe: jq missing"; exit 0; }
command -v curl >/dev/null 2>&1 || { log "skip observe: curl missing"; exit 0; }

if [[ "${TASKFORCE_HOOKS_DISABLED:-0}" == "1" ]]; then
    log "skip observe: TASKFORCE_HOOKS_DISABLED=1"
    exit 0
fi

payload="$(cat || true)"
[[ -z "$payload" ]] && { log "skip observe: empty stdin"; exit 0; }

hook_event_name="$(jq -r '.hook_event_name // empty' <<<"$payload" 2>/dev/null)"
session_id="$(jq -r '.session_id // empty' <<<"$payload" 2>/dev/null)"
transcript_path="$(jq -r '.transcript_path // empty' <<<"$payload" 2>/dev/null)"
cwd="$(jq -r '.cwd // empty' <<<"$payload" 2>/dev/null)"
model="$(jq -r '.model // empty' <<<"$payload" 2>/dev/null)"
tool_name="$(jq -r '.tool_name // empty' <<<"$payload" 2>/dev/null)"
last_assistant_message="$(jq -r '.last_assistant_message // empty' <<<"$payload" 2>/dev/null)"

[[ -z "$session_id" ]] && { log "skip observe: no session_id"; exit 0; }

if [[ "$hook_event_name" == "PostToolUse" ]]; then
    counter_file="${STATE_DIR}/${session_id}.codex-counter"
    current="$(cat "$counter_file" 2>/dev/null || echo 0)"
    next=$((current + 1))
    printf '%s' "$next" > "$counter_file"
    if (( next % CHECKPOINT_EVERY != 0 )); then
        exit 0
    fi
    checkpoint_index=$((next / CHECKPOINT_EVERY))
else
    checkpoint_index=0
fi

token_file="$TOKEN_FILE"
if [[ ! -r "$token_file" && -r "$LEGACY_TOKEN_FILE" ]]; then
    token_file="$LEGACY_TOKEN_FILE"
fi
if [[ ! -r "$token_file" ]]; then
    log "skip observe: no token at $TOKEN_FILE"
    exit 0
fi
token="$(tr -d '\r\n' < "$token_file")"
[[ -z "$token" ]] && { log "skip observe: token empty"; exit 0; }

branch=""
if [[ -n "$cwd" && -d "$cwd" ]] && command -v git >/dev/null 2>&1; then
    branch="$(git -C "$cwd" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
fi

recent_turns="[]"
commands_run="[]"
duration_ms=0

if [[ -n "$transcript_path" && -r "$transcript_path" ]]; then
    recent_turns="$(
        tail -n 240 "$transcript_path" 2>/dev/null \
            | jq -sc '
                def text_content:
                    if (.payload.content | type) == "array" then
                        [.payload.content[]?
                            | (.text // .input_text // .output_text // .content // empty)
                            | strings
                        ] | join("\n")
                    else
                        (.payload.content // "" | tostring)
                    end;
                [.[] | select(.payload.type == "message")
                    | select(.payload.role == "user" or .payload.role == "assistant")
                    | {role: .payload.role, content: (text_content | gsub("[[:space:]]+"; " ") | .[:2000])}
                    | select(.content != "")
                ] | .[-20:]' 2>/dev/null
    )"
    [[ -z "$recent_turns" || "$recent_turns" == "null" ]] && recent_turns="[]"

    commands_run="$(
        tail -n 240 "$transcript_path" 2>/dev/null \
            | jq -sc '
                [.[] | select(.payload.type == "function_call")
                    | select(.payload.name == "exec_command")
                    | (.payload.arguments | fromjson? // {})
                    | .cmd? // empty
                    | strings
                    | {cmd: .[:2000], exit_code: null, output: null}
                ] | .[-12:]' 2>/dev/null
    )"
    [[ -z "$commands_run" || "$commands_run" == "null" ]] && commands_run="[]"

    duration_ms="$(
        tail -n 400 "$transcript_path" 2>/dev/null \
            | jq -sr '
                [.[] | .timestamp // empty | (try (fromdateiso8601 * 1000) catch empty)] as $ts
                | if ($ts | length) >= 2 then (($ts | max) - ($ts | min)) else 0 end
                | floor' 2>/dev/null
    )"
    [[ -z "$duration_ms" || "$duration_ms" == "null" ]] && duration_ms=0
fi

last_user="$(
    jq -r '[.[] | select(.role == "user") | .content] | last // ""' <<<"$recent_turns" 2>/dev/null
)"
if [[ -z "$last_assistant_message" ]]; then
    last_assistant_message="$(
        jq -r '[.[] | select(.role == "assistant") | .content] | last // ""' <<<"$recent_turns" 2>/dev/null
    )"
fi

active_doc_id="null"
if [[ -f "${STATE_DIR}/${session_id}.active" ]]; then
    active_doc_id="\"$(tr -d '\r\n' < "${STATE_DIR}/${session_id}.active")\""
fi

details_markdown="$(
    jq -rn \
        --arg last_user "$last_user" \
        --arg last_assistant "$last_assistant_message" \
        --arg tool_name "$tool_name" \
        --arg branch "$branch" '
        [
            (if $last_user != "" then "Latest user prompt: " + $last_user else empty end),
            (if $last_assistant != "" then "Latest Codex response: " + $last_assistant else empty end),
            (if $tool_name != "" then "Latest tool: " + $tool_name else empty end),
            (if $branch != "" then "Branch: " + $branch else empty end)
        ] | map("- " + .[:900]) | join("\n") | .[:3900]'
)"
[[ -z "$details_markdown" ]] && details_markdown="- Codex session checkpoint."

harness_payload="null"
if [[ -n "$model" ]]; then
    harness_payload="$(jq -cn --arg model "$model" '{
        model_id: $model,
        total_input_tokens: 0,
        total_output_tokens: 0,
        total_cache_read_tokens: 0,
        total_cache_write_tokens: 0
    }')"
fi

body="$(
    jq -cn \
        --arg session_id "$session_id" \
        --arg cwd "$cwd" \
        --arg branch "$branch" \
        --arg prompt "$last_user" \
        --arg last_user "$last_user" \
        --arg last_assistant "$last_assistant_message" \
        --arg details "$details_markdown" \
        --argjson active "$active_doc_id" \
        --argjson commands "$commands_run" \
        --argjson duration_ms "${duration_ms:-0}" \
        --argjson harness "$harness_payload" \
        --argjson checkpoint_index "$checkpoint_index" \
        '{
            kind: "checkpoint",
            prompt: $prompt[:8000],
            transcript: [],
            active_document_id: $active,
            session_id: $session_id,
            cwd: (if $cwd == "" then null else $cwd end),
            branch: (if $branch == "" then null else $branch end),
            client: "codex",
            files_touched: [],
            commands_run: $commands,
            duration_ms: $duration_ms,
            harness: $harness,
            checkpoint_index: (if $checkpoint_index == 0 then null else $checkpoint_index end),
            summary_points: ([
                (if $last_user != "" then "User asked: " + $last_user else empty end),
                (if $last_assistant != "" then "Codex reported: " + $last_assistant else empty end)
            ] | map(.[:1200])),
            details_sections: [{anchor_id: "codex-latest-turn", markdown: $details}],
            decisions: [],
            outcome: null
        }' 2>>"$LOG_FILE"
)"

[[ -z "$body" ]] && { log "skip observe: could not build body"; exit 0; }

response_file="$(mktemp)"
http_status="$(
    curl -sS \
        -o "$response_file" \
        -w '%{http_code}' \
        --max-time 15 \
        -X POST \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        --data "$body" \
        "${BACKEND_URL}/api/v1/v2/taskforce/observe" 2>>"$LOG_FILE"
)" || { rm -f "$response_file"; log "skip observe: curl failed"; exit 0; }

if [[ "$http_status" == "200" || "$http_status" == "202" ]]; then
    doc_id="$(jq -r '.document_id // empty' "$response_file" 2>/dev/null || true)"
    if [[ -n "$doc_id" ]]; then
        printf '%s' "$doc_id" > "${STATE_DIR}/${session_id}.active"
    fi
    action="$(jq -r '.action // "unknown"' "$response_file" 2>/dev/null || echo unknown)"
    reason="$(jq -r '.reason // ""' "$response_file" 2>/dev/null || true)"
    log "POST /v2/taskforce/observe (${hook_event_name:-manual}) -> ${http_status} ${action} ${reason}"
else
    log "skip observe: returned ${http_status}"
fi

rm -f "$response_file"
