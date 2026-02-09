#!/usr/bin/env python3
"""
Create minimal "Tasks + Library" memory tables in Postgres for the EnderAI demo.

Reads connection info from either:
  - DATABASE_URL (preferred), or
  - PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD

No secrets are stored in-repo; pass creds via env vars.
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg2


def _dsn_from_env() -> str:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    required = ["PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise SystemExit(
            "Missing env vars. Set DATABASE_URL or: "
            + ", ".join(missing)
        )

    return (
        f"host={os.environ['PGHOST']} "
        f"port={os.environ['PGPORT']} "
        f"dbname={os.environ['PGDATABASE']} "
        f"user={os.environ['PGUSER']} "
        f"password={os.environ['PGPASSWORD']}"
    )


DDL_STATEMENTS: list[str] = [
    # Task: durable container for a goal that may span multiple runs.
    """
    create table if not exists public.task (
      id uuid primary key,
      title text not null,
      workflow_key text not null,
      intent_key text,
      goal text,
      acceptance_criteria text,
      systems_touched jsonb not null default '{}'::jsonb,
      risk_level text not null default 'read_only',
      status text not null default 'open',
      created_at timestamptz not null default now(),
      last_touched_at timestamptz not null default now()
    )
    """,
    # Schema evolution: keep this script idempotent across deployed DBs.
    "alter table public.task add column if not exists intent_key text",
    "create index if not exists idx_task_workflow_key on public.task (workflow_key)",
    "create index if not exists idx_task_workflow_intent_key on public.task (workflow_key, intent_key)",
    "create index if not exists idx_task_status on public.task (status)",
    "create index if not exists idx_task_last_touched_at on public.task (last_touched_at)",
    # Run: one attempt/session at a task.
    """
    create table if not exists public.run (
      id uuid primary key,
      task_id uuid not null references public.task(id) on delete cascade,
      targets jsonb not null default '[]'::jsonb,
      started_at timestamptz not null default now(),
      ended_at timestamptz,
      status text not null default 'aborted',
      summary text
    )
    """,
    "create index if not exists idx_run_task_id_started_at on public.run (task_id, started_at desc)",
    # Run events: append-only log for trust/auditability.
    """
    create table if not exists public.run_event (
      id bigserial primary key,
      run_id uuid not null references public.run(id) on delete cascade,
      ts timestamptz not null default now(),
      type text not null,
      message text,
      data jsonb not null default '{}'::jsonb,
      supersedes_event_id bigint references public.run_event(id)
    )
    """,
    "create index if not exists idx_run_event_run_id_ts on public.run_event (run_id, ts)",
    "create index if not exists idx_run_event_type on public.run_event (type)",
    # Library items: promoted, reusable memory. Never delete; supersede.
    """
    create table if not exists public.library_item (
      id uuid primary key,
      workflow_key text not null,
      kind text not null,
      title text not null,
      body_mdc text not null,
      tags jsonb not null default '{}'::jsonb,
      source_refs jsonb not null default '[]'::jsonb,
      created_at timestamptz not null default now(),
      last_used_at timestamptz,
      promotion_mode text not null default 'auto',
      superseded_by_id uuid references public.library_item(id)
    )
    """,
    "create index if not exists idx_library_item_workflow_key_kind on public.library_item (workflow_key, kind)",
    "create index if not exists idx_library_item_superseded_by_id on public.library_item (superseded_by_id)",
    # Workflow buckets: human-readable labels for workflow_key.
    """
    create table if not exists public.workflow_bucket (
      workflow_key text primary key,
      bucket_name text not null,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )
    """,
    "create index if not exists idx_workflow_bucket_bucket_name on public.workflow_bucket (bucket_name)",
    # Link table: how a run used/created/promoted/superseded memory.
    """
    create table if not exists public.run_library_link (
      run_id uuid not null references public.run(id) on delete cascade,
      library_item_id uuid not null references public.library_item(id) on delete cascade,
      relation text not null,
      created_at timestamptz not null default now(),
      primary key (run_id, library_item_id, relation)
    )
    """,
    "create index if not exists idx_run_library_link_run_id_relation on public.run_library_link (run_id, relation)",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print DDL statements without executing.",
    )
    args = parser.parse_args()

    if args.dry_run:
        for stmt in DDL_STATEMENTS:
            print(stmt.strip() + ";\n")
        return 0

    dsn = _dsn_from_env()
    conn = psycopg2.connect(dsn)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            for stmt in DDL_STATEMENTS:
                cur.execute(stmt)
    finally:
        conn.close()

    print("OK: memory tables are present (create-if-not-exists).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
