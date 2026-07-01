"""Add model_hint and permission_scope to agent_specialist (WS1a / TF-250).

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-07-01 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "i9j0k1l2m3n4"
down_revision = "h8i9j0k1l2m3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_specialist",
        sa.Column(
            "model_hint",
            sa.String(length=64),
            nullable=False,
            server_default="inherit",
        ),
    )
    op.add_column(
        "agent_specialist",
        sa.Column(
            "permission_scope",
            sa.String(length=16),
            nullable=False,
            server_default="readonly",
        ),
    )
    # Drop server defaults so future inserts rely on the model defaults.
    op.alter_column("agent_specialist", "model_hint", server_default=None)
    op.alter_column("agent_specialist", "permission_scope", server_default=None)


def downgrade() -> None:
    op.drop_column("agent_specialist", "permission_scope")
    op.drop_column("agent_specialist", "model_hint")
