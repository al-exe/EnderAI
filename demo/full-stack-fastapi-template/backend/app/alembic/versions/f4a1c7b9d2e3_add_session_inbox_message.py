"""Add Taskforce session inbox (reply-to-idle-agent queue).

Revision ID: f4a1c7b9d2e3
Revises: e3b9d1c2a4f7
Create Date: 2026-06-17 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f4a1c7b9d2e3"
down_revision = "e3b9d1c2a4f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "taskforce_session_inbox_message",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("body", sa.String(length=8000), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_taskforce_session_inbox_message_session_id",
        "taskforce_session_inbox_message",
        ["session_id"],
    )
    op.create_index(
        "ix_taskforce_session_inbox_message_actor_id",
        "taskforce_session_inbox_message",
        ["actor_id"],
    )
    op.create_index(
        "ix_taskforce_session_inbox_message_organization_id",
        "taskforce_session_inbox_message",
        ["organization_id"],
    )
    op.create_index(
        "ix_taskforce_session_inbox_message_is_demo",
        "taskforce_session_inbox_message",
        ["is_demo"],
    )
    op.create_index(
        "ix_taskforce_session_inbox_message_delivered_at",
        "taskforce_session_inbox_message",
        ["delivered_at"],
    )
    op.create_index(
        "ix_taskforce_session_inbox_message_created_at",
        "taskforce_session_inbox_message",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_taskforce_session_inbox_message_created_at",
        table_name="taskforce_session_inbox_message",
    )
    op.drop_index(
        "ix_taskforce_session_inbox_message_delivered_at",
        table_name="taskforce_session_inbox_message",
    )
    op.drop_index(
        "ix_taskforce_session_inbox_message_is_demo",
        table_name="taskforce_session_inbox_message",
    )
    op.drop_index(
        "ix_taskforce_session_inbox_message_organization_id",
        table_name="taskforce_session_inbox_message",
    )
    op.drop_index(
        "ix_taskforce_session_inbox_message_actor_id",
        table_name="taskforce_session_inbox_message",
    )
    op.drop_index(
        "ix_taskforce_session_inbox_message_session_id",
        table_name="taskforce_session_inbox_message",
    )
    op.drop_table("taskforce_session_inbox_message")
