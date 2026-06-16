"""Add last_turn_ended_at to session archive for Fleet turn-state.

Lets Fleet distinguish a session actively running a turn from one that has
finished and is awaiting the next user prompt. Advanced by the Claude Code
Stop hook via POST /v2/taskforce/session/turn-ended.

Revision ID: c7d8e9f0a1b2
Revises: f6a1b2c3d4e5
Create Date: 2026-06-16 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "c7d8e9f0a1b2"
down_revision = "f6a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "taskforce_session_archive",
        sa.Column("last_turn_ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_taskforce_session_archive_last_turn_ended_at",
        "taskforce_session_archive",
        ["last_turn_ended_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_taskforce_session_archive_last_turn_ended_at",
        table_name="taskforce_session_archive",
    )
    op.drop_column("taskforce_session_archive", "last_turn_ended_at")
