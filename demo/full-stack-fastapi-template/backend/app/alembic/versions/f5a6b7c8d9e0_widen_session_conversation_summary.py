"""Widen session conversation_summary for full-sentence roster labels.

Revision ID: f5a6b7c8d9e0
Revises: e3f4a5b6c7d9
Create Date: 2026-06-24 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "f5a6b7c8d9e0"
down_revision = "e3f4a5b6c7d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "taskforce_session_archive",
        "conversation_summary",
        existing_type=sa.String(length=120),
        type_=sa.String(length=255),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "taskforce_session_archive",
        "conversation_summary",
        existing_type=sa.String(length=255),
        type_=sa.String(length=120),
        existing_nullable=True,
    )
