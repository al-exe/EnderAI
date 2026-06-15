#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="/app/backend"

alembic upgrade head
exec fastapi run \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-1}" \
  app/main.py
