"""add demo mode seed columns

Revision ID: c4f5d9e7b2a1
Revises: 6f2b5e6c3a11
Create Date: 2026-03-28 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c4f5d9e7b2a1"
down_revision = "6f2b5e6c3a11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("demo_seeded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "topic",
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_topic_is_demo", "topic", ["is_demo"], unique=False)
    op.alter_column("topic", "is_demo", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_topic_is_demo", table_name="topic")
    op.drop_column("topic", "is_demo")
    op.drop_column("user", "demo_seeded_at")
