"""Add per-session auto-archive opt-out flag.

Revision ID: g7h8i9j0k1l2
Revises: f5a6b7c8d9e0
Create Date: 2026-06-27 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "g7h8i9j0k1l2"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "taskforce_fleet_session",
        sa.Column(
            "auto_archive_disabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("taskforce_fleet_session", "auto_archive_disabled")
