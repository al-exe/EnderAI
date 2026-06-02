"""Add Taskforce session archive table.

Revision ID: 7b9c1d2e3f4a
Revises: 0f4b9c8d7e6a
Create Date: 2026-06-01 23:20:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "7b9c1d2e3f4a"
down_revision = "0f4b9c8d7e6a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "taskforce_session_archive",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("client", sa.String(length=32), nullable=True),
        sa.Column("specialist_slug", sa.String(length=64), nullable=True),
        sa.Column("harness_label", sa.String(length=64), nullable=True),
        sa.Column("harness_version", sa.String(length=64), nullable=True),
        sa.Column("model_id", sa.String(length=128), nullable=True),
        sa.Column("repo", sa.String(length=255), nullable=True),
        sa.Column("branch", sa.String(length=255), nullable=True),
        sa.Column("cwd", sa.String(length=1024), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("command_count", sa.Integer(), nullable=False),
        sa.Column("edit_count", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column(
            "referenced_document_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "transcript_events",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "raw_transcript",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["actor_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "is_demo",
            "session_id",
            name="uq_taskforce_session_archive_org_demo_session",
        ),
    )
    op.create_index(
        "ix_taskforce_session_archive_actor_id",
        "taskforce_session_archive",
        ["actor_id"],
    )
    op.create_index(
        "ix_taskforce_session_archive_ended_at",
        "taskforce_session_archive",
        ["ended_at"],
    )
    op.create_index(
        "ix_taskforce_session_archive_imported_at",
        "taskforce_session_archive",
        ["imported_at"],
    )
    op.create_index(
        "ix_taskforce_session_archive_is_demo",
        "taskforce_session_archive",
        ["is_demo"],
    )
    op.create_index(
        "ix_taskforce_session_archive_organization_id",
        "taskforce_session_archive",
        ["organization_id"],
    )
    op.create_index(
        "ix_taskforce_session_archive_session_id",
        "taskforce_session_archive",
        ["session_id"],
    )
    op.create_index(
        "ix_taskforce_session_archive_started_at",
        "taskforce_session_archive",
        ["started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_taskforce_session_archive_started_at",
        table_name="taskforce_session_archive",
    )
    op.drop_index(
        "ix_taskforce_session_archive_session_id",
        table_name="taskforce_session_archive",
    )
    op.drop_index(
        "ix_taskforce_session_archive_organization_id",
        table_name="taskforce_session_archive",
    )
    op.drop_index(
        "ix_taskforce_session_archive_is_demo",
        table_name="taskforce_session_archive",
    )
    op.drop_index(
        "ix_taskforce_session_archive_imported_at",
        table_name="taskforce_session_archive",
    )
    op.drop_index(
        "ix_taskforce_session_archive_ended_at",
        table_name="taskforce_session_archive",
    )
    op.drop_index(
        "ix_taskforce_session_archive_actor_id",
        table_name="taskforce_session_archive",
    )
    op.drop_table("taskforce_session_archive")
