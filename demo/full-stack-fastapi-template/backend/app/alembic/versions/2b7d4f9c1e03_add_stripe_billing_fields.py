"""add stripe billing fields

Revision ID: 2b7d4f9c1e03
Revises: 4c7b1a8f0d2e
Create Date: 2026-05-14 05:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2b7d4f9c1e03"
down_revision = "4c7b1a8f0d2e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "user",
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "user",
        sa.Column("stripe_subscription_status", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "user",
        sa.Column(
            "stripe_subscription_current_period_end",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "user",
        sa.Column(
            "stripe_subscription_cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "user",
        sa.Column("stripe_price_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_user_stripe_customer_id"),
        "user",
        ["stripe_customer_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_user_stripe_subscription_id"),
        "user",
        ["stripe_subscription_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_user_stripe_subscription_status"),
        "user",
        ["stripe_subscription_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_stripe_subscription_status"), table_name="user")
    op.drop_index(op.f("ix_user_stripe_subscription_id"), table_name="user")
    op.drop_index(op.f("ix_user_stripe_customer_id"), table_name="user")
    op.drop_column("user", "stripe_price_id")
    op.drop_column("user", "stripe_subscription_cancel_at_period_end")
    op.drop_column("user", "stripe_subscription_current_period_end")
    op.drop_column("user", "stripe_subscription_status")
    op.drop_column("user", "stripe_subscription_id")
    op.drop_column("user", "stripe_customer_id")
