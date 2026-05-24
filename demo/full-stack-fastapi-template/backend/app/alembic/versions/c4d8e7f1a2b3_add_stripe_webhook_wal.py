"""add stripe_webhook_event WAL table (TF-193, demo branch only)

DEMO BRANCH SCAFFOLDING — see DEMO_BRANCH.md at repo root.

Creates the `stripe_webhook_event` WAL backing
`record_stripe_event_or_skip` in `app/core/stripe_billing.py`. The
table is keyed on `(event_id, is_test_mode)` so test-mode replays
cannot collide with live fulfillment.

This migration must NEVER ship on main — the demo branch keeps it
isolated so the recorded fix has machinery to fix.

Revision ID: c4d8e7f1a2b3
Revises: a3b7c1d9e2f4
Create Date: 2026-05-24 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c4d8e7f1a2b3"
down_revision = "a3b7c1d9e2f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stripe_webhook_event",
        sa.Column("event_id", sa.String(length=128), primary_key=True),
        sa.Column(
            "is_test_mode",
            sa.Boolean(),
            primary_key=True,
            server_default=sa.false(),
        ),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("stripe_webhook_event")
