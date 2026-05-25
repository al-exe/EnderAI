#!/usr/bin/env bash
# Idempotent installer for the /tf Taskforce skill (TF-188).
#
# Drops SKILL.md + three wrapper scripts into ~/.claude/skills/tf/.
# Re-running it leaves the directory in a consistent state.
#
# Usage:
#   curl -fsSL <raw url> | bash
# or, from a clone:
#   bash scripts/taskforce-skill/install.sh

set -euo pipefail

SKILL_DIR="${HOME}/.claude/skills/tf"
REPO_RAW_BASE="${TASKFORCE_SKILL_REPO_RAW:-https://raw.githubusercontent.com/al-exe/EnderAI/main/scripts/taskforce-skill}"

mkdir -p "$SKILL_DIR"

install_file() {
    local source_name="$1" target="$2" mode="$3"
    echo "→ Installing ${source_name} → ${target}"
    if [[ -f "${PWD}/scripts/taskforce-skill/${source_name}" ]]; then
        install -m "$mode" "${PWD}/scripts/taskforce-skill/${source_name}" "$target"
    else
        curl -fsSL "${REPO_RAW_BASE}/${source_name}" -o "$target"
        chmod "$mode" "$target"
    fi
}

install_file "SKILL.md"        "${SKILL_DIR}/SKILL.md"        0644
install_file "tf-discover.sh"  "${SKILL_DIR}/tf-discover.sh"  0755
install_file "tf-reference.sh" "${SKILL_DIR}/tf-reference.sh" 0755
install_file "tf-savings.sh"   "${SKILL_DIR}/tf-savings.sh"   0755

if [[ ! -r "${HOME}/.enderai_mcp_token" ]]; then
    echo ""
    echo "⚠ No Taskforce token at ~/.enderai_mcp_token."
    echo "  Connect a Claude Code agent at https://www.taskforce.tools to create one."
    echo "  The /tf skill will degrade gracefully (announce 'not connected') until it exists."
fi

echo ""
echo "✓ /tf skill installed at ${SKILL_DIR}."
echo ""
echo "Verify with:"
echo "  ls ${SKILL_DIR}"
echo ""
echo "Restart your Claude Code session, then type /tf <your task> to invoke it."
echo "Logs land at: ~/.claude/taskforce-skill.log"
