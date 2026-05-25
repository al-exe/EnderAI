"""add organizations and v2 document visibility

Revision ID: d4a9c8b7e6f5
Revises: b8e5d4a91207
Create Date: 2026-05-18 00:00:00.000000
"""

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "d4a9c8b7e6f5"
down_revision = "b8e5d4a91207"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(
        "ix_organization_name", "organization", ["name"], unique=True
    )

    op.add_column(
        "user",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_user_organization_id", "user", ["organization_id"], unique=False
    )
    op.create_foreign_key(
        "user_organization_id_fkey",
        "user",
        "organization",
        ["organization_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "user",
        sa.Column(
            "organization_role",
            sa.String(length=16),
            nullable=False,
            server_default="admin",
        ),
    )
    op.create_index(
        "ix_user_organization_role", "user", ["organization_role"], unique=False
    )

    bind = op.get_bind()
    existing_users = bind.execute(
        sa.text('SELECT id, email, full_name FROM "user" WHERE organization_id IS NULL')
    ).mappings()
    now = datetime.now(timezone.utc)
    for user in existing_users:
        organization_id = uuid.uuid4()
        label = user["full_name"] or user["email"]
        bind.execute(
            sa.text(
                """
                INSERT INTO organization (id, name, created_at, updated_at)
                VALUES (:id, :name, :created_at, :updated_at)
                """
            ),
            {
                "id": organization_id,
                "name": f"{label}'s Organization ({str(user['id'])[:8]})",
                "created_at": now,
                "updated_at": now,
            },
        )
        bind.execute(
            sa.text(
                """
                UPDATE "user"
                SET organization_id = :organization_id, organization_role = 'admin'
                WHERE id = :user_id
                """
            ),
            {"organization_id": organization_id, "user_id": user["id"]},
        )

    op.create_table(
        "organization_invitation",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invited_email", sa.String(length=255), nullable=False),
        sa.Column("invited_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"], ["user.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_organization_invitation_organization_id",
        "organization_invitation",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_organization_invitation_invited_by_user_id",
        "organization_invitation",
        ["invited_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_organization_invitation_invited_email",
        "organization_invitation",
        ["invited_email"],
        unique=False,
    )

    op.add_column(
        "v2_document",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "v2_document",
        sa.Column(
            "visibility",
            sa.String(length=12),
            nullable=False,
            server_default="private",
        ),
    )
    op.create_index(
        "ix_v2_document_organization_id",
        "v2_document",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_v2_document_visibility",
        "v2_document",
        ["visibility"],
        unique=False,
    )
    op.create_foreign_key(
        "v2_document_organization_id_fkey",
        "v2_document",
        "organization",
        ["organization_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "v2_document_organization_id_fkey", "v2_document", type_="foreignkey"
    )
    op.drop_index("ix_v2_document_visibility", table_name="v2_document")
    op.drop_index("ix_v2_document_organization_id", table_name="v2_document")
    op.drop_column("v2_document", "visibility")
    op.drop_column("v2_document", "organization_id")

    op.drop_constraint("user_organization_id_fkey", "user", type_="foreignkey")
    op.drop_index(
        "ix_organization_invitation_invited_email",
        table_name="organization_invitation",
    )
    op.drop_index(
        "ix_organization_invitation_invited_by_user_id",
        table_name="organization_invitation",
    )
    op.drop_index(
        "ix_organization_invitation_organization_id",
        table_name="organization_invitation",
    )
    op.drop_table("organization_invitation")
    op.drop_index("ix_user_organization_role", table_name="user")
    op.drop_column("user", "organization_role")
    op.drop_index("ix_user_organization_id", table_name="user")
    op.drop_column("user", "organization_id")

    op.drop_index("ix_organization_name", table_name="organization")
    op.drop_table("organization")
