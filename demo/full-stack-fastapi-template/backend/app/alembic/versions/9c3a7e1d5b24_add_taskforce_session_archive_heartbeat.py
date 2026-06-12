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
    op.create_index(
        "ix_taskforce_session_archive_last_seen_at",
        "taskforce_session_archive",
        ["last_seen_at"],
    )
    op.create_index(
        "ix_taskforce_session_archive_active_document_id",
        "taskforce_session_archive",
        ["active_document_id"],
    )
    op.create_foreign_key(
        "fk_taskforce_session_archive_active_document_id",
        "taskforce_session_archive",
        "v2_document",
        ["active_document_id"],
        ["id"],
        ondelete="SET NULL",
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
