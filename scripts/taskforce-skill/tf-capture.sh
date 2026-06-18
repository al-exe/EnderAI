#!/usr/bin/env bash
# /tf — capture step ([DEMO WORK]).
#
# Write what this session just figured out into the Library *now*, instead of
# waiting for the passive Stop-hook summarizer. POSTs /v2/taskforce/observe
# with structured fields (decisions / summary_points / outcome / files), so the
# backend builds the document patch directly — no haiku summarizer, no cost,
# deterministic content the demo can show landing on camera.
#
# The doc it writes/patches is the same one your fleet-mates' tf-fleet.sh will
# surface, so "capture here → reuse there" closes the loop.
#
# Repeatable flags collect into arrays:
#   --session-id <id>           (required)
#   --decision <str>            a decision/finding worth reusing (repeat)
#   --summary-point <str>       a one-line summary bullet (repeat)
#   --files <comma-list>        files touched this session
#   --outcome <shipped|blocked|paused|interrupted>
#   --specialist-slug <str>     the routed profile slug, if any
#   --active-document-id <id>   patch a specific doc instead of the active one
#   --visibility <private|organization>   default private
#   --cwd <path>   --branch <str>   --prompt <str>   --kind <checkpoint|final>
#
# Output JSON (always exit 0; check .ok):
#   { "ok": true, "action": "created|updated|skipped", "document_id": "<uuid>|",
#     "href": "<frontend>/v2/library/<id>", "patched_fields": [...],
#     "structured_path": true }
#   { "ok": false, "reason": "...", "detail": "..." }

set -uo pipefail

readonly LOG_FILE="${HOME}/.claude/taskforce-skill.log"
readonly TOKEN_FILE="${HOME}/.taskforce_mcp_token"
readonly LEGACY_TOKEN_FILE="${HOME}/.enderai_mcp_token"
readonly BACKEND_URL="${TASKFORCE_BACKEND_URL:-${ENDERAI_BACKEND_URL:-https://enderai-backend.onrender.com}}"
readonly FRONTEND_HOST="${TASKFORCE_FRONTEND_HOST:-https://www.taskforce.tools}"

case "${TASKFORCE_DEMO:-0}" in
    1|true|TRUE|yes) DEMO_FLAG="true" ;;
    *)               DEMO_FLAG="false" ;;
esac
readonly DEMO_FLAG

