"""Add workflow_bucket table

Revision ID: 8d7f9c3a1b2e
Revises: fe56fa70289e
Create Date: 2026-02-04 09:41:00.000000

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "8d7f9c3a1b2e"
down_revision = "fe56fa70289e"
branch_labels = None
depends_on = None


def upgrade():
    # A lightweight mapping table to give workflow_key ("bucket") a human-friendly label.
    # Use IF NOT EXISTS because this repo has a mix of Alembic-managed and manually-created tables.
    op.execute(
        """
        create table if not exists public.workflow_bucket (
          workflow_key text primary key,
          bucket_name text not null,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        )
        """
    )
    op.execute(
        "create index if not exists idx_workflow_bucket_bucket_name on public.workflow_bucket (bucket_name)"
    )

    # Seed buckets from existing library items (if the table exists).
    op.execute(
        """
        do $$
        begin
          if exists (
            select 1
            from information_schema.tables
            where table_schema = 'public' and table_name = 'library_item'
          ) then
            insert into public.workflow_bucket (workflow_key, bucket_name)
            select distinct
              workflow_key,
              replace(
                replace(
                  replace(initcap(replace(workflow_key, '_', ' ')), 'Github', 'GitHub'),
                  'Api',
                  'API'
                ),
                'Db',
                'DB'
              ) as bucket_name
            from public.library_item
            on conflict (workflow_key) do nothing;
          end if;
        end
        $$;
        """
    )


def downgrade():
    op.execute("drop table if exists public.workflow_bucket")
