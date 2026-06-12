"""Add last_seen_at heartbeat and active_document_id to taskforce_session_archive

Revision ID: 9c3a7e1d5b24
Revises: 7b9c1d2e3f4a
Create Date: 2026-06-12 09:00:00.000000
"""

import time

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import OperationalError

revision = "9c3a7e1d5b24"
down_revision = "7b9c1d2e3f4a"
branch_labels = None
depends_on = None


def _ddl_with_lock_retry(
    sql: str, *, attempts: int = 12, delay_seconds: float = 5.0
) -> None:
    """Run a DDL statement against taskforce_session_archive, retrying on lock
    timeout.

    taskforce_session_archive is written on every observe/discover call in
    prod, so even brief locks (ACCESS EXCLUSIVE for ADD COLUMN, SHARE ROW
    EXCLUSIVE for ADD CONSTRAINT) can queue behind a constant stream of
    overlapping writer transactions and never get a turn within a single
    lock_timeout window. Each attempt runs in its own autocommit transaction
    with a short lock_timeout, so a failed attempt doesn't poison the
    migration transaction and we get several chances to slot into a gap,
    while still bounding the total wait instead of hanging the deploy.
    """
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
        "ALTER TABLE taskforce_session_archive "
        "ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITH TIME ZONE"
    )
    _ddl_with_lock_retry(
        "ALTER TABLE taskforce_session_archive "
        "ADD COLUMN IF NOT EXISTS active_document_id UUID"
    )

    # ADD CONSTRAINT ... NOT VALID takes a brief lock with no validation scan;
    # VALIDATE CONSTRAINT then takes only SHARE UPDATE EXCLUSIVE, which
    # doesn't block concurrent reads/writes.
    _ddl_with_lock_retry(
        "ALTER TABLE taskforce_session_archive "
        "ADD CONSTRAINT fk_taskforce_session_archive_active_document_id "
        "FOREIGN KEY (active_document_id) REFERENCES v2_document(id) "
        "ON DELETE SET NULL NOT VALID"
    )
    _ddl_with_lock_retry(
        "ALTER TABLE taskforce_session_archive "
        "VALIDATE CONSTRAINT fk_taskforce_session_archive_active_document_id"
    )

    # CREATE INDEX CONCURRENTLY avoids the SHARE lock a plain CREATE INDEX
    # would hold against writers for the duration of the build.
    _ddl_with_lock_retry(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_taskforce_session_archive_last_seen_at "
        "ON taskforce_session_archive (last_seen_at)"
    )
    _ddl_with_lock_retry(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_taskforce_session_archive_active_document_id "
        "ON taskforce_session_archive (active_document_id)"
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_taskforce_session_archive_active_document_id",
        "taskforce_session_archive",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_taskforce_session_archive_active_document_id",
        table_name="taskforce_session_archive",
    )
    op.drop_index(
        "ix_taskforce_session_archive_last_seen_at",
        table_name="taskforce_session_archive",
    )
    op.drop_column("taskforce_session_archive", "active_document_id")
    op.drop_column("taskforce_session_archive", "last_seen_at")
