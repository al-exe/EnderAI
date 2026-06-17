"""Rename the Fleet "History" session to "Archive".

The history bucket is now a user-controlled "Archive" group — agents are never
swept into it automatically, only by an explicit user drag. Rename existing
buckets (identified by the stable ``is_history`` flag) so the display name
matches. The column name ``is_history`` is intentionally left unchanged for
schema stability.

Revision ID: d1e2f3a4b5c6
Revises: c7d8e9f0a1b2
Create Date: 2026-06-16 23:55:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "d1e2f3a4b5c6"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE taskforce_fleet_session
            SET name = 'Archive'
            WHERE is_history = true AND name = 'History'
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE taskforce_fleet_session
            SET name = 'History'
            WHERE is_history = true AND name = 'Archive'
            """
        )
    )
