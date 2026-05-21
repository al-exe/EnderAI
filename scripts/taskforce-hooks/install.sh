#!/usr/bin/env bash
# Idempotent installer for the Taskforce Claude Code hooks (TF-176).
#
# Drops the hook scripts into ~/.claude/hooks/ and merges the matching
# entries into ~/.claude/settings.json. Re-running it leaves both in
# a consistent state.
#
# Usage:
#   curl -fsSL <raw url> | bash
# or
#   bash scripts/taskforce-hooks/install.sh

set -euo pipefail

HOOK_DIR="${HOME}/.claude/hooks"
SETTINGS_FILE="${HOME}/.claude/settings.json"
USER_PROMPT_HOOK="${HOOK_DIR}/taskforce-user-prompt-submit.sh"

REPO_RAW_BASE="${TASKFORCE_HOOK_REPO_RAW:-https://raw.githubusercontent.com/al-exe/EnderAI/main/scripts/taskforce-hooks}"

mkdir -p "$HOOK_DIR"

echo "→ Installing UserPromptSubmit hook to ${USER_PROMPT_HOOK}"
if [[ -f "${PWD}/scripts/taskforce-hooks/user-prompt-submit.sh" ]]; then
    install -m 0755 "${PWD}/scripts/taskforce-hooks/user-prompt-submit.sh" "$USER_PROMPT_HOOK"
else
    curl -fsSL "${REPO_RAW_BASE}/user-prompt-submit.sh" -o "$USER_PROMPT_HOOK"
    chmod 0755 "$USER_PROMPT_HOOK"
fi

# Merge the hooks block into ~/.claude/settings.json. Uses jq so any
# existing entries (e.g. the Stop hook from the EnderAI Connect Agent
# flow) survive.
mkdir -p "$(dirname "$SETTINGS_FILE")"
if [[ ! -f "$SETTINGS_FILE" ]]; then
    echo '{}' > "$SETTINGS_FILE"
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "WARNING: jq is required to merge settings.json safely."
    echo "Install jq, or merge the following into ~/.claude/settings.json:"
    cat <<JSON
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "${USER_PROMPT_HOOK}",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
JSON
    exit 0
fi

tmp_file="$(mktemp)"
jq --arg cmd "$USER_PROMPT_HOOK" '
    .hooks = (.hooks // {})
    | .hooks.UserPromptSubmit = (
        .hooks.UserPromptSubmit
        // [{matcher: "*", hooks: []}]
    )
    | .hooks.UserPromptSubmit |= (
        if any(.hooks[]?; .command == $cmd) then
            .
        else
            map(
                if .matcher == "*" then
                    .hooks = ((.hooks // []) + [
                        {type: "command", command: $cmd, timeout: 5}
                    ])
                else . end
            )
        end
    )
' "$SETTINGS_FILE" > "$tmp_file"

mv "$tmp_file" "$SETTINGS_FILE"

echo "✓ Hook installed and ~/.claude/settings.json updated."
echo ""
echo "Verify with:"
echo "  jq '.hooks.UserPromptSubmit' ~/.claude/settings.json"
echo ""
echo "Restart your Claude Code session for the hook to take effect."
echo "Logs land at: ~/.claude/taskforce-discover.log"
