"""Build the public, self-contained Taskforce hook installer."""

from pathlib import Path

HOOK_ASSET_DIR = Path(__file__).resolve().parents[2] / "assets" / "taskforce-hooks"
CODEX_HOOK_ASSET_DIR = (
    Path(__file__).resolve().parents[2] / "assets" / "taskforce-codex-hooks"
)
CURSOR_HOOK_ASSET_DIR = (
    Path(__file__).resolve().parents[2] / "assets" / "taskforce-cursor-hooks"
)

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
    (
        "session-end.sh",
        "taskforce-session-end.sh",
        "SessionEnd",
        15,
        "TASKFORCE_SESSION_END_EOF",
    ),
    (
        "record-usage.sh",
        "taskforce-record-usage.sh",
        "Stop",
        10,
        "TASKFORCE_RECORD_USAGE_EOF",
    ),
)

CODEX_HOOKS = (
    (
        "session-start.sh",
        "taskforce-session-start.sh",
        "SessionStart",
        "startup|resume|clear|compact",
        10,
        "TASKFORCE_CODEX_SESSION_START_EOF",
    ),
    (
        "user-prompt-submit.sh",
        "taskforce-user-prompt-submit.sh",
        "UserPromptSubmit",
        "*",
        5,
        "TASKFORCE_CODEX_USER_PROMPT_SUBMIT_EOF",
    ),
    (
        "observe.sh",
        "taskforce-observe.sh",
        "PostToolUse",
        "*",
        15,
        "TASKFORCE_CODEX_OBSERVE_POST_TOOL_USE_EOF",
    ),
    (
        "observe.sh",
        "taskforce-observe.sh",
        "Stop",
        "*",
        15,
        "TASKFORCE_CODEX_OBSERVE_STOP_EOF",
    ),
)

CURSOR_HOOKS = (
    (
        "session-start.sh",
        "taskforce-session-start.sh",
        "sessionStart",
        10,
        "TASKFORCE_CURSOR_SESSION_START_EOF",
    ),
    (
        "before-submit-prompt.sh",
        "taskforce-before-submit-prompt.sh",
        "beforeSubmitPrompt",
        5,
        "TASKFORCE_CURSOR_BEFORE_SUBMIT_PROMPT_EOF",
    ),
    (
        "post-tool-use.sh",
        "taskforce-post-tool-use.sh",
        "postToolUse",
        15,
        "TASKFORCE_CURSOR_POST_TOOL_USE_EOF",
    ),
    (
        "stop.sh",
        "taskforce-stop.sh",
        "stop",
        30,
        "TASKFORCE_CURSOR_STOP_EOF",
    ),
    (
        "session-end.sh",
        "taskforce-session-end.sh",
        "sessionEnd",
        15,
        "TASKFORCE_CURSOR_SESSION_END_EOF",
    ),
)

