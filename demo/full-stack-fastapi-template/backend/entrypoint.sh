#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="/app/backend"

alembic upgrade head
# Ensure DB-backed Thread/Execution/Artifact/Event tables exist and migrate legacy data.
# This script is idempotent and safe to run on every startup.
python scripts/create_memory_tables.py
exec fastapi run --workers 4 app/main.py
