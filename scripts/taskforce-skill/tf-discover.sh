#!/usr/bin/env bash
# /tf — discover step (TF-188).
#
# POST /v2/taskforce/session/start, then GET /v2/documents/{id} per match
# so the skill can render a 3-line anchor preview AND inject full anchor
# content into Claude's reasoning. Always exits 0 — emits a JSON envelope
# so the skill can degrade gracefully on errors.
#
# Flags:
#   --prompt <str>       (required)
#   --cwd <path>
#   --files <comma-list>
#   --git-branch <str>
#
# Output: a single-line JSON envelope on stdout. Schema:
#   { "ok": true,
#     "session_id": "<uuid>",
#     "matched_specialist": { ... } | null,
#     "matches": [ { document_id, title, score, confidence_band,
#                    match_reasons, href, anchor_preview, anchor_full } ],
#     "frontend_host": "https://www.taskforce.tools" }
# On failure:
#   { "ok": false, "reason": "no_token|backend_down|http_<code>|empty",
#     "detail": "..." }

set -uo pipefail

readonly LOG_FILE="${HOME}/.claude/taskforce-skill.log"
readonly TOKEN_FILE="${HOME}/.taskforce_mcp_token"
readonly LEGACY_TOKEN_FILE="${HOME}/.enderai_mcp_token"
readonly BACKEND_URL="${TASKFORCE_BACKEND_URL:-${ENDERAI_BACKEND_URL:-https://enderai-backend.onrender.com}}"
readonly FRONTEND_HOST="${TASKFORCE_FRONTEND_HOST:-https://www.taskforce.tools}"
# When TASKFORCE_DEMO=1, opt the session/start request into demo-flagged
# specialists + documents (TF-198 seed). Off by default so day-to-day
# /tf use sees only real, owner-scoped resources.
case "${TASKFORCE_DEMO:-0}" in
    1|true|TRUE|yes) DEMO_FLAG="true" ;;
    *)               DEMO_FLAG="false" ;;
esac
readonly DEMO_FLAG

mkdir -p "$(dirname "$LOG_FILE")"
log() { printf '[%s] tf-discover %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG_FILE"; }

emit_error() {
    local reason="$1" detail="${2:-}"
    log "error: ${reason} ${detail}"
    jq -cn --arg r "$reason" --arg d "$detail" '{ok:false, reason:$r, detail:$d}'
    exit 0
}

command -v jq >/dev/null 2>&1   || emit_error "jq_missing" "install jq"
command -v curl >/dev/null 2>&1 || emit_error "curl_missing" "install curl"

prompt="" cwd="" files_csv="" git_branch=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --prompt)      prompt="$2";       shift 2 ;;
        --cwd)         cwd="$2";          shift 2 ;;
        --files)       files_csv="$2";    shift 2 ;;
        --git-branch)  git_branch="$2";   shift 2 ;;
        *)             shift ;;
    esac
done

[[ -z "$prompt" ]] && emit_error "missing_prompt" "--prompt is required"
token_file="$TOKEN_FILE"
if [[ ! -r "$token_file" && -r "$LEGACY_TOKEN_FILE" ]]; then
    token_file="$LEGACY_TOKEN_FILE"
fi
[[ -r "$token_file" ]] || emit_error "no_token" "$TOKEN_FILE not readable"

token="$(tr -d '\r\n' < "$token_file")"
[[ -z "$token" ]] && emit_error "no_token" "token file empty"

# Build files JSON array from CSV. Caller (Claude, per SKILL.md Beat 1a) is
# responsible for populating --files via grep-based discovery on the user's
# prompt. Empty is valid — the backend will score on the prompt alone, which
# may return zero matches if the prompt isn't specific enough on its own.
files_json="$(jq -cn --arg csv "$files_csv" '
    if $csv == "" then []
    else ($csv | split(",") | map(select(. != "")))
    end
')"

body="$(jq -cn \
    --arg prompt "$prompt" \
    --arg cwd "$cwd" \
    --arg git_branch "$git_branch" \
    --argjson files "$files_json" \
    --argjson demo "$DEMO_FLAG" '
    {
        prompt: $prompt,
        cwd: (if $cwd == "" then null else $cwd end),
        git_branch: (if $git_branch == "" then null else $git_branch end),
        files: $files,
        k: 3,
        min_score: 0.3,
        demo: $demo
    }')"

