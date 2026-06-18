#!/usr/bin/env bash
# Idempotent installer for the /tf Taskforce skill (TF-188).
#
# Installs SKILL.md + three wrapper scripts into the skills directory of
# every supported harness found on this machine:
#   - Claude Code → ~/.claude/skills/tf/
#   - Cursor      → ~/.cursor/skills-cursor/tf/
#   - Codex       → ~/.codex/skills/tf/
# The SKILL.md + scripts are byte-identical across harnesses; only the
# install location differs. Re-running leaves every directory consistent.
#
# By default it installs into each harness whose parent config dir already
# exists (so a Claude-only box stays Claude-only). Override the target set:
#   TASKFORCE_SKILL_TARGETS="claude cursor codex"  # force all three
#   TASKFORCE_SKILL_TARGETS="claude"               # just one
#
# Usage:
#   curl -fsSL <raw url> | bash
# or, from a clone:
#   bash scripts/taskforce-skill/install.sh

set -euo pipefail

REPO_RAW_BASE="${TASKFORCE_SKILL_REPO_RAW:-https://raw.githubusercontent.com/al-exe/EnderAI/main/scripts/taskforce-skill}"

# Map each harness → its skills/<name> directory. The "tf" leaf is the skill.
declare -A HARNESS_DIR=(
    [claude]="${HOME}/.claude/skills/tf"
    [cursor]="${HOME}/.cursor/skills-cursor/tf"
    [codex]="${HOME}/.codex/skills/tf"
)
# Parent that must exist for a harness to be auto-detected as "present".
declare -A HARNESS_ROOT=(
    [claude]="${HOME}/.claude"
    [cursor]="${HOME}/.cursor"
    [codex]="${HOME}/.codex"
)

# Resolve the target harness list: explicit override, else auto-detect.
if [[ -n "${TASKFORCE_SKILL_TARGETS:-}" ]]; then
    read -r -a TARGETS <<<"${TASKFORCE_SKILL_TARGETS}"
else
    TARGETS=()
    for h in claude cursor codex; do
        [[ -d "${HARNESS_ROOT[$h]}" ]] && TARGETS+=("$h")
    done
    # Fall back to Claude if nothing detected (fresh box / piped installer).
    [[ ${#TARGETS[@]} -eq 0 ]] && TARGETS=(claude)
fi

install_file() {
    local source_name="$1" target="$2" mode="$3"
    echo "  → ${source_name} → ${target}"
    if [[ -f "${PWD}/scripts/taskforce-skill/${source_name}" ]]; then
        install -m "$mode" "${PWD}/scripts/taskforce-skill/${source_name}" "$target"
    else
        curl -fsSL "${REPO_RAW_BASE}/${source_name}" -o "$target"
        chmod "$mode" "$target"
    fi
}

install_into() {
    local skill_dir="$1"
    mkdir -p "$skill_dir"
    install_file "SKILL.md"        "${skill_dir}/SKILL.md"        0644
    install_file "tf-discover.sh"  "${skill_dir}/tf-discover.sh"  0755
    install_file "tf-fleet.sh"     "${skill_dir}/tf-fleet.sh"     0755
    install_file "tf-reference.sh" "${skill_dir}/tf-reference.sh" 0755
    install_file "tf-capture.sh"   "${skill_dir}/tf-capture.sh"   0755
    install_file "tf-savings.sh"   "${skill_dir}/tf-savings.sh"   0755
}

INSTALLED=()
for h in "${TARGETS[@]}"; do
    dir="${HARNESS_DIR[$h]:-}"
    if [[ -z "$dir" ]]; then
        echo "⚠ Unknown harness '${h}' — skipping (valid: claude cursor codex)."
        continue
    fi
    echo "Installing /tf for ${h}:"
    install_into "$dir"
    INSTALLED+=("${h} (${dir})")
done

TOKEN_FILE="${HOME}/.taskforce_mcp_token"
LEGACY_TOKEN_FILE="${HOME}/.enderai_mcp_token"
if [[ ! -r "$TOKEN_FILE" && ! -r "$LEGACY_TOKEN_FILE" ]]; then
    echo ""
    echo "⚠ No Taskforce token at ~/.taskforce_mcp_token."
    echo "  Connect an agent at https://www.taskforce.tools to create one."
    echo "  The /tf skill will degrade gracefully (announce 'not connected') until it exists."
fi

echo ""
echo "✓ /tf skill installed for: ${INSTALLED[*]}"
echo ""
echo "Restart your agent session, then type /tf <your task> to invoke it."
echo "Logs land at: ~/.claude/taskforce-skill.log"
