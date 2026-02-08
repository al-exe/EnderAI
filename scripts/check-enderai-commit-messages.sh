#!/usr/bin/env bash
set -euo pipefail

range="${1:-HEAD}"

if [[ "$range" == *".."* ]]; then
  commits="$(git rev-list "$range")"
else
  commits="$(git rev-list -n 1 "$range")"
fi

fail=0
for sha in $commits; do
  msg="$(git log -n 1 --format=%B "$sha")"

  if ! grep -Eq '^EnderAI-Task:[[:space:]]*[^[:space:]].*$' <<<"$msg"; then
    echo "ERROR: commit $sha is missing: EnderAI-Task: <task_id>" >&2
    fail=1
  fi
  if ! grep -Eq '^EnderAI-Run:[[:space:]]*[^[:space:]].*$' <<<"$msg"; then
    echo "ERROR: commit $sha is missing: EnderAI-Run: <run_id>" >&2
    fail=1
  fi
done

exit "$fail"

