"""add v2 document favorites

Revision ID: 6a7b8c9d0e12
Revises: 5f6a7b8c9d01
Create Date: 2026-05-19 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "6a7b8c9d0e12"
down_revision = "5f6a7b8c9d01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "v2_document_favorite",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["v2_document.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "user_id",
            name="uq_v2_document_favorite_document_user",
        ),
    )
    op.create_index(
        "ix_v2_document_favorite_document_id",
        "v2_document_favorite",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_v2_document_favorite_user_id",
        "v2_document_favorite",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_v2_document_favorite_user_id",
        table_name="v2_document_favorite",
    )
    op.drop_index(
        "ix_v2_document_favorite_document_id",
        table_name="v2_document_favorite",
    )
    op.drop_table("v2_document_favorite")
