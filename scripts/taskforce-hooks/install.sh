#!/usr/bin/env bash
# Idempotent installer for the Taskforce Claude Code hooks (TF-176).
#
# Drops the hook scripts into ~/.claude/hooks/ and merges the matching
# entries into ~/.claude/settings.json. Re-running it leaves both in
# a consistent state.
#
# Usage:
#   curl -fsSL https://enderai-backend.onrender.com/api/v1/v2/taskforce/install.sh | bash
# or
#   bash scripts/taskforce-hooks/install.sh

set -euo pipefail

HOOK_DIR="${HOME}/.claude/hooks"
SETTINGS_FILE="${HOME}/.claude/settings.json"
USER_PROMPT_HOOK="${HOOK_DIR}/taskforce-user-prompt-submit.sh"
STOP_HOOK="${HOOK_DIR}/taskforce-stop.sh"
POST_TOOL_HOOK="${HOOK_DIR}/taskforce-post-tool-use.sh"
SESSION_END_HOOK="${HOOK_DIR}/taskforce-session-end.sh"
RECORD_USAGE_HOOK="${HOOK_DIR}/taskforce-record-usage.sh"

REPO_RAW_BASE="${TASKFORCE_HOOK_REPO_RAW:-https://raw.githubusercontent.com/al-exe/EnderAI/main/scripts/taskforce-hooks}"

mkdir -p "$HOOK_DIR" "${HOME}/.taskforce"

install_hook() {
    local source_name="$1" target="$2"
    echo "→ Installing ${source_name} → ${target}"
    if [[ -f "${PWD}/scripts/taskforce-hooks/${source_name}" ]]; then
        install -m 0755 "${PWD}/scripts/taskforce-hooks/${source_name}" "$target"
    else
        curl -fsSL "${REPO_RAW_BASE}/${source_name}" -o "$target"
        chmod 0755 "$target"
    fi
}

install_hook "user-prompt-submit.sh" "$USER_PROMPT_HOOK"
install_hook "stop.sh"                "$STOP_HOOK"
install_hook "post-tool-use.sh"       "$POST_TOOL_HOOK"
install_hook "session-end.sh"         "$SESSION_END_HOOK"
install_hook "record-usage.sh"        "$RECORD_USAGE_HOOK"

# Merge the hooks block into ~/.claude/settings.json. Uses jq so any
# existing entries (e.g. the Stop hook from the EnderAI Connect Agent
# flow) survive.
mkdir -p "$(dirname "$SETTINGS_FILE")"
if [[ ! -f "$SETTINGS_FILE" ]]; then
    echo '{}' > "$SETTINGS_FILE"
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "WARNING: jq is required to merge settings.json safely."
    echo "Install jq, then re-run this script."
    exit 1
fi

merge_hook() {
    local hook_name="$1" command="$2" timeout="$3"
    local tmp_file
    tmp_file="$(mktemp)"
    jq --arg hook_name "$hook_name" --arg cmd "$command" --argjson timeout "$timeout" '
        .hooks = (.hooks // {})
        | .hooks[$hook_name] = (
            .hooks[$hook_name]
            // [{matcher: "*", hooks: []}]
        )
        | .hooks[$hook_name] |= (
            # `.` is the array of {matcher, hooks} entries at this point.
            # Dedup: if any entry already lists our command, leave the
            # whole array alone. Otherwise, append to the wildcard matcher.
            if (any(.[]; .hooks[]?.command == $cmd)) then
                .
            elif (any(.[]; .matcher == "*")) then
                map(
                    if .matcher == "*" then
                        .hooks = ((.hooks // []) + [
                            {type: "command", command: $cmd, timeout: $timeout}
                        ])
                    else . end
                )
            else
                . + [{
                    matcher: "*",
                    hooks: [
                        {type: "command", command: $cmd, timeout: $timeout}
                    ]
                }]
            end
        )
    ' "$SETTINGS_FILE" > "$tmp_file"
    mv "$tmp_file" "$SETTINGS_FILE"
}

merge_hook UserPromptSubmit "$USER_PROMPT_HOOK"  5
merge_hook Stop             "$STOP_HOOK"        30
merge_hook PostToolUse      "$POST_TOOL_HOOK"   15
merge_hook SessionEnd       "$SESSION_END_HOOK" 15
merge_hook Stop             "$RECORD_USAGE_HOOK" 10

echo "✓ Hook installed and ~/.claude/settings.json updated."
echo ""
echo "Verify with:"
echo "  jq '.hooks.UserPromptSubmit' ~/.claude/settings.json"
echo ""
echo "Restart your Claude Code session for the hook to take effect."
echo "Logs land at: ~/.claude/taskforce-discover.log"
