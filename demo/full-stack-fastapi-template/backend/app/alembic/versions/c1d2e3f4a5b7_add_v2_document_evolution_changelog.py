"""Add v2_document_evolution_changelog table (T2).

Revision ID: c1d2e3f4a5b7
Revises: b9c2d3e4f5a6
Create Date: 2026-06-22 07:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c1d2e3f4a5b7"
down_revision = "b9c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "v2_document_evolution_changelog",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_session_id", sa.String(length=128), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "summary_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "diff_or_section",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "revertable_to",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["actor_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["v2_document.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_v2_document_evolution_changelog_document_id",
        "v2_document_evolution_changelog",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_v2_document_evolution_changelog_source_session_id",
        "v2_document_evolution_changelog",
        ["source_session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_v2_document_evolution_changelog_source_session_id",
        table_name="v2_document_evolution_changelog",
    )
    op.drop_index(
        "ix_v2_document_evolution_changelog_document_id",
        table_name="v2_document_evolution_changelog",
    )
    op.drop_table("v2_document_evolution_changelog")
