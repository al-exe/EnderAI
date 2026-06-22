"""Add auto-evolution provenance fields to v2_document (T1).

Revision ID: b9c2d3e4f5a6
Revises: a8b4c2d1e9f0
Create Date: 2026-06-22 06:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b9c2d3e4f5a6"
down_revision = "a8b4c2d1e9f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "v2_document",
        sa.Column(
            "auto_created",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "v2_document",
        sa.Column("evolution_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "v2_document",
        sa.Column(
            "evolution_provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_v2_document_auto_created",
        "v2_document",
        ["auto_created"],
        unique=False,
    )
    op.alter_column("v2_document", "auto_created", server_default=None)
    op.alter_column("v2_document", "evolution_provenance", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_v2_document_auto_created", table_name="v2_document")
    op.drop_column("v2_document", "evolution_provenance")
    op.drop_column("v2_document", "evolution_confidence")
    op.drop_column("v2_document", "auto_created")
