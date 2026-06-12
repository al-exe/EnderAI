"""Add Taskforce Fleet sessions.

Revision ID: 8c4f2a7d9e10
Revises: 9c3a7e1d5b24
Create Date: 2026-06-12 09:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "8c4f2a7d9e10"
down_revision = "9c3a7e1d5b24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "taskforce_fleet_session",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_taskforce_fleet_session_actor_id",
        "taskforce_fleet_session",
        ["actor_id"],
    )
    op.create_index(
        "ix_taskforce_fleet_session_organization_id",
        "taskforce_fleet_session",
        ["organization_id"],
    )
    op.add_column(
        "taskforce_session_archive",
        sa.Column(
            "fleet_session_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_taskforce_session_archive_fleet_session_id",
        "taskforce_session_archive",
        "taskforce_fleet_session",
        ["fleet_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_taskforce_session_archive_fleet_session_id",
        "taskforce_session_archive",
        ["fleet_session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_taskforce_session_archive_fleet_session_id",
        table_name="taskforce_session_archive",
    )
    op.drop_constraint(
        "fk_taskforce_session_archive_fleet_session_id",
        "taskforce_session_archive",
        type_="foreignkey",
    )
    op.drop_column("taskforce_session_archive", "fleet_session_id")
    op.drop_index(
        "ix_taskforce_fleet_session_organization_id",
        table_name="taskforce_fleet_session",
    )
    op.drop_index(
        "ix_taskforce_fleet_session_actor_id",
        table_name="taskforce_fleet_session",
    )
    op.drop_table("taskforce_fleet_session")
