"""add firebase auth fields

Revision ID: af2b3c4d5e6f
Revises: 7e4f1b9a0c2d
Create Date: 2026-05-16 21:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "af2b3c4d5e6f"
down_revision = "7e4f1b9a0c2d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("firebase_uid", sa.String(length=128), nullable=True))
    op.alter_column(
        "user",
        "hashed_password",
        existing_type=sa.String(),
        nullable=True,
    )
    op.create_index(
        op.f("ix_user_firebase_uid"),
        "user",
        ["firebase_uid"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_firebase_uid"), table_name="user")
    op.drop_column("user", "firebase_uid")
    op.execute('UPDATE "user" SET hashed_password = \'\' WHERE hashed_password IS NULL')
    op.alter_column(
        "user",
        "hashed_password",
        existing_type=sa.String(),
        nullable=False,
    )
