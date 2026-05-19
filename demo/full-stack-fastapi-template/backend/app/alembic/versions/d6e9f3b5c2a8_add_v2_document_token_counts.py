"""add summary_tokens / details_tokens to v2_document

Adds two cheap-to-read integer columns to v2_document so the metrics
engine's reuse-on-begin savings source (plan §2.2) can estimate
bootstrap_tokens per reused doc without re-tokenizing on every read.
Both columns default to 0 and are recomputed on V2Document create/update.

Revision ID: d6e9f3b5c2a8
Revises: c5d8e2f4a1b6
Create Date: 2026-05-19 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d6e9f3b5c2a8"
down_revision = "c5d8e2f4a1b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "v2_document",
        sa.Column(
            "summary_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "v2_document",
        sa.Column(
            "details_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("v2_document", "details_tokens")
    op.drop_column("v2_document", "summary_tokens")
