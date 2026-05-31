"""add produced_by_client to v2_document

Revision ID: 0f4b9c8d7e6a
Revises: c1d2e3f4a5b6
Create Date: 2026-05-31 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0f4b9c8d7e6a"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "v2_document",
        sa.Column("produced_by_client", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("v2_document", "produced_by_client")
