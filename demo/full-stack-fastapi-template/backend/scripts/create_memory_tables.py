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
from sqlmodel import Session

from app.core.topics import refresh_topic_rollup
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
    "alter table public.thread add column if not exists topic_data jsonb not null default '{}'::jsonb;",
    "alter table public.thread add column if not exists topic_rollup jsonb not null default '{}'::jsonb;",
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
    "alter table public.execution add column if not exists updated_at timestamptz not null default now();",
    "alter table public.execution add column if not exists case_data jsonb not null default '{}'::jsonb;",
    "alter table public.execution add column if not exists context_pack_snapshot jsonb not null default '{}'::jsonb;",
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
    # ---- Data migration (handles the "both old and new tables exist" case) ----
    # This can happen if a previous deploy created the new tables but did not rename the legacy ones.
    """
    do $$
    declare has_intent boolean;
    begin
      if exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'task'
      ) and exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'thread'
      ) then
        select exists (
          select 1 from information_schema.columns
          where table_schema = 'public' and table_name = 'task' and column_name = 'intent_key'
        ) into has_intent;

        if has_intent then
          insert into public.thread (
            id, title, workflow_key, intent_key, goal, acceptance_criteria,
            systems_touched, risk_level, status, created_at, last_touched_at
          )
          select
            t.id, t.title, t.workflow_key, t.intent_key, t.goal, t.acceptance_criteria,
            t.systems_touched, t.risk_level, t.status, t.created_at, t.last_touched_at
          from public.task t
          where not exists (select 1 from public.thread th where th.id = t.id);
        else
          insert into public.thread (
            id, title, workflow_key, intent_key, goal, acceptance_criteria,
            systems_touched, risk_level, status, created_at, last_touched_at
          )
          select
            t.id, t.title, t.workflow_key, null, t.goal, t.acceptance_criteria,
            t.systems_touched, t.risk_level, t.status, t.created_at, t.last_touched_at
          from public.task t
          where not exists (select 1 from public.thread th where th.id = t.id);
        end if;
      end if;
    end $$;
    """,
    """
    do $$
    begin
      if exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'run'
      ) and exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'execution'
      ) then
        insert into public.execution (
          id, thread_id, targets, started_at, ended_at, status, summary
        )
        select
          r.id, r.task_id, r.targets, r.started_at, r.ended_at, r.status, r.summary
        from public.run r
        where not exists (select 1 from public.execution e where e.id = r.id);
      end if;
    end $$;
    """,
    """
    do $$
    begin
      if exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'run_event'
      ) and exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'event'
      ) then
        insert into public.event (
          id, execution_id, ts, type, message, data, supersedes_event_id
        )
        select
          e.id, e.run_id, e.ts, e.type, e.message, e.data, e.supersedes_event_id
        from public.run_event e
        where not exists (select 1 from public.event ev where ev.id = e.id);

        perform setval(
          pg_get_serial_sequence('public.event', 'id'),
          greatest(coalesce((select max(id) from public.event), 0), 1),
          true
        );
      end if;
    end $$;
    """,
    """
    do $$
    begin
      if exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'library_item'
      ) and exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'artifact'
      ) then
        insert into public.artifact (
          id, workflow_key, kind, title, body_mdc, tags, source_refs,
          created_at, last_used_at, promotion_mode, superseded_by_id
        )
        select
          li.id, li.workflow_key, li.kind, li.title, li.body_mdc, li.tags, li.source_refs,
          li.created_at, li.last_used_at, li.promotion_mode, li.superseded_by_id
        from public.library_item li
        where not exists (select 1 from public.artifact a where a.id = li.id);
      end if;
    end $$;
    """,
    """
    do $$
    begin
      if exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'run_library_link'
      ) and exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'execution_artifact_link'
      ) then
        insert into public.execution_artifact_link (
          execution_id, artifact_id, relation, created_at
        )
        select
          l.run_id, l.library_item_id, l.relation, l.created_at
        from public.run_library_link l
        on conflict (execution_id, artifact_id, relation) do nothing;
      end if;
    end $$;
    """,
]


def main() -> None:
    with engine.begin() as conn:
        for stmt in DDL:
            conn.execute(text(stmt))
    with Session(engine) as session:
        topic_ids = session.connection().execute(text("select id from public.thread")).scalars().all()
        for topic_id in topic_ids:
            refresh_topic_rollup(session, topic_id, persist=True)
        session.commit()
    print("OK: memory tables ensured")


if __name__ == "__main__":
    main()
