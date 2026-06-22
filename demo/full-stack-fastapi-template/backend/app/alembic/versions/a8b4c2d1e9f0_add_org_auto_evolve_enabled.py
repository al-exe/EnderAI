"""Add org auto-evolve master switch (T7).

Revision ID: a8b4c2d1e9f0
Revises: f4a1c7b9d2e3
Create Date: 2026-06-22 05:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "a8b4c2d1e9f0"
down_revision = "f4a1c7b9d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organization",
        sa.Column(
            "auto_evolve_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.alter_column("organization", "auto_evolve_enabled", server_default=None)


def downgrade() -> None:
    op.drop_column("organization", "auto_evolve_enabled")
