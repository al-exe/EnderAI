"""add user last_seen_at

Revision ID: 4c7b1a8f0d2e
Revises: a6b4e2c9d1f0
Create Date: 2026-05-03 15:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4c7b1a8f0d2e"
down_revision = "a6b4e2c9d1f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user", "last_seen_at")
