"""Add last_seen_at heartbeat and active_document_id to taskforce_session_archive

Revision ID: 9c3a7e1d5b24
Revises: 7b9c1d2e3f4a
Create Date: 2026-06-12 09:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "9c3a7e1d5b24"
down_revision = "7b9c1d2e3f4a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # taskforce_session_archive is written on every observe/discover call in
    # prod. Bound how long we'll wait for locks so a busy table fails fast
    # with a clear error instead of hanging the deploy until Render's
    # port-scan times out.
    op.execute("SET lock_timeout = '5s'")

    op.add_column(
        "taskforce_session_archive",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "taskforce_session_archive",
        sa.Column(
            "active_document_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )

    # ADD CONSTRAINT ... NOT VALID takes a brief ACCESS EXCLUSIVE lock with no
    # validation scan; VALIDATE CONSTRAINT then takes only SHARE UPDATE
    # EXCLUSIVE, which doesn't block concurrent reads/writes. This avoids
    # holding a long SHARE ROW EXCLUSIVE lock on the live table.
    op.execute(
        "ALTER TABLE taskforce_session_archive "
        "ADD CONSTRAINT fk_taskforce_session_archive_active_document_id "
        "FOREIGN KEY (active_document_id) REFERENCES v2_document(id) "
        "ON DELETE SET NULL NOT VALID"
    )
    op.execute(
        "ALTER TABLE taskforce_session_archive "
        "VALIDATE CONSTRAINT fk_taskforce_session_archive_active_document_id"
    )

    # CREATE INDEX CONCURRENTLY can't run inside a transaction, and avoids the
    # SHARE lock a plain CREATE INDEX would hold against writers for the
    # duration of the build.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_taskforce_session_archive_last_seen_at "
            "ON taskforce_session_archive (last_seen_at)"
        )
        op.execute(
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
