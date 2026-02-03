#!/usr/bin/env bash
set -euo pipefail

alembic upgrade head
exec fastapi run --workers 4 app/main.py
