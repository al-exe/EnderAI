#!/usr/bin/env bash
# Claude Code Stop hook → EnderAI metrics ingest.
#
# Wired into ~/.claude/settings.json as a Stop hook. Each time Claude
# finishes a response, this script reads the hook's stdin payload,
# pulls the latest assistant turn's usage out of the session transcript
# (which Claude Code writes to ~/.claude/projects/<cwd>/<session>.jsonl),
# and POSTs it to /api/v1/v2/metrics/usage so the Taskforce Metrics
# page reflects real LLM spend.
#
# Failures are silent on purpose — a broken hook should never block a
# user's session. Log lines go to ~/.claude/enderai-record-usage.log
# for debugging.
#
# Required:
#   - ~/.taskforce_mcp_token     (created by the Connect Agent flow)
# Optional:
#   - ENDERAI_BACKEND_URL        (defaults to https://enderai-backend.onrender.com)
#   - ENDERAI_USAGE_SOURCE       (defaults to "hook" — written to metrics_event.payload.source)
#   - ENDERAI_RECORD_USAGE_DEBUG (set to 1 to mirror logs to stderr)

set -uo pipefail

readonly LOG_FILE="${HOME}/.claude/enderai-record-usage.log"
readonly TOKEN_FILE="${HOME}/.taskforce_mcp_token"
readonly LEGACY_TOKEN_FILE="${HOME}/.enderai_mcp_token"
readonly BACKEND_URL="${ENDERAI_BACKEND_URL:-https://enderai-backend.onrender.com}"
readonly SOURCE_LABEL="${ENDERAI_USAGE_SOURCE:-hook}"

log() {
    local msg="[$(date -u +%FT%TZ)] $*"
    printf '%s\n' "$msg" >> "$LOG_FILE"
    if [[ "${ENDERAI_RECORD_USAGE_DEBUG:-0}" == "1" ]]; then
        printf '%s\n' "$msg" >&2
    fi
}

# Always exit 0; a broken hook must never block the user's session.
trap 'exit 0' EXIT

token_file="$TOKEN_FILE"
if [[ ! -r "$token_file" && -r "$LEGACY_TOKEN_FILE" ]]; then
    token_file="$LEGACY_TOKEN_FILE"
fi
if [[ ! -r "$token_file" ]]; then
    log "skip: token file not readable at $TOKEN_FILE"
    exit 0
fi
token="$(tr -d '\r\n' < "$token_file")"
if [[ -z "$token" ]]; then
    log "skip: token file empty"
    exit 0
fi

# Stop-hook payload (~50 lines) — we only need transcript_path.
payload="$(cat || true)"
if [[ -z "$payload" ]]; then
    log "skip: empty stdin payload"
    exit 0
fi

transcript_path="$(jq -r '.transcript_path // empty' <<<"$payload" 2>/dev/null)"
if [[ -z "$transcript_path" || ! -r "$transcript_path" ]]; then
    log "skip: transcript_path missing or unreadable ($transcript_path)"
    exit 0
fi

# Last line of the JSONL whose `type` is "assistant" and whose
# `.message.usage` exists. tac + awk avoids loading the whole file.
last_assistant_with_usage="$(
    tac "$transcript_path" 2>/dev/null \
        | awk '/"type":"assistant"/ && /"usage":/ { print; exit }'
)"
if [[ -z "$last_assistant_with_usage" ]]; then
    log "skip: no assistant turn with usage in $transcript_path"
    exit 0
fi

# Build the usage payload the backend expects (matches TaskforceUsagePayload).
# All token counts default to 0 if the field is missing.
body="$(
    jq -c '
        {
            model_id: (.message.model // "unknown"),
            input_tokens: (.message.usage.input_tokens // 0),
            output_tokens: (.message.usage.output_tokens // 0),
            cache_read_input_tokens: (.message.usage.cache_read_input_tokens // 0),
            cache_creation_input_tokens: (.message.usage.cache_creation_input_tokens // 0)
        }
    ' <<<"$last_assistant_with_usage" 2>/dev/null
)"
if [[ -z "$body" || "$body" == "null" ]]; then
    log "skip: could not extract usage from assistant turn"
    exit 0
fi

# Skip if every token count is 0 — most likely a no-op finalization
# turn (Stop fired without the model actually generating).
if [[ "$(jq -r '[.input_tokens, .output_tokens, .cache_read_input_tokens, .cache_creation_input_tokens] | add' <<<"$body")" == "0" ]]; then
    log "skip: zero-token turn"
    exit 0
fi

# Fire and forget. --max-time keeps a stalled backend from delaying
# the next Claude turn.
http_status="$(
    curl -sS \
        -o /dev/null \
        -w '%{http_code}' \
        --max-time 8 \
        -X POST \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        --data "$body" \
        "${BACKEND_URL}/api/v1/v2/metrics/usage?source=${SOURCE_LABEL}" 2>>"$LOG_FILE"
)" || true

log "POST /v2/metrics/usage → ${http_status} body=${body}"
