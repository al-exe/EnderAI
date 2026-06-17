#!/usr/bin/env bash
# Claude Code UserPromptSubmit hook → Taskforce discovery.
#
# Wired into ~/.claude/settings.json as a UserPromptSubmit hook. Each
# time the user submits a prompt, this script reads the hook's stdin
# payload, asks the Taskforce backend for related prior work, and
# (when there are matches above threshold) prepends a short preamble
# to the prompt so the agent has the context. It also pulls the live
# fleet roster and injects a compact "what the other agents are doing
# now" block so each agent has its siblings' shared context.
#
# - Empty matches → silent (no stdout, no stderr).
# - Failures (no token, backend down, jq missing) → silent + logged.
# - stderr is used for the one-line banner Claude Code shows to the user.
# - stdout is the augmented prompt; Claude Code prepends it.
#
# Required:
#   ~/.taskforce_mcp_token        (created by the Connect Agent flow)
# Optional:
#   ENDERAI_BACKEND_URL           (default https://enderai-backend.onrender.com)
#   TASKFORCE_PREAMBLE_BUDGET     (default 1500; tokens budget for the preamble)
#   TASKFORCE_HOOK_DEBUG          (set to 1 to mirror logs to stderr)
#   TASKFORCE_FLEET_INJECT        (set to 0 to disable the live-sibling block)
#   TASKFORCE_FLEET_MAX_MIN       (liveness window in minutes; default 480 / 8h)
#
# Plan: ~/dev/docs/claude-mcp-brainstorm.md §3, §7.2
# Ticket: TF-176

set -uo pipefail

readonly LOG_FILE="${HOME}/.claude/taskforce-discover.log"
readonly TOKEN_FILE="${HOME}/.taskforce_mcp_token"
readonly LEGACY_TOKEN_FILE="${HOME}/.enderai_mcp_token"
readonly STATE_DIR="${HOME}/.taskforce"
readonly BACKEND_URL="${ENDERAI_BACKEND_URL:-https://enderai-backend.onrender.com}"
readonly TOKEN_BUDGET="${TASKFORCE_PREAMBLE_BUDGET:-1500}"

mkdir -p "$(dirname "$LOG_FILE")" "$STATE_DIR"

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
        git_branch: (if $git_branch == "" then null else $git_branch end),
        min_score: 0.2
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

if [[ -n "$session_id" ]]; then
    session_active_doc="$(jq -r '.session_active_document_id // empty' <<<"$response" 2>/dev/null || true)"
    if [[ -n "$session_active_doc" ]]; then
        printf '%s' "$session_active_doc" > "${STATE_DIR}/${session_id}.active"
    fi
fi

# ── Part 1: related prior work (topical /discover matches) ──────────
# Buffered, not printed yet — we may also have sibling-fleet context to
# emit below, and we want a single combined preamble either way.
discover_block=""
match_count="$(jq '.matches | length' <<<"$response" 2>/dev/null || echo 0)"
if [[ "$match_count" != "0" ]]; then
    # Token budget ≈ 4 chars/token; stop adding matches near the cap.
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
    if [[ -n "$preamble_text" ]]; then
        discover_block="─── Related prior work (Taskforce) ──────────────────${preamble_text}
─── End related prior work ──────────────────────────"
        titles="$(jq -r '[.matches[].title] | join(", ")' <<<"$response" 2>/dev/null)"
        printf '[Taskforce] %s related doc%s pulled · %s\n' \
            "$match_count" \
            "$( [[ "$match_count" == "1" ]] && echo "" || echo "s" )" \
            "$titles" >&2
    fi
fi

# ── Part 2: live sibling agents (fleet roster) ──────────────────────
# Auto-pull what the other agents in the fleet are doing right now and
# inject a compact status block into this agent's context — no need for
# the user to ask. Disable with TASKFORCE_FLEET_INJECT=0. Tune the
# liveness window with TASKFORCE_FLEET_MAX_MIN (default 480 min / 8h, to
# match the backend's 8h active-session timeout).
fleet_block=""
if [[ "${TASKFORCE_FLEET_INJECT:-1}" != "0" ]]; then
    fleet_status="$(
        curl -sS \
            -o /tmp/.taskforce-fleet-response.json \
            -w '%{http_code}' \
            --max-time 4 \
            -H "Authorization: Bearer ${token}" \
            "${BACKEND_URL}/api/v1/v2/taskforce/fleet" 2>>"$LOG_FILE"
    )" || fleet_status=""

    if [[ "$fleet_status" == "200" ]]; then
        fleet_json="$(cat /tmp/.taskforce-fleet-response.json 2>/dev/null || true)"
        # Live siblings = non-history sessions, status running/waiting/active,
        # seen within the window, excluding this very session. Cap at 6.
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
                   else (\$name | .[0:90]) + \"  (just started — no work summary yet)\" end) as \$desc
                | \"• \" + (.repo // \"?\") + (if .branch then \"@\"+.branch else \"\" end)
                  + \" (\" + (.status // \"?\") + \", \" + ((.minutes_ago // 0)|tostring) + \"m ago)\"
                  + \"\n    \" + \$desc )
            | .[0:6] | join(\"\n\")
        " <<<"$fleet_json" 2>/dev/null)"

        if [[ -n "$sib_text" ]]; then
            sib_count="$(jq -r --arg self "$session_id" --argjson maxmin "${TASKFORCE_FLEET_MAX_MIN:-480}" "${sib_filter} | length" <<<"$fleet_json" 2>/dev/null || echo 0)"
            fleet_block="─── Live sibling agents (Taskforce fleet) ───────────
${sib_text}
─── End sibling agents ───────────────────────────────"
            fleet_banner="$(printf '[Taskforce] %s live sibling agent%s in fleet' \
                "$sib_count" \
                "$( [[ "$sib_count" == "1" ]] && echo "" || echo "s" )")"
            printf '%s\n' "$fleet_banner" >&2
            # Mirror the banner into the log so `tail -f` shows it too.
            log "$fleet_banner"
        else
            log "fleet: no live siblings"
        fi
    else
        log "fleet: status ${fleet_status:-none}"
    fi
fi

# ── Emit combined preamble (whichever blocks exist) ─────────────────
if [[ -n "$discover_block" || -n "$fleet_block" ]]; then
    [[ -n "$discover_block" ]] && printf '%s\n' "$discover_block"
    [[ -n "$fleet_block" ]] && printf '%s\n' "$fleet_block"
    printf '\n'
fi

log "ok: discover=${match_count} fleet=$([[ -n "$fleet_block" ]] && echo yes || echo no)"
