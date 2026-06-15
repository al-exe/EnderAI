"""Add Fleet History session bucket per actor.

Revision ID: a1f8c3e2d9b0
Revises: c7d2a9f4b6e1
Create Date: 2026-06-15 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "a1f8c3e2d9b0"
down_revision = "c7d2a9f4b6e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "taskforce_fleet_session",
        sa.Column(
            "is_history",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_taskforce_fleet_session_is_history",
        "taskforce_fleet_session",
        ["is_history"],
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            WITH actors_needing_history AS (
                SELECT DISTINCT
                    fleet.actor_id,
                    fleet.organization_id
                FROM taskforce_fleet_session AS fleet
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM taskforce_fleet_session AS existing
                    WHERE existing.actor_id = fleet.actor_id
                      AND existing.is_history = true
                )
            )
            INSERT INTO taskforce_fleet_session (
                id,
                actor_id,
                organization_id,
                name,
                is_history,
                created_at,
                updated_at
            )
            SELECT
                gen_random_uuid(),
                actor_id,
                organization_id,
                'History',
                true,
                now(),
                now()
            FROM actors_needing_history
            """
        )
    )

    bind.execute(
        sa.text(
            """
            UPDATE taskforce_session_archive AS archive
            SET fleet_session_id = history.id
            FROM taskforce_fleet_session AS history
            WHERE history.actor_id = archive.actor_id
              AND history.is_history = true
              AND (
                  archive.ended_at IS NOT NULL
                  OR archive.last_seen_at IS NULL
                  OR archive.last_seen_at < now() - interval '5 minutes'
              )
              AND (
                  archive.fleet_session_id IS NULL
                  OR archive.fleet_session_id <> history.id
              )
            """
        )
    )

    op.alter_column("taskforce_fleet_session", "is_history", server_default=None)


def downgrade() -> None:
    op.drop_index(
        "ix_taskforce_fleet_session_is_history",
        table_name="taskforce_fleet_session",
    )
    op.drop_column("taskforce_fleet_session", "is_history")
