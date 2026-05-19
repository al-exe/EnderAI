"""add v2 document folders and member shares

Revision ID: e9f1b2c3d4a5
Revises: d4a9c8b7e6f5
Create Date: 2026-05-19 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "e9f1b2c3d4a5"
down_revision = "d4a9c8b7e6f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "v2_document_folder",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "visibility",
            sa.String(length=16),
            nullable=False,
            server_default="private",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_v2_document_folder_owner_id",
        "v2_document_folder",
        ["owner_id"],
        unique=False,
    )
    op.create_index(
        "ix_v2_document_folder_organization_id",
        "v2_document_folder",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_v2_document_folder_name",
        "v2_document_folder",
        ["name"],
        unique=False,
    )
    op.create_index(
        "ix_v2_document_folder_visibility",
        "v2_document_folder",
        ["visibility"],
        unique=False,
    )

    op.add_column(
        "v2_document",
        sa.Column("folder_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_v2_document_folder_id",
        "v2_document",
        ["folder_id"],
        unique=False,
    )
    op.create_foreign_key(
        "v2_document_folder_id_fkey",
        "v2_document",
        "v2_document_folder",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "v2_document_share",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "permission",
            sa.String(length=16),
            nullable=False,
            server_default="editor",
        ),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["v2_document.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["user.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "user_id",
            name="uq_v2_document_share_document_user",
        ),
    )
    op.create_index(
        "ix_v2_document_share_document_id",
        "v2_document_share",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_v2_document_share_user_id",
        "v2_document_share",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_v2_document_share_permission",
        "v2_document_share",
        ["permission"],
        unique=False,
    )
    op.create_index(
        "ix_v2_document_share_created_by_user_id",
        "v2_document_share",
        ["created_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_v2_document_share_created_by_user_id",
        table_name="v2_document_share",
    )
    op.drop_index("ix_v2_document_share_permission", table_name="v2_document_share")
    op.drop_index("ix_v2_document_share_user_id", table_name="v2_document_share")
    op.drop_index("ix_v2_document_share_document_id", table_name="v2_document_share")
    op.drop_table("v2_document_share")

    op.drop_constraint("v2_document_folder_id_fkey", "v2_document", type_="foreignkey")
    op.drop_index("ix_v2_document_folder_id", table_name="v2_document")
    op.drop_column("v2_document", "folder_id")

    op.drop_index("ix_v2_document_folder_visibility", table_name="v2_document_folder")
    op.drop_index("ix_v2_document_folder_name", table_name="v2_document_folder")
    op.drop_index(
        "ix_v2_document_folder_organization_id",
        table_name="v2_document_folder",
    )
    op.drop_index("ix_v2_document_folder_owner_id", table_name="v2_document_folder")
    op.drop_table("v2_document_folder")
