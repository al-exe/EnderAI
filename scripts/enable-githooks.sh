#!/usr/bin/env bash
set -euo pipefail

# Opt-in local enforcement. CI is the hard gate.
git config core.hooksPath .githooks
echo "Configured git hooks path to .githooks"

