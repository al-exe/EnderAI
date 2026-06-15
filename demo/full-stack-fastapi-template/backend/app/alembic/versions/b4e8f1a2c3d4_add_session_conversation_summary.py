"""Add stable Fleet session labels to session archives.

Revision ID: b4e8f1a2c3d4
Revises: a1f8c3e2d9b0
Create Date: 2026-06-15 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "b4e8f1a2c3d4"
down_revision = "a1f8c3e2d9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "taskforce_session_archive",
        sa.Column("conversation_summary", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "taskforce_session_archive",
        sa.Column("display_name", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("taskforce_session_archive", "display_name")
    op.drop_column("taskforce_session_archive", "conversation_summary")
