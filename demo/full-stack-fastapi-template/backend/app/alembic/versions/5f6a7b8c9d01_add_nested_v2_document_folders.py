"""add nested v2 document folders

Revision ID: 5f6a7b8c9d01
Revises: b38f7a4a9d2c
Create Date: 2026-05-19 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "5f6a7b8c9d01"
down_revision = "b38f7a4a9d2c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "v2_document_folder",
        sa.Column("parent_folder_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_v2_document_folder_parent_folder_id",
        "v2_document_folder",
        ["parent_folder_id"],
        unique=False,
    )
    op.create_foreign_key(
        "v2_document_folder_parent_folder_id_fkey",
        "v2_document_folder",
        "v2_document_folder",
        ["parent_folder_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "v2_document_folder_parent_folder_id_fkey",
        "v2_document_folder",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_v2_document_folder_parent_folder_id",
        table_name="v2_document_folder",
    )
    op.drop_column("v2_document_folder", "parent_folder_id")
