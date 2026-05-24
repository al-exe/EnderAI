"""add agent specialist tables

Revision ID: f1a2b3c4d5e6
Revises: a3b7c1d9e2f4
Create Date: 2026-05-24 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "f1a2b3c4d5e6"
down_revision = "a3b7c1d9e2f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_specialist",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("role", sa.String(length=160), nullable=False),
        sa.Column("short_description", sa.String(length=240), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column(
            "domain_tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "routing_triggers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "negative_triggers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "instructions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_from", sa.String(length=32), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_agent_specialist_owner_id", "agent_specialist", ["owner_id"])
    op.create_index(
        "ix_agent_specialist_organization_id",
        "agent_specialist",
        ["organization_id"],
    )
    op.create_index("ix_agent_specialist_slug", "agent_specialist", ["slug"])
    op.create_index("ix_agent_specialist_status", "agent_specialist", ["status"])
    op.create_index(
        "ix_agent_specialist_visibility",
        "agent_specialist",
        ["visibility"],
    )
    op.create_index("ix_agent_specialist_is_demo", "agent_specialist", ["is_demo"])

    op.create_table(
        "agent_specialist_document_link",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("specialist_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("anchor_id", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.String(length=240), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["v2_document.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["specialist_id"],
            ["agent_specialist.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "specialist_id",
            "document_id",
            name="uq_agent_doc_link",
        ),
    )
    op.create_index(
        "ix_agent_specialist_document_link_specialist_id",
        "agent_specialist_document_link",
        ["specialist_id"],
    )
    op.create_index(
        "ix_agent_specialist_document_link_document_id",
        "agent_specialist_document_link",
        ["document_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_specialist_document_link_document_id",
        table_name="agent_specialist_document_link",
    )
    op.drop_index(
        "ix_agent_specialist_document_link_specialist_id",
        table_name="agent_specialist_document_link",
    )
    op.drop_table("agent_specialist_document_link")
    op.drop_index("ix_agent_specialist_is_demo", table_name="agent_specialist")
    op.drop_index("ix_agent_specialist_visibility", table_name="agent_specialist")
    op.drop_index("ix_agent_specialist_status", table_name="agent_specialist")
    op.drop_index("ix_agent_specialist_slug", table_name="agent_specialist")
    op.drop_index("ix_agent_specialist_organization_id", table_name="agent_specialist")
    op.drop_index("ix_agent_specialist_owner_id", table_name="agent_specialist")
    op.drop_table("agent_specialist")
