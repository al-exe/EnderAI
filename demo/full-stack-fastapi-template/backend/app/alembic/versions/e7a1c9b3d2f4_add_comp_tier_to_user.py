"""add comp_tier to user (new-user MAX promo)

Adds a nullable complimentary-tier grant column. It is set at signup by
the new-user promo (settings.NEW_USER_DEFAULT_TIER) and honored as a
floor over the Stripe-resolved tier in app.core.tiering.resolve_tier.
Nullable with no backfill: existing users keep NULL (no grant) and
continue to resolve purely from their Stripe state.

Revision ID: e7a1c9b3d2f4
Revises: 4d8e7f6a5b3c
Create Date: 2026-06-12 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e7a1c9b3d2f4"
down_revision = "4d8e7f6a5b3c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("comp_tier", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user", "comp_tier")