detect_client() {
    if [[ -n "${TASKFORCE_CLIENT:-}" ]]; then printf '%s\n' "$TASKFORCE_CLIENT"; return; fi
    case "${BASH_SOURCE[0]:-$0}" in
        */.codex/*)  printf 'codex\n' ;;
        */.cursor/*) printf 'cursor\n' ;;
        */.claude/*) printf 'claude-code\n' ;;
        *)           printf '\n' ;;
    esac
}
readonly CLIENT_VALUE="$(detect_client)"

mkdir -p "$(dirname "$LOG_FILE")"
log() { printf '[%s] tf-capture %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG_FILE"; }
emit_error() {
    local reason="$1" detail="${2:-}"
    log "error: ${reason} ${detail}"
    jq -cn --arg r "$reason" --arg d "$detail" '{ok:false, reason:$r, detail:$d}'
    exit 0
}

command -v jq >/dev/null 2>&1   || emit_error "jq_missing" "install jq"
command -v curl >/dev/null 2>&1 || emit_error "curl_missing" "install curl"

session_id="" outcome="" specialist_slug="" active_doc_id="" visibility="private"
cwd="" branch="" prompt="" kind="checkpoint" files_csv=""
decisions_json="[]" summary_json="[]"
append() { jq -cn --argjson p "$1" --arg v "$2" '$p + [$v]'; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --session-id)         session_id="$2";       shift 2 ;;
        --decision)           decisions_json="$(append "$decisions_json" "$2")"; shift 2 ;;
        --summary-point)      summary_json="$(append "$summary_json" "$2")";     shift 2 ;;
        --files)              files_csv="$2";        shift 2 ;;
        --outcome)            outcome="$2";          shift 2 ;;
        --specialist-slug)    specialist_slug="$2";  shift 2 ;;
        --active-document-id) active_doc_id="$2";    shift 2 ;;
        --visibility)         visibility="$2";       shift 2 ;;
        --cwd)                cwd="$2";              shift 2 ;;
        --branch)             branch="$2";           shift 2 ;;
        --prompt)             prompt="$2";           shift 2 ;;
        --kind)               kind="$2";             shift 2 ;;
        *)                    shift ;;
    esac
done

[[ -z "$session_id" ]] && emit_error "missing_session_id" "--session-id is required"
if [[ "$decisions_json" == "[]" && "$summary_json" == "[]" ]]; then
    emit_error "nothing_to_capture" "pass at least one --decision or --summary-point"
fi

token_file="$TOKEN_FILE"
if [[ ! -r "$token_file" && -r "$LEGACY_TOKEN_FILE" ]]; then
    token_file="$LEGACY_TOKEN_FILE"
fi
[[ -r "$token_file" ]] || emit_error "no_token" "$TOKEN_FILE not readable"
token="$(tr -d '\r\n' < "$token_file")"
[[ -z "$token" ]] && emit_error "no_token" "token file empty"

files_json="$(jq -cn --arg csv "$files_csv" '
    if $csv == "" then [] else ($csv | split(",") | map(select(. != ""))) end')"

body="$(jq -cn \
    --arg kind "$kind" \
    --arg prompt "$prompt" \
    --arg session_id "$session_id" \
    --arg client "$CLIENT_VALUE" \
    --arg cwd "$cwd" \
    --arg branch "$branch" \
    --arg visibility "$visibility" \
    --arg outcome "$outcome" \
    --arg specialist_slug "$specialist_slug" \
    --arg active_doc_id "$active_doc_id" \
    --argjson decisions "$decisions_json" \
    --argjson summary_points "$summary_json" \
    --argjson files "$files_json" '
    {
        kind: $kind,
        prompt: $prompt,
        session_id: $session_id,
        client: (if $client == "" then null else $client end),
        cwd: (if $cwd == "" then null else $cwd end),
        branch: (if $branch == "" then null else $branch end),
        visibility: $visibility,
        decisions: $decisions,
        summary_points: $summary_points,
        files_touched: $files,
        transcript: []
    }
    + (if $outcome == "" then {} else {outcome: $outcome} end)
    + (if $specialist_slug == "" then {} else {specialist_slug: $specialist_slug} end)
    + (if $active_doc_id == "" then {} else {active_document_id: $active_doc_id} end)
')"

tmp_resp="$(mktemp)"; trap 'rm -f "$tmp_resp"' EXIT

http_status="$(
    curl -sS -o "$tmp_resp" -w '%{http_code}' \
        --max-time 12 \
        -X POST \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        --data "$body" \
        "${BACKEND_URL}/api/v1/v2/taskforce/observe?demo=${DEMO_FLAG}" 2>>"$LOG_FILE"
)" || emit_error "backend_down" "curl failed"

if [[ "$http_status" != "202" && "$http_status" != "200" ]]; then
    emit_error "http_${http_status}" "$(head -c 400 "$tmp_resp" 2>/dev/null || true)"
fi
[[ -s "$tmp_resp" ]] || emit_error "empty" "empty body from /observe"

jq -c \
    --arg host "$FRONTEND_HOST" '
    (.document_id // "") as $id
    | {
        ok: true,
        action: (.action // "skipped"),
        document_id: $id,
        href: (if $id == "" then "" else ($host + "/v2/library/" + $id) end),
        patched_fields: (.patched_fields // []),
        structured_path: (.structured_path // false),
        reason: (.reason // "")
    }' "$tmp_resp"

log "ok: session_id=${session_id} action=$(jq -r '.action // "?"' "$tmp_resp")"
