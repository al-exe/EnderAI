#!/usr/bin/env bash
# Codex UserPromptSubmit hook -> Taskforce discovery.

set -uo pipefail

readonly LOG_FILE="${HOME}/.codex/taskforce.log"
readonly TOKEN_FILE="${HOME}/.taskforce_mcp_token"
readonly LEGACY_TOKEN_FILE="${HOME}/.enderai_mcp_token"
readonly STATE_DIR="${HOME}/.taskforce"
readonly BACKEND_URL="${ENDERAI_BACKEND_URL:-https://enderai-backend.onrender.com}"
readonly TOKEN_BUDGET="${TASKFORCE_PREAMBLE_BUDGET:-1500}"
readonly DISCOVER_MAX="${TASKFORCE_DISCOVER_MAX:-2}"
readonly DISCOVER_SUMMARY_CHARS="${TASKFORCE_DISCOVER_SUMMARY_CHARS:-140}"
readonly FLEET_MAX="${TASKFORCE_FLEET_MAX:-3}"
readonly FLEET_SUMMARY_CHARS="${TASKFORCE_FLEET_SUMMARY_CHARS:-120}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/git-context.sh"

mkdir -p "$(dirname "$LOG_FILE")" "$STATE_DIR"

log() {
    printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG_FILE"
}

response_file=""
fleet_response_file=""
cleanup() {
    [[ -n "$response_file" ]] && rm -f "$response_file"
    [[ -n "$fleet_response_file" ]] && rm -f "$fleet_response_file"
}
trap 'cleanup; exit 0' EXIT

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

prompt="$(jq -r '.prompt // empty' <<<"$payload" 2>/dev/null)"
session_id="$(jq -r '.session_id // empty' <<<"$payload" 2>/dev/null)"
cwd="$(taskforce_resolve_cwd_from_payload "$payload")"
[[ -z "$prompt" ]] && { log "skip: no prompt"; exit 0; }
[[ -z "$session_id" ]] && { log "skip: no session_id"; exit 0; }

git_branch="$(taskforce_resolve_git_branch_from_payload "$payload" 2>/dev/null || true)"

body="$(jq -cn \
    --arg prompt "$prompt" \
    --arg cwd "$cwd" \
    --arg session_id "$session_id" \
    --arg git_branch "$git_branch" \
    '{
        prompt: $prompt,
        cwd: (if $cwd == "" then null else $cwd end),
        session_id: $session_id,
        git_branch: (if $git_branch == "" then null else $git_branch end),
        client: "codex",
        min_score: 0.2
    }')"

response_file="$(mktemp)"
http_status="$(
    curl -sS \
        -o "$response_file" \
        -w '%{http_code}' \
        --max-time 4 \
        -X POST \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        --data "$body" \
        "${BACKEND_URL}/api/v1/v2/taskforce/discover" 2>>"$LOG_FILE"
)" || { log "skip: curl failed"; exit 0; }

if [[ "$http_status" != "200" ]]; then
    log "skip: discover returned ${http_status}"
    exit 0
fi

session_active_doc="$(jq -r '.session_active_document_id // empty' "$response_file" 2>/dev/null || true)"
if [[ -n "$session_active_doc" ]]; then
    printf '%s' "$session_active_doc" > "${STATE_DIR}/${session_id}.active"
fi

match_count="$(jq '.matches | length' "$response_file" 2>/dev/null || echo 0)"
discover_block=""
if [[ "$match_count" != "0" ]]; then
    preamble_text="$(jq -r \
        --argjson max_items "$DISCOVER_MAX" \
        --argjson summary_chars "$DISCOVER_SUMMARY_CHARS" \
        --argjson budget_chars "$((TOKEN_BUDGET * 4))" '
        .matches[:$max_items]
        | map(
            ((.title // "Untitled") | gsub("\n"; " ") | gsub("\\s+"; " ")) as $title
            | ((.summary_markdown // .outcome // "") | gsub("\n"; " ") | gsub("\\s+"; " ")) as $summary
            | ("- " + $title + (if $summary != "" then ": " + ($summary[:$summary_chars]) else "" end))
          )
        | join("\n")
        | .[:$budget_chars]
    ' "$response_file" 2>/dev/null)"

    if [[ -n "$preamble_text" ]]; then
        discover_block="Taskforce prior context (${match_count} match(es)):
${preamble_text}
Use only if relevant."
    fi
fi

fleet_block=""
if [[ "${TASKFORCE_FLEET_INJECT:-1}" != "0" ]]; then
    fleet_response_file="$(mktemp)"
    fleet_status="$(
        curl -sS \
            -o "$fleet_response_file" \
            -w '%{http_code}' \
            --max-time 4 \
            -H "Authorization: Bearer ${token}" \
            "${BACKEND_URL}/api/v1/v2/taskforce/fleet" 2>>"$LOG_FILE"
    )" || fleet_status=""

    if [[ "$fleet_status" == "200" ]]; then
        sib_filter='[ .fleet_sessions[]? | select(.is_history | not) | .agents[]?
            | select(.session_id != $self)
            | select((.minutes_ago // 99999) <= $maxmin)
            | select(((.status // "") == "running") or ((.status // "") == "waiting") or ((.status // "") == "active")) ]'
        sib_text="$(jq -r \
            --arg self "$session_id" \
            --argjson maxmin "${TASKFORCE_FLEET_MAX_MIN:-480}" \
            --argjson max_items "$FLEET_MAX" \
            --argjson summary_chars "$FLEET_SUMMARY_CHARS" "
            ${sib_filter}
            | map(
                ((.summary_markdown // \"\") | gsub(\"\n\";\" \") | gsub(\"\\\\s+\"; \" \")) as \$sum
                | ((.title // \"\") | gsub(\"\n\";\" \") | gsub(\"\\\\s+\"; \" \")) as \$title
                | ((.display_name // \"untitled\") | gsub(\"\n\";\" \") | gsub(\"\\\\s+\"; \" \")) as \$name
                | (if \$sum != \"\" then (\$sum | .[0:\$summary_chars])
                   elif \$title != \"\" then \$title
                   else (\$name | .[0:90]) + \" (just started)\" end) as \$desc
                | \"- \" + (.repo // \"?\") + (if .branch then \"@\"+.branch else \"\" end)
                  + \": \" + (.status // \"?\") + \" \" + ((.minutes_ago // 0)|tostring) + \"m\"
                  + (if \$desc != \"\" then \" - \" + \$desc else \"\" end) )
            | .[0:\$max_items] | join(\"\n\")
        " "$fleet_response_file" 2>/dev/null)"

        if [[ -n "$sib_text" ]]; then
            sib_count="$(jq -r --arg self "$session_id" --argjson maxmin "${TASKFORCE_FLEET_MAX_MIN:-480}" "${sib_filter} | length" "$fleet_response_file" 2>/dev/null || echo 0)"
            fleet_block="Taskforce live siblings (${sib_count}):
${sib_text}
Use only for coordination if relevant."
            log "fleet: ${sib_count} live siblings injected"
        else
            log "fleet: no live siblings"
        fi
    else
        log "fleet: status ${fleet_status:-none}"
    fi
fi

if [[ -n "$discover_block" || -n "$fleet_block" ]]; then
    [[ -n "$discover_block" ]] && printf '%s\n' "$discover_block"
    [[ -n "$fleet_block" ]] && printf '%s\n' "$fleet_block"
    log "ok: discover=${match_count} fleet=$([[ -n "$fleet_block" ]] && echo yes || echo no)"
else
    log "no context to inject"
fi