JQ_FILES = (
    ("transcript-extract.jq", "transcript-extract.jq", "TASKFORCE_TRANSCRIPT_JQ_EOF"),
    ("commands-extract.jq", "commands-extract.jq", "TASKFORCE_COMMANDS_JQ_EOF"),
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

    for source_name, target_name, delimiter in JQ_FILES:
        script = (HOOK_ASSET_DIR / source_name).read_text().rstrip("\n")
        lines.extend(
            [
                f"# Source: scripts/taskforce-hooks/{source_name}",
                f"cat > \"$HOOK_DIR/{target_name}\" <<'{delimiter}'",
                script,
                delimiter,
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
            'echo "✓ Taskforce hooks installed (discovery, capture, metrics) '
            '— restart Claude Code to activate."',
            "",
        ]
    )
    return "\n".join(lines)


def build_codex_hook_installer() -> str:
    """Return an installer for Taskforce's Codex lifecycle hooks."""

    lines = [
        "#!/usr/bin/env bash",
        "# Public Taskforce Codex hook installer.",
        "# Hook sources mirror scripts/taskforce-codex-hooks/ in the EnderAI repository.",
        "",
        "set -euo pipefail",
        "",
        'HOOK_DIR="${HOME}/.codex/hooks"',
        'SETTINGS_FILE="${HOME}/.codex/hooks.json"',
        "",
        "if ! command -v jq >/dev/null 2>&1; then",
        '    echo "ERROR: jq is required to install Taskforce hooks." >&2',
        "    exit 1",
        "fi",
        "",
        'mkdir -p "$HOOK_DIR" "${HOME}/.taskforce"',
        "",
    ]

    for source_name, target_name, _, _, _, delimiter in CODEX_HOOKS:
        script = (CODEX_HOOK_ASSET_DIR / source_name).read_text().rstrip("\n")
        lines.extend(
            [
                f"# Source: scripts/taskforce-codex-hooks/{source_name}",
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
            '    echo \'{"hooks": {}}\' > "$SETTINGS_FILE"',
            "fi",
            "",
            "merge_hook() {",
            '    local hook_name="$1" matcher="$2" command="$3" timeout="$4"',
            "    local tmp_file",
            '    tmp_file="$(mktemp)"',
            '    jq --arg hook_name "$hook_name" --arg matcher "$matcher" '
            '--arg cmd "$command" --argjson timeout "$timeout" \'',
            "        .hooks = (.hooks // {})",
            "        | .hooks[$hook_name] = (.hooks[$hook_name] // [])",
            "        | .hooks[$hook_name] |= (",
            "            if (any(.[]; .hooks[]?.command == $cmd)) then",
            "                .",
            '            elif (any(.[]; (.matcher // "*") == $matcher)) then',
            "                map(",
            '                    if (.matcher // "*") == $matcher then',
            "                        .hooks = ((.hooks // []) + [",
            '                            {type: "command", command: $cmd, '
            "timeout: $timeout}",
            "                        ])",
            "                    else . end",
            "                )",
            "            else",
            "                . + [{matcher: $matcher, hooks: [",
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

    for _, target_name, hook_name, matcher, timeout, _ in CODEX_HOOKS:
        lines.append(
            f'merge_hook {hook_name} "{matcher}" "$HOOK_DIR/{target_name}" {timeout}'
        )

    lines.extend(
        [
            "",
            'echo "Taskforce Codex hooks installed."',
            'echo "Restart Codex, run /hooks, and trust the Taskforce hooks."',
            'echo "Start one more Codex session after trusting them to activate Sessions registration."',
            "",
        ]
    )
    return "\n".join(lines)


def build_cursor_hook_installer() -> str:
    """Return an installer for Taskforce's Cursor lifecycle hooks."""

    lines = [
        "#!/usr/bin/env bash",
        "# Public Taskforce Cursor hook installer.",
        "# Hook sources mirror scripts/taskforce-cursor-hooks/ in the EnderAI repository.",
        "",
        "set -euo pipefail",
        "",
        'CURSOR_DIR="${HOME}/.cursor"',
        'HOOK_DIR="${CURSOR_DIR}/hooks"',
        'SETTINGS_FILE="${CURSOR_DIR}/hooks.json"',
        "",
        "if ! command -v jq >/dev/null 2>&1; then",
        '    echo "ERROR: jq is required to install Taskforce hooks." >&2',
        "    exit 1",
        "fi",
        "",
        'mkdir -p "$HOOK_DIR" "${HOME}/.taskforce"',
        "",
    ]

    for source_name, target_name, _, _, delimiter in CURSOR_HOOKS:
        script = (CURSOR_HOOK_ASSET_DIR / source_name).read_text().rstrip("\n")
        lines.extend(
            [
                f"# Source: scripts/taskforce-cursor-hooks/{source_name}",
                f"cat > \"$HOOK_DIR/{target_name}\" <<'{delimiter}'",
                script,
                delimiter,
                f'chmod 0755 "$HOOK_DIR/{target_name}"',
                "",
            ]
        )

    for source_name, target_name, delimiter in JQ_FILES:
        script = (CURSOR_HOOK_ASSET_DIR / source_name).read_text().rstrip("\n")
        lines.extend(
            [
                f"# Source: scripts/taskforce-cursor-hooks/{source_name}",
                f"cat > \"$HOOK_DIR/{target_name}\" <<'{delimiter}'",
                script,
                delimiter,
                "",
            ]
        )

    lines.extend(
        [
            'mkdir -p "$CURSOR_DIR"',
            'if [[ ! -f "$SETTINGS_FILE" ]]; then',
            '    echo \'{"version": 1, "hooks": {}}\' > "$SETTINGS_FILE"',
            "fi",
            "",
            "merge_hook() {",
            '    local hook_name="$1" command="$2" timeout="$3"',
            "    local tmp_file",
            '    tmp_file="$(mktemp)"',
            '    jq --arg hook_name "$hook_name" --arg cmd "$command" '
            '--argjson timeout "$timeout" \'',
            "        .version = (.version // 1)",
            "        | .hooks = (.hooks // {})",
            "        | .hooks[$hook_name] = (.hooks[$hook_name] // [])",
            "        | .hooks[$hook_name] |= (",
            "            if (any(.[]; .command == $cmd)) then",
            "                .",
            "            else",
            "                . + [{command: $cmd, timeout: $timeout}]",
            "            end",
            "        )",
            '    \' "$SETTINGS_FILE" > "$tmp_file"',
            '    mv "$tmp_file" "$SETTINGS_FILE"',
            "}",
            "",
        ]
    )

    for _, target_name, hook_name, timeout, _ in CURSOR_HOOKS:
        lines.append(f'merge_hook {hook_name} "./hooks/{target_name}" {timeout}')

    lines.extend(
        [
            "",
            'echo "Taskforce Cursor hooks installed."',
            'echo "Restart Cursor (or reload hooks from Settings -> Hooks) to activate."',
            'echo "New Agent sessions will appear in Sessions after sessionStart fires."',
            "",
        ]
    )
    return "\n".join(lines)
