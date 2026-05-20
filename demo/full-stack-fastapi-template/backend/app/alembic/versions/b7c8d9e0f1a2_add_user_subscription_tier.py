"""add user subscription tier

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-05-20 06:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b7c8d9e0f1a2"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "subscription_tier",
            sa.String(length=16),
            nullable=False,
            server_default="free",
        ),
    )
    op.create_index(
        op.f("ix_user_subscription_tier"),
        "user",
        ["subscription_tier"],
        unique=False,
    )
    op.execute(
        """
        UPDATE "user"
        SET subscription_tier = CASE
            WHEN is_superuser THEN 'admin'
            WHEN stripe_subscription_status IN ('active', 'trialing') THEN 'pro'
            ELSE 'free'
        END
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_subscription_tier"), table_name="user")
    op.drop_column("user", "subscription_tier")
