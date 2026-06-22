"""Add evolution_provenance to agent_specialist (T4).

Revision ID: e3f4a5b6c7d9
Revises: d2e3f4a5b6c8
Create Date: 2026-06-22 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e3f4a5b6c7d9"
down_revision = "d2e3f4a5b6c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_specialist",
        sa.Column(
            "evolution_provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("agent_specialist", "evolution_provenance", server_default=None)


def downgrade() -> None:
    op.drop_column("agent_specialist", "evolution_provenance")
