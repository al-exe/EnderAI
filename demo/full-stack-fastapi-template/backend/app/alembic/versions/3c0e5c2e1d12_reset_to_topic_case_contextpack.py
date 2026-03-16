"""Reset domain schema to canonical Topic/Case/ContextPack

Revision ID: 3c0e5c2e1d12
Revises: b2055405c0df
Create Date: 2026-03-16 00:15:00.000000

"""

from alembic import op


revision = "3c0e5c2e1d12"
down_revision = "b2055405c0df"
branch_labels = None
depends_on = None


LEGACY_TABLES = [
    "execution_artifact_link",
    "run_library_link",
    "artifact",
    "library_item",
    "case_event",  # dropped/recreated canonically below if a stale copy exists
    "event",
    "case_record",  # dropped/recreated canonically below if a stale copy exists
    "execution",
    "run",
    "topic",  # dropped/recreated canonically below if a stale copy exists
    "thread",
    "task",
    "workflow_bucket",
    "item",
]


def upgrade():
    for table_name in LEGACY_TABLES:
        op.execute(f'drop table if exists public.{table_name} cascade')

    op.execute(
        """
        create table public.topic (
          id uuid primary key,
          title varchar(255) not null,
          slug varchar(255) not null unique,
          workflow_key varchar(255) not null unique,
          description text,
          aliases jsonb not null default '[]'::jsonb,
          status varchar(64) not null default 'open',
          owner_ids jsonb not null default '[]'::jsonb,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          last_used_at timestamptz,
          rollup_summary text,
          rollup_version integer not null default 1,
          rollup_data jsonb not null default '{}'::jsonb
        )
        """
    )
    op.execute("create index idx_topic_last_used_at on public.topic (last_used_at desc)")

    op.execute(
        """
        create table public.case_record (
          id uuid primary key,
          topic_id uuid not null references public.topic(id) on delete cascade,
          title varchar(255) not null,
          opened_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          closed_at timestamptz,
          status varchar(64) not null default 'open',
          actor_id uuid,
          source text,
          input_summary text,
          summary_current text,
          case_data jsonb not null default '{}'::jsonb,
          context_pack_snapshot jsonb not null default '{}'::jsonb
        )
        """
    )
    op.execute("create index idx_case_record_topic_id on public.case_record (topic_id)")
    op.execute("create index idx_case_record_updated_at on public.case_record (updated_at desc)")

    op.execute(
        """
        create table public.case_event (
          id bigserial primary key,
          case_id uuid not null references public.case_record(id) on delete cascade,
          ts timestamptz not null default now(),
          type varchar(128) not null,
          message text,
          data jsonb not null default '{}'::jsonb,
          supersedes_event_id bigint references public.case_event(id)
        )
        """
    )
    op.execute("create index idx_case_event_case_id on public.case_event (case_id)")


def downgrade():
    op.execute('drop table if exists public.case_event cascade')
    op.execute('drop table if exists public.case_record cascade')
    op.execute('drop table if exists public.topic cascade')
