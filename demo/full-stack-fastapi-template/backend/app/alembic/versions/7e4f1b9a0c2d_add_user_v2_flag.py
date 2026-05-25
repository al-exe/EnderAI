"""add user v2 flag

Revision ID: 7e4f1b9a0c2d
Revises: 2b7d4f9c1e03
Create Date: 2026-05-15 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "7e4f1b9a0c2d"
down_revision = "2b7d4f9c1e03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("v2", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        """
        update "user"
        set v2 = true
        where lower(email) = 'alexlee4190'
           or lower(email) like 'alexlee4190@%'
        """
    )


def downgrade() -> None:
    op.drop_column("user", "v2")
