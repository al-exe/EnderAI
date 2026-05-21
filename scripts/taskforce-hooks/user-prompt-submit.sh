#!/usr/bin/env bash
# Claude Code UserPromptSubmit hook → Taskforce discovery.
#
# Wired into ~/.claude/settings.json as a UserPromptSubmit hook. Each
# time the user submits a prompt, this script reads the hook's stdin
# payload, asks the Taskforce backend for related prior work, and
# (when there are matches above threshold) prepends a short preamble
# to the prompt so the agent has the context.
#
# - Empty matches → silent (no stdout, no stderr).
# - Failures (no token, backend down, jq missing) → silent + logged.
# - stderr is used for the one-line banner Claude Code shows to the user.
# - stdout is the augmented prompt; Claude Code prepends it.
#
# Required:
#   ~/.enderai_mcp_token          (created by the Connect Agent flow)
# Optional:
#   ENDERAI_BACKEND_URL           (default https://enderai-backend.onrender.com)
#   TASKFORCE_PREAMBLE_BUDGET     (default 1500; tokens budget for the preamble)
#   TASKFORCE_HOOK_DEBUG          (set to 1 to mirror logs to stderr)
#
# Plan: ~/dev/docs/claude-mcp-brainstorm.md §3, §7.2
# Ticket: TF-176

set -uo pipefail

readonly LOG_FILE="${HOME}/.claude/taskforce-discover.log"
readonly TOKEN_FILE="${HOME}/.enderai_mcp_token"
readonly BACKEND_URL="${ENDERAI_BACKEND_URL:-https://enderai-backend.onrender.com}"
readonly TOKEN_BUDGET="${TASKFORCE_PREAMBLE_BUDGET:-1500}"

mkdir -p "$(dirname "$LOG_FILE")"

log() {
    local msg="[$(date -u +%FT%TZ)] $*"
    printf '%s\n' "$msg" >> "$LOG_FILE"
    if [[ "${TASKFORCE_HOOK_DEBUG:-0}" == "1" ]]; then
        printf '%s\n' "$msg" >&2
    fi
}

# Never block the user's session.
trap 'exit 0' EXIT

# Dependencies
if ! command -v jq >/dev/null 2>&1; then
    log "skip: jq missing"
    exit 0
fi
if ! command -v curl >/dev/null 2>&1; then
    log "skip: curl missing"
    exit 0
fi

if [[ ! -r "$TOKEN_FILE" ]]; then
    log "skip: no token at $TOKEN_FILE"
    exit 0
fi
token="$(tr -d '\r\n' < "$TOKEN_FILE")"
[[ -z "$token" ]] && { log "skip: token empty"; exit 0; }

# Claude Code hands us a JSON payload on stdin: {session_id, prompt, cwd,
# transcript_path}. Anything else we don't need today.
payload="$(cat || true)"
[[ -z "$payload" ]] && { log "skip: empty stdin"; exit 0; }

prompt="$(jq -r '.prompt // empty' <<<"$payload" 2>/dev/null)"
[[ -z "$prompt" ]] && { log "skip: no prompt in payload"; exit 0; }

session_id="$(jq -r '.session_id // empty' <<<"$payload" 2>/dev/null)"
cwd="$(jq -r '.cwd // empty' <<<"$payload" 2>/dev/null)"

# Best-effort git branch — keeps the scoring slightly sharper.
git_branch=""
if [[ -n "$cwd" && -d "$cwd/.git" ]] && command -v git >/dev/null 2>&1; then
    git_branch="$(cd "$cwd" && git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
fi

# Build the request body.
body="$(jq -cn \
    --arg prompt "$prompt" \
    --arg cwd "$cwd" \
    --arg session_id "$session_id" \
    --arg git_branch "$git_branch" \
    '{
        prompt: $prompt,
        cwd: (if $cwd == "" then null else $cwd end),
        session_id: (if $session_id == "" then null else $session_id end),
        git_branch: (if $git_branch == "" then null else $git_branch end)
    }')"

http_status="$(
    curl -sS \
        -o /tmp/.taskforce-discover-response.json \
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

response="$(cat /tmp/.taskforce-discover-response.json 2>/dev/null || true)"
[[ -z "$response" ]] && { log "skip: empty discover response"; exit 0; }

match_count="$(jq '.matches | length' <<<"$response" 2>/dev/null || echo 0)"
if [[ "$match_count" == "0" ]]; then
    log "no matches"
    exit 0
fi

# Format the preamble. Token budget is approximated at ~4 chars/token,
# so 1500 tokens ≈ 6000 chars. We cap per-match summary length and stop
# adding matches once the running total approaches the cap.
preamble_text="$(jq -r --argjson budget_chars "$((TOKEN_BUDGET * 4))" '
    .matches as $matches
    | reduce range(0; ($matches | length)) as $i ([0, ""];
        .[1] as $acc
        | .[0] as $used
        | $matches[$i] as $m
        | ($m.title + " — score " + ($m.score | tostring) + " — " + ($m.summary_markdown // "")) as $entry
        | ($used + ($entry | length)) as $next
        | if $next > $budget_chars then . else [$next, $acc + "\n[" + $m.title + "] (" + $m.confidence_band + ", " + ($m.score | tostring) + ")\n" + ($m.summary_markdown // "(no summary)") + (if $m.outcome then "\nOutcome: " + $m.outcome else "" end) + "\n"] end
      )
    | .[1]
' <<<"$response" 2>/dev/null)"

if [[ -z "$preamble_text" ]]; then
    log "skip: preamble empty after budget"
    exit 0
fi

# stdout → prepended to the agent's prompt as fresh context.
cat <<EOF
─── Related prior work (Taskforce) ──────────────────${preamble_text}
─── End related prior work ──────────────────────────

EOF

# stderr → one-line banner Claude Code surfaces to the user.
titles="$(jq -r '[.matches[].title] | join(", ")' <<<"$response" 2>/dev/null)"
printf '[Taskforce] %s related doc%s pulled · %s\n' \
    "$match_count" \
    "$( [[ "$match_count" == "1" ]] && echo "" || echo "s" )" \
    "$titles" >&2

log "ok: ${match_count} matches injected"
