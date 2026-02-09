#! /usr/bin/env bash

set -e
set -x

# Let the DB start
python app/backend_pre_start.py

# Run migrations
alembic upgrade head

# Ensure DB-backed memory tables (Tasks/Runs/Library) are present and up to date.
# This is idempotent and safe to run on every startup.
python scripts/create_memory_tables.py

# Create initial data in DB
python app/initial_data.py
