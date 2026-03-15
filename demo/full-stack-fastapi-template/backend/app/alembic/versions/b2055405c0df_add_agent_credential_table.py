"""Add agent_credential table

Revision ID: b2055405c0df
Revises: 8d7f9c3a1b2e
Create Date: 2026-03-14 22:05:00.000000

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "b2055405c0df"
down_revision = "8d7f9c3a1b2e"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        create table if not exists public.agent_credential (
          id uuid primary key,
          user_id uuid not null references public."user"(id) on delete cascade,
          label varchar(255) not null,
          token_version integer not null default 1,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          last_rotated_at timestamptz not null default now(),
          current_token_expires_at timestamptz not null,
          last_used_at timestamptz,
          revoked_at timestamptz
        )
        """
    )
    op.execute(
        """
        create index if not exists idx_agent_credential_user_id
        on public.agent_credential (user_id)
        """
    )


def downgrade():
    op.execute("drop table if exists public.agent_credential")
