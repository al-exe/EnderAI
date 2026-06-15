"""Add Taskforce session activity timeline (TF-247).

Revision ID: c7d2a9f4b6e1
Revises: e7a1c9b3d2f4
Create Date: 2026-06-14 23:30:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c7d2a9f4b6e1"
down_revision = "e7a1c9b3d2f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Brand-new table: plain create_table is safe — no concurrent writers to
    # lock against (unlike the ALTERs on taskforce_session_archive that need
    # the online-DDL retry dance in 8c4f2a7d9e10).
    op.create_table(
        "taskforce_session_activity",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fleet_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("prompt", sa.String(length=255), nullable=False),
        sa.Column("response_summary", sa.String(length=2000), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["fleet_session_id"],
            ["taskforce_fleet_session.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_taskforce_session_activity_session_id",
        "taskforce_session_activity",
        ["session_id"],
    )
    op.create_index(
        "ix_taskforce_session_activity_actor_id",
        "taskforce_session_activity",
        ["actor_id"],
    )
    op.create_index(
        "ix_taskforce_session_activity_organization_id",
        "taskforce_session_activity",
        ["organization_id"],
    )
    op.create_index(
        "ix_taskforce_session_activity_fleet_session_id",
        "taskforce_session_activity",
        ["fleet_session_id"],
    )
    op.create_index(
        "ix_taskforce_session_activity_is_demo",
        "taskforce_session_activity",
        ["is_demo"],
    )
    op.create_index(
        "ix_taskforce_session_activity_occurred_at",
        "taskforce_session_activity",
        ["occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_taskforce_session_activity_occurred_at",
        table_name="taskforce_session_activity",
    )
    op.drop_index(
        "ix_taskforce_session_activity_is_demo",
        table_name="taskforce_session_activity",
    )
    op.drop_index(
        "ix_taskforce_session_activity_fleet_session_id",
        table_name="taskforce_session_activity",
    )
    op.drop_index(
        "ix_taskforce_session_activity_organization_id",
        table_name="taskforce_session_activity",
    )
    op.drop_index(
        "ix_taskforce_session_activity_actor_id",
        table_name="taskforce_session_activity",
    )
    op.drop_index(
        "ix_taskforce_session_activity_session_id",
        table_name="taskforce_session_activity",
    )
    op.drop_table("taskforce_session_activity")
