"""Build the public, self-contained Taskforce hook installer."""

from pathlib import Path

HOOK_ASSET_DIR = Path(__file__).resolve().parents[2] / "assets" / "taskforce-hooks"

HOOKS = (
    (
        "user-prompt-submit.sh",
        "taskforce-user-prompt-submit.sh",
        "UserPromptSubmit",
        5,
        "TASKFORCE_USER_PROMPT_SUBMIT_EOF",
    ),
    (
        "stop.sh",
        "taskforce-stop.sh",
        "Stop",
        30,
        "TASKFORCE_STOP_EOF",
    ),
    (
        "post-tool-use.sh",
        "taskforce-post-tool-use.sh",
        "PostToolUse",
        15,
        "TASKFORCE_POST_TOOL_USE_EOF",
    ),
)


def build_hook_installer() -> str:
    """Return an installer that writes and registers all Taskforce hooks."""

    lines = [
        "#!/usr/bin/env bash",
        "# Public Taskforce Claude Code hook installer.",
        "# Hook sources mirror scripts/taskforce-hooks/ in the EnderAI repository.",
        "",
        "set -euo pipefail",
        "",
        'HOOK_DIR="${HOME}/.claude/hooks"',
        'SETTINGS_FILE="${HOME}/.claude/settings.json"',
        "",
        "if ! command -v jq >/dev/null 2>&1; then",
        '    echo "ERROR: jq is required to install Taskforce hooks." >&2',
        "    exit 1",
        "fi",
        "",
        'mkdir -p "$HOOK_DIR" "${HOME}/.taskforce"',
        "",
    ]

    for source_name, target_name, _, _, delimiter in HOOKS:
        script = (HOOK_ASSET_DIR / source_name).read_text().rstrip("\n")
        lines.extend(
            [
                f"# Source: scripts/taskforce-hooks/{source_name}",
                f"cat > \"$HOOK_DIR/{target_name}\" <<'{delimiter}'",
                script,
                delimiter,
                f'chmod 0755 "$HOOK_DIR/{target_name}"',
                "",
            ]
        )

    lines.extend(
        [
            'mkdir -p "$(dirname "$SETTINGS_FILE")"',
            'if [[ ! -f "$SETTINGS_FILE" ]]; then',
            "    echo '{}' > \"$SETTINGS_FILE\"",
            "fi",
            "",
            "merge_hook() {",
            '    local hook_name="$1" command="$2" timeout="$3"',
            "    local tmp_file",
            '    tmp_file="$(mktemp)"',
            '    jq --arg hook_name "$hook_name" --arg cmd "$command" '
            '--argjson timeout "$timeout" \'',
            "        .hooks = (.hooks // {})",
            "        | .hooks[$hook_name] = (",
            "            .hooks[$hook_name]",
            '            // [{matcher: "*", hooks: []}]',
            "        )",
            "        | .hooks[$hook_name] |= (",
            "            if (any(.[]; .hooks[]?.command == $cmd)) then",
            "                .",
            '            elif (any(.[]; .matcher == "*")) then',
            "                map(",
            '                    if .matcher == "*" then',
            "                        .hooks = ((.hooks // []) + [",
            '                            {type: "command", command: $cmd, '
            "timeout: $timeout}",
            "                        ])",
            "                    else . end",
            "                )",
            "            else",
            '                . + [{matcher: "*", hooks: [',
            '                    {type: "command", command: $cmd, timeout: $timeout}',
            "                ]}]",
            "            end",
            "        )",
            '    \' "$SETTINGS_FILE" > "$tmp_file"',
            '    mv "$tmp_file" "$SETTINGS_FILE"',
            "}",
            "",
        ]
    )

    for _, target_name, hook_name, timeout, _ in HOOKS:
        lines.append(f'merge_hook {hook_name} "$HOOK_DIR/{target_name}" {timeout}')

    lines.extend(
        [
            "",
            'echo "✓ Taskforce hooks installed — restart Claude Code to activate."',
            "",
        ]
    )
    return "\n".join(lines)
