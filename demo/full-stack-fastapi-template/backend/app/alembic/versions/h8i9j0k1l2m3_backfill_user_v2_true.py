"""Backfill User.v2 = true for all accounts (V1 removed; everyone is on V2).

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-06-28 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "h8i9j0k1l2m3"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The legacy V1 (topics/cases/skills) experience was removed, so the v2
    # rollout flag is now universal. Flip every existing account on and make
    # the column default to true for new rows.
    op.execute('UPDATE "user" SET v2 = true WHERE v2 = false')
    op.alter_column("user", "v2", server_default=sa.true())


def downgrade() -> None:
    op.alter_column("user", "v2", server_default=sa.false())