tmp_resp="$(mktemp)"
trap 'rm -f "$tmp_resp"' EXIT

http_status="$(
    curl -sS -o "$tmp_resp" -w '%{http_code}' \
        --max-time 8 \
        -X POST \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        --data "$body" \
        "${BACKEND_URL}/api/v1/v2/taskforce/session/start" 2>>"$LOG_FILE"
)" || emit_error "backend_down" "curl failed"

if [[ "$http_status" != "201" && "$http_status" != "200" ]]; then
    emit_error "http_${http_status}" "$(head -c 400 "$tmp_resp" 2>/dev/null || true)"
fi

response="$(cat "$tmp_resp")"
[[ -z "$response" ]] && emit_error "empty" "empty body from session/start"

session_id="$(jq -r '.session_id // empty' <<<"$response")"
[[ -z "$session_id" ]] && emit_error "empty" "no session_id in response"

# For each match: pull the document + slice the matched anchor.
# Renders a 3-line preview (first 3 non-blank lines, prefixed with >) and
# the FULL anchor markdown (so the skill can feed it to Claude as context).
match_count="$(jq '.matches | length' <<<"$response")"
enriched_matches="[]"

for ((i=0; i<match_count; i++)); do
    doc_id="$(jq -r ".matches[$i].document_id" <<<"$response")"
    anchor_id="$(jq -r ".matches[$i].matched_anchor_id // empty" <<<"$response")"

    doc_resp="$(mktemp)"
    doc_http="$(
        curl -sS -o "$doc_resp" -w '%{http_code}' \
            --max-time 6 \
            -H "Authorization: Bearer ${token}" \
            "${BACKEND_URL}/api/v1/v2/documents/${doc_id}?demo=${DEMO_FLAG}" 2>>"$LOG_FILE"
    )" || doc_http="000"

    if [[ "$doc_http" != "200" ]]; then
        log "doc fetch ${doc_id} → ${doc_http}, falling back to summary"
        anchor_full=""
        anchor_preview=""
    else
        anchor_full="$(jq -r --arg a "$anchor_id" '
            if $a == "" then ""
            else (.details_markdown_sections // []
                  | map(select(.anchor_id == $a))
                  | first
                  | .markdown // "")
            end
        ' "$doc_resp")"
        anchor_preview="$(printf '%s\n' "$anchor_full" \
            | awk 'NF { print "> " $0; n++; if (n >= 3) exit }')"
    fi
    rm -f "$doc_resp"

    match_json="$(jq -c ".matches[$i]" <<<"$response")"
    enriched_matches="$(jq -cn \
        --argjson prior "$enriched_matches" \
        --argjson m "$match_json" \
        --arg href "${FRONTEND_HOST}/v2/library/${doc_id}$([[ -n "$anchor_id" ]] && echo "#${anchor_id}")" \
        --arg preview "$anchor_preview" \
        --arg full "$anchor_full" '
        $prior + [{
            document_id: $m.document_id,
            title: $m.title,
            score: $m.score,
            confidence_band: $m.confidence_band,
            matched_anchor_id: $m.matched_anchor_id,
            match_reasons: $m.match_reasons,
            summary_markdown: $m.summary_markdown,
            href: $href,
            anchor_preview: $preview,
            anchor_full: $full
        }]
    ')"
done

# Rewrite matched_specialist.href + each linked_documents[].href to use
# FRONTEND_HOST so the skill can render absolute links.
matched_specialist="$(jq -c --arg host "$FRONTEND_HOST" '
    if .matched_specialist == null then null
    else .matched_specialist
         | .href = ($host + .href)
         | .linked_documents |= map(.href = ($host + .href))
    end
' <<<"$response")"

jq -cn \
    --arg session_id "$session_id" \
    --argjson matched_specialist "$matched_specialist" \
    --argjson matches "$enriched_matches" \
    --arg frontend_host "$FRONTEND_HOST" \
    '{
        ok: true,
        session_id: $session_id,
        matched_specialist: $matched_specialist,
        matches: $matches,
        frontend_host: $frontend_host
    }'

log "ok: ${match_count} matches, session_id=${session_id}"
