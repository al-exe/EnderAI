"""Add Fleet document scope and backfill default sessions.

Revision ID: 4d8e7f6a5b3c
Revises: 8c4f2a7d9e10
Create Date: 2026-06-12 12:30:00.000000
"""

import time

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import OperationalError

revision = "4d8e7f6a5b3c"
down_revision = "8c4f2a7d9e10"
branch_labels = None
depends_on = None


def _ddl_with_lock_retry(
    sql: str, *, attempts: int = 12, delay_seconds: float = 5.0
) -> None:
    with op.get_context().autocommit_block():
        bind = op.get_bind()
        bind.execute(sa.text("SET lock_timeout = '2s'"))
        for attempt in range(1, attempts + 1):
            try:
                bind.execute(sa.text(sql))
                return
            except OperationalError as exc:
                if "lock timeout" not in str(exc).lower() or attempt == attempts:
                    raise
                time.sleep(delay_seconds)


def upgrade() -> None:
    _ddl_with_lock_retry(
        "ALTER TABLE v2_document ADD COLUMN IF NOT EXISTS fleet_session_id UUID"
    )
    _ddl_with_lock_retry(
        "ALTER TABLE v2_document "
        "ADD CONSTRAINT fk_v2_document_fleet_session_id "
        "FOREIGN KEY (fleet_session_id) REFERENCES taskforce_fleet_session(id) "
        "ON DELETE SET NULL NOT VALID"
    )
    _ddl_with_lock_retry(
        "ALTER TABLE v2_document VALIDATE CONSTRAINT fk_v2_document_fleet_session_id"
    )
    _ddl_with_lock_retry(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_v2_document_fleet_session_id "
        "ON v2_document (fleet_session_id)"
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            WITH actors_needing_default AS (
                SELECT DISTINCT ON (archive.actor_id)
                    archive.actor_id,
                    archive.organization_id
                FROM taskforce_session_archive AS archive
                WHERE archive.fleet_session_id IS NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM taskforce_fleet_session AS existing
                      WHERE existing.actor_id = archive.actor_id
                        AND existing.name = 'Session 1'
                  )
                ORDER BY
                    archive.actor_id,
                    archive.created_at NULLS LAST,
                    archive.id
            )
            INSERT INTO taskforce_fleet_session (
                id,
                actor_id,
                organization_id,
                name,
                created_at,
                updated_at
            )
            SELECT
                gen_random_uuid(),
                actor_id,
                organization_id,
                'Session 1',
                now(),
                now()
            FROM actors_needing_default
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE taskforce_session_archive AS archive
            SET fleet_session_id = (
                SELECT fleet.id
                FROM taskforce_fleet_session AS fleet
                WHERE fleet.actor_id = archive.actor_id
                ORDER BY
                    CASE WHEN fleet.name = 'Session 1' THEN 0 ELSE 1 END,
                    fleet.created_at,
                    fleet.id
                LIMIT 1
            )
            WHERE archive.fleet_session_id IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_v2_document_fleet_session_id",
        table_name="v2_document",
    )
    op.drop_constraint(
        "fk_v2_document_fleet_session_id",
        "v2_document",
        type_="foreignkey",
    )
    op.drop_column("v2_document", "fleet_session_id")
