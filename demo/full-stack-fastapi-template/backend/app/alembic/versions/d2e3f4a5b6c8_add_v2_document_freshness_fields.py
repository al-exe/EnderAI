"""Add evolution freshness fields on v2_document (T3).

Revision ID: d2e3f4a5b6c8
Revises: c1d2e3f4a5b7
Create Date: 2026-06-22 08:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "d2e3f4a5b6c8"
down_revision = "c1d2e3f4a5b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "v2_document",
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "v2_document",
        sa.Column(
            "evolution_stale",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_v2_document_evolution_stale",
        "v2_document",
        ["evolution_stale"],
        unique=False,
    )
    op.alter_column("v2_document", "evolution_stale", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_v2_document_evolution_stale", table_name="v2_document")
    op.drop_column("v2_document", "evolution_stale")
    op.drop_column("v2_document", "last_verified_at")
