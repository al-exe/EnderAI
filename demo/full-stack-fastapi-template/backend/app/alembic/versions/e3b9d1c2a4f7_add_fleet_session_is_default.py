"""Add explicit default flag to Fleet session groups.

Revision ID: e3b9d1c2a4f7
Revises: d1e2f3a4b5c6
Create Date: 2026-06-17 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "e3b9d1c2a4f7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "taskforce_fleet_session",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_taskforce_fleet_session_is_default",
        "taskforce_fleet_session",
        ["is_default"],
    )

    # Backfill: flag exactly one non-history group per actor as the default.
    # Prefer the conventionally-named "Session 1", otherwise the oldest group,
    # so existing actors (incl. those with a single session) get a marked default.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            WITH chosen AS (
                SELECT DISTINCT ON (actor_id) id
                FROM taskforce_fleet_session
                WHERE is_history = false
                ORDER BY
                    actor_id,
                    (name = 'Session 1') DESC,
                    created_at ASC,
                    id ASC
            )
            UPDATE taskforce_fleet_session AS fleet
            SET is_default = true
            FROM chosen
            WHERE fleet.id = chosen.id
            """
        )
    )
    # Keep the false server_default so DB-level inserts always populate the
    # column; the ORM still sets it explicitly via the model default.


def downgrade() -> None:
    op.drop_index(
        "ix_taskforce_fleet_session_is_default",
        table_name="taskforce_fleet_session",
    )
    op.drop_column("taskforce_fleet_session", "is_default")
