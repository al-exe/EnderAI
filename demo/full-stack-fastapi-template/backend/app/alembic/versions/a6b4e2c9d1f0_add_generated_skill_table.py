"""Add generated Skill table

Revision ID: a6b4e2c9d1f0
Revises: f03a5d2b9c11
Create Date: 2026-05-03 00:00:00.000000

"""

from alembic import op


revision = "a6b4e2c9d1f0"
down_revision = "f03a5d2b9c11"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        create table public.skill (
          id uuid primary key,
          title varchar(255) not null,
          slug varchar(255) not null,
          description text,
          status varchar(64) not null default 'published',
          source_type varchar(64) not null default 'topic',
          source_topic_id uuid references public.topic(id) on delete set null,
          source_case_ids jsonb not null default '[]'::jsonb,
          owner_ids jsonb not null default '[]'::jsonb,
          is_demo boolean not null default false,
          trigger_phrases jsonb not null default '[]'::jsonb,
          files jsonb not null default '[]'::jsonb,
          symbols jsonb not null default '[]'::jsonb,
          errors jsonb not null default '[]'::jsonb,
          symptoms jsonb not null default '[]'::jsonb,
          instructions_md text not null,
          confidence varchar(16) not null default 'medium',
          source_snapshot jsonb not null default '{}'::jsonb,
          usage_count integer not null default 0,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          last_used_at timestamptz
        )
        """
    )
    op.execute("create index idx_skill_slug on public.skill (slug)")
    op.execute(
        "create index idx_skill_source_topic_id on public.skill (source_topic_id)"
    )
    op.execute("create index idx_skill_is_demo on public.skill (is_demo)")
    op.execute("create index idx_skill_updated_at on public.skill (updated_at desc)")


def downgrade():
    op.execute("drop table if exists public.skill cascade")
