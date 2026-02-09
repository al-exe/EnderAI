#!/usr/bin/env python3
"""
Bootstrap/upgrade DB-backed memory tables used by:

- Threads (formerly Tasks)
- Executions (formerly Runs)
- Artifacts (formerly Library items / memory)
- Events (formerly Run events / audit log)

This is intentionally idempotent and includes a best-effort rename from the
legacy table/column names used in early iterations of the system.
"""

from sqlalchemy import text

from app.core.db import engine


DDL = [
    # ---- Legacy -> current renames (best-effort) ----
    """
    do $$
    begin
      if exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'task'
      ) and not exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'thread'
      ) then
        alter table public.task rename to thread;
      end if;
    end $$;
    """,
    """
    do $$
    begin
      if exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'run'
      ) and not exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'execution'
      ) then
        alter table public.run rename to execution;
      end if;
    end $$;
    """,
    """
    do $$
    begin
      if exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'run_event'
      ) and not exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'event'
      ) then
        alter table public.run_event rename to event;
      end if;
    end $$;
    """,
    """
    do $$
    begin
      if exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'library_item'
      ) and not exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'artifact'
      ) then
        alter table public.library_item rename to artifact;
      end if;
    end $$;
    """,
    """
    do $$
    begin
      if exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'run_library_link'
      ) and not exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'execution_artifact_link'
      ) then
        alter table public.run_library_link rename to execution_artifact_link;
      end if;
    end $$;
    """,
    # Column renames (after table renames).
    """
    do $$
    begin
      if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'execution' and column_name = 'task_id'
      ) and not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'execution' and column_name = 'thread_id'
      ) then
        alter table public.execution rename column task_id to thread_id;
      end if;
    end $$;
    """,
    """
    do $$
    begin
      if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'event' and column_name = 'run_id'
      ) and not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'event' and column_name = 'execution_id'
      ) then
        alter table public.event rename column run_id to execution_id;
      end if;
    end $$;
    """,
    """
    do $$
    begin
      if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'execution_artifact_link' and column_name = 'run_id'
      ) and not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'execution_artifact_link' and column_name = 'execution_id'
      ) then
        alter table public.execution_artifact_link rename column run_id to execution_id;
      end if;
    end $$;
    """,
    """
    do $$
    begin
      if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'execution_artifact_link' and column_name = 'library_item_id'
      ) and not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'execution_artifact_link' and column_name = 'artifact_id'
      ) then
        alter table public.execution_artifact_link rename column library_item_id to artifact_id;
      end if;
    end $$;
    """,
    # ---- Canonical tables (Thread/Execution/Artifact/Event) ----
    """
    create table if not exists public.thread (
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
    "alter table public.thread add column if not exists intent_key text;",
    """
    create table if not exists public.execution (
      id uuid primary key,
      thread_id uuid not null references public.thread(id) on delete cascade,
      targets jsonb not null default '[]'::jsonb,
      started_at timestamptz not null default now(),
      ended_at timestamptz,
      status text not null default 'aborted',
      summary text
    );
    """,
    """
    create table if not exists public.event (
      id bigserial primary key,
      execution_id uuid not null references public.execution(id) on delete cascade,
      ts timestamptz not null default now(),
      type text not null,
      message text,
      data jsonb not null default '{}'::jsonb,
      supersedes_event_id bigint references public.event(id)
    );
    """,
    """
    create table if not exists public.artifact (
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
      superseded_by_id uuid references public.artifact(id)
    );
    """,
    """
    create table if not exists public.execution_artifact_link (
      execution_id uuid not null references public.execution(id) on delete cascade,
      artifact_id uuid not null references public.artifact(id) on delete cascade,
      relation text not null,
      created_at timestamptz not null default now(),
      primary key (execution_id, artifact_id, relation)
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
