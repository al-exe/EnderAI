"""Default new users to inactive

Revision ID: f03a5d2b9c11
Revises: c4f5d9e7b2a1
Create Date: 2026-05-03 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "f03a5d2b9c11"
down_revision = "c4f5d9e7b2a1"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "user",
        "is_active",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.false(),
    )


def downgrade():
    op.alter_column(
        "user",
        "is_active",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=None,
    )
