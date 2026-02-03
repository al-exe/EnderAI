#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="/app/backend"

alembic upgrade head
exec fastapi run --workers 4 app/main.py
