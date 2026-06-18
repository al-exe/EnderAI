#!/usr/bin/env bash
# Codex UserPromptSubmit hook -> Taskforce discovery.

set -uo pipefail

readonly LOG_FILE="${HOME}/.codex/taskforce.log"
readonly TOKEN_FILE="${HOME}/.taskforce_mcp_token"
readonly LEGACY_TOKEN_FILE="${HOME}/.enderai_mcp_token"
readonly STATE_DIR="${HOME}/.taskforce"
readonly BACKEND_URL="${ENDERAI_BACKEND_URL:-https://enderai-backend.onrender.com}"
readonly TOKEN_BUDGET="${TASKFORCE_PREAMBLE_BUDGET:-1500}"
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
    preamble_text="$(jq -r --argjson budget_chars "$((TOKEN_BUDGET * 4))" '
        .matches as $matches
        | reduce range(0; ($matches | length)) as $i ([0, ""];
            .[1] as $acc
            | .[0] as $used
            | $matches[$i] as $m
            | ($m.title + " - score " + ($m.score | tostring) + " - " + ($m.summary_markdown // "")) as $entry
            | ($used + ($entry | length)) as $next
            | if $next > $budget_chars then .
              else [$next, $acc + "\n[" + $m.title + "] (" + $m.confidence_band + ", " + ($m.score | tostring) + ")\n" + ($m.summary_markdown // "(no summary)") + (if $m.outcome then "\nOutcome: " + $m.outcome else "" end) + "\n"]
              end
          )
        | .[1]
    ' "$response_file" 2>/dev/null)"

    if [[ -n "$preamble_text" ]]; then
        discover_block="Related prior work from Taskforce:
${preamble_text}
Use this as prior context when it is relevant to the user's request."
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
        sib_text="$(jq -r --arg self "$session_id" --argjson maxmin "${TASKFORCE_FLEET_MAX_MIN:-480}" "
            ${sib_filter}
            | map(
                ((.summary_markdown // \"\") | gsub(\"\n\";\" \")) as \$sum
                | ((.title // \"\") | gsub(\"\n\";\" \")) as \$title
                | ((.display_name // \"untitled\") | gsub(\"\n\";\" \")) as \$name
                | (if \$sum != \"\" then (\$sum | .[0:240])
                   elif \$title != \"\" then \$title
                   else (\$name | .[0:90]) + \"  (just started - no work summary yet)\" end) as \$desc
                | \"- \" + (.repo // \"?\") + (if .branch then \"@\"+.branch else \"\" end)
                  + \" (\" + (.status // \"?\") + \", \" + ((.minutes_ago // 0)|tostring) + \"m ago)\"
                  + \"\n    \" + \$desc )
            | .[0:6] | join(\"\n\")
        " "$fleet_response_file" 2>/dev/null)"

        if [[ -n "$sib_text" ]]; then
            sib_count="$(jq -r --arg self "$session_id" --argjson maxmin "${TASKFORCE_FLEET_MAX_MIN:-480}" "${sib_filter} | length" "$fleet_response_file" 2>/dev/null || echo 0)"
            fleet_block="Live sibling agents from Taskforce:
${sib_text}
Use this as current coordination context when it is relevant to the user's request."
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
