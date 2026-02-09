#!/usr/bin/env python3
"""
Bootstrap/upgrade DB-backed memory tables used by Tasks/Runs/Library.

This is intentionally idempotent: safe to run multiple times.
"""

from sqlalchemy import text

from app.core.db import engine


DDL = [
    # Task table (the key migration for /runs/start is intent_key).
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
    );
    """,
    "alter table public.task add column if not exists intent_key text;",
    # Runs + audit log.
    """
    create table if not exists public.run (
      id uuid primary key,
      task_id uuid not null references public.task(id) on delete cascade,
      targets jsonb not null default '[]'::jsonb,
      started_at timestamptz not null default now(),
      ended_at timestamptz,
      status text not null default 'aborted',
      summary text
    );
    """,
    """
    create table if not exists public.run_event (
      id bigserial primary key,
      run_id uuid not null references public.run(id) on delete cascade,
      ts timestamptz not null default now(),
      type text not null,
      message text,
      data jsonb not null default '{}'::jsonb,
      supersedes_event_id bigint references public.run_event(id)
    );
    """,
    # Library items + run<->memory linkage.
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
    );
    """,
    """
    create table if not exists public.run_library_link (
      run_id uuid not null references public.run(id) on delete cascade,
      library_item_id uuid not null references public.library_item(id) on delete cascade,
      relation text not null,
      created_at timestamptz not null default now(),
      primary key (run_id, library_item_id, relation)
    );
    """,
]


def main() -> None:
    with engine.begin() as conn:
        for stmt in DDL:
            conn.execute(text(stmt))
    print("OK: memory tables ensured")


if __name__ == "__main__":
    main()

