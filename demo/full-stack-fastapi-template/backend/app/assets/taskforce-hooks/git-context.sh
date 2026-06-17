#!/usr/bin/env bash
# Shared cwd / git-branch helpers for Taskforce hooks.

taskforce_git_branch_for_path() {
    local start="${1:-}"
    [[ -z "$start" || ! -d "$start" ]] && return 1
    command -v git >/dev/null 2>&1 || return 1

    local dir="$start"
    while [[ -n "$dir" && "$dir" != "/" ]]; do
        if git -C "$dir" rev-parse --git-dir >/dev/null 2>&1; then
            git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    return 1
}

taskforce_resolve_cwd_from_payload() {
    local payload="$1"
    jq -r '.cwd // .workspace_roots[0] // empty' <<<"$payload" 2>/dev/null
}

taskforce_resolve_git_branch_from_payload() {
    local payload="$1"
    local cwd branch file_path dir

    cwd="$(taskforce_resolve_cwd_from_payload "$payload")"
    if branch="$(taskforce_git_branch_for_path "$cwd")"; then
        printf '%s' "$branch"
        return 0
    fi

    file_path="$(
        jq -r '
            ([.attachments[]? | .file_path // .filePath // empty]
             | map(select(. != "")))[0] // empty
        ' <<<"$payload" 2>/dev/null
    )"
    if [[ -n "$file_path" ]]; then
        dir="$(dirname "$file_path")"
        if branch="$(taskforce_git_branch_for_path "$dir")"; then
            printf '%s' "$branch"
            return 0
        fi
    fi

    file_path="$(
        jq -r '
            .tool_input.file_path // .tool_input.path
            // .tool_input.target_file // empty
        ' <<<"$payload" 2>/dev/null
    )"
    if [[ -n "$file_path" ]]; then
        dir="$(dirname "$file_path")"
        if branch="$(taskforce_git_branch_for_path "$dir")"; then
            printf '%s' "$branch"
            return 0
        fi
    fi

    return 1
}

taskforce_resolve_git_branch_from_files_json() {
    local files_json="${1:-[]}"
    local file_path dir branch

    file_path="$(jq -r 'map(select(. != ""))[0] // empty' <<<"$files_json" 2>/dev/null)"
    [[ -z "$file_path" ]] && return 1
    dir="$(dirname "$file_path")"
    if branch="$(taskforce_git_branch_for_path "$dir")"; then
        printf '%s' "$branch"
        return 0
    fi
    return 1
}
