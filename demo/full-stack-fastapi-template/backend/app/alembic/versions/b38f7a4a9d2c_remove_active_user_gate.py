"""Remove active-user gate

Revision ID: b38f7a4a9d2c
Revises: d6e9f3b5c2a8
Create Date: 2026-05-19 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "b38f7a4a9d2c"
down_revision = "d6e9f3b5c2a8"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text('UPDATE "user" SET is_active = TRUE WHERE is_active = FALSE'))
    op.alter_column(
        "user",
        "is_active",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.true(),
    )


def downgrade():
    op.alter_column(
        "user",
        "is_active",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.false(),
    )
