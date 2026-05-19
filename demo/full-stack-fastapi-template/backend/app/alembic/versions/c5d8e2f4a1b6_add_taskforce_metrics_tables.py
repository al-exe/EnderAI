"""add taskforce metrics tables

Creates the three tables that back the Taskforce Metrics engine
(model_pricing, metrics_event, metrics_daily_rollup) and seeds
model_pricing with the May 2026 Anthropic catalog. See
docs/taskforce-metrics-engine-plan.md.

Revision ID: c5d8e2f4a1b6
Revises: e9f1b2c3d4a5
Create Date: 2026-05-19 00:00:00.000000
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c5d8e2f4a1b6"
down_revision = "e9f1b2c3d4a5"
branch_labels = None
depends_on = None


SEED_EFFECTIVE_FROM = datetime(2026, 5, 19, tzinfo=timezone.utc)
ANTHROPIC_PRICING_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"

# (model_id, input, output, cache_read, cache_write_5m, cache_write_1h)
# All values in USD per million tokens, as of 2026-05-19.
ANTHROPIC_SEED: list[tuple[str, str, str, str, str, str]] = [
    ("claude-opus-4-7", "5.0000", "25.0000", "0.5000", "6.2500", "10.0000"),
    ("claude-opus-4-6", "5.0000", "25.0000", "0.5000", "6.2500", "10.0000"),
    ("claude-opus-4-5", "5.0000", "25.0000", "0.5000", "6.2500", "10.0000"),
    ("claude-opus-4-1", "15.0000", "75.0000", "1.5000", "18.7500", "30.0000"),
    ("claude-sonnet-4-6", "3.0000", "15.0000", "0.3000", "3.7500", "6.0000"),
    ("claude-sonnet-4-5", "3.0000", "15.0000", "0.3000", "3.7500", "6.0000"),
    ("claude-haiku-4-5", "1.0000", "5.0000", "0.1000", "1.2500", "2.0000"),
    ("claude-haiku-3-5", "0.8000", "4.0000", "0.0800", "1.0000", "1.6000"),
]


def upgrade() -> None:
    op.create_table(
        "model_pricing",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "currency",
            sa.String(length=8),
            nullable=False,
            server_default="USD",
        ),
        sa.Column("input_per_mtok", sa.Numeric(10, 4), nullable=False),
        sa.Column("output_per_mtok", sa.Numeric(10, 4), nullable=False),
        sa.Column("cache_read_per_mtok", sa.Numeric(10, 4), nullable=True),
        sa.Column("cache_write_5m_per_mtok", sa.Numeric(10, 4), nullable=True),
        sa.Column("cache_write_1h_per_mtok", sa.Numeric(10, 4), nullable=True),
        sa.Column("batch_discount", sa.Numeric(4, 3), nullable=True),
        sa.Column("source_url", sa.String(length=512), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_id",
            "effective_from",
            name="uq_model_pricing_model_effective_from",
        ),
    )
    op.create_index(
        "ix_model_pricing_provider",
        "model_pricing",
        ["provider"],
        unique=False,
    )
    op.create_index(
        "ix_model_pricing_model_id",
        "model_pricing",
        ["model_id"],
        unique=False,
    )
    op.create_index(
        "ix_model_pricing_effective_from",
        "model_pricing",
        ["effective_from"],
        unique=False,
    )

    op.create_table(
        "metrics_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=True),
        sa.Column("pricing_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=True),
        sa.Column("usd_amount", sa.Numeric(12, 6), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["v2_document.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["pricing_id"], ["model_pricing.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_metrics_event_occurred_at",
        "metrics_event",
        ["occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_metrics_event_user_id",
        "metrics_event",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_metrics_event_organization_id",
        "metrics_event",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_metrics_event_document_id",
        "metrics_event",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_metrics_event_kind",
        "metrics_event",
        ["kind"],
        unique=False,
    )
    op.create_index(
        "ix_metrics_event_is_demo",
        "metrics_event",
        ["is_demo"],
        unique=False,
    )
    op.create_index(
        "ix_metrics_event_user_occurred_at",
        "metrics_event",
        ["user_id", "occurred_at"],
        unique=False,
    )

    op.create_table(
        "metrics_daily_rollup",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metric_name", sa.String(length=64), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("value_num", sa.Numeric(20, 6), nullable=False),
        sa.Column("value_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("day", "user_id", "is_demo", "metric_name"),
    )
    op.create_index(
        "ix_metrics_daily_rollup_organization_id",
        "metrics_daily_rollup",
        ["organization_id"],
        unique=False,
    )

    # Seed model_pricing with the May 2026 Anthropic catalog. OpenAI / Gemini
    # are intentionally not seeded — per the plan's Open Question 3, we add
    # non-Claude rows when a real workflow needs them.
    model_pricing = sa.table(
        "model_pricing",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("provider", sa.String),
        sa.column("model_id", sa.String),
        sa.column("effective_from", sa.DateTime(timezone=True)),
        sa.column("effective_to", sa.DateTime(timezone=True)),
        sa.column("currency", sa.String),
        sa.column("input_per_mtok", sa.Numeric(10, 4)),
        sa.column("output_per_mtok", sa.Numeric(10, 4)),
        sa.column("cache_read_per_mtok", sa.Numeric(10, 4)),
        sa.column("cache_write_5m_per_mtok", sa.Numeric(10, 4)),
        sa.column("cache_write_1h_per_mtok", sa.Numeric(10, 4)),
        sa.column("batch_discount", sa.Numeric(4, 3)),
        sa.column("source_url", sa.String),
        sa.column("recorded_at", sa.DateTime(timezone=True)),
    )
    rows = [
        {
            "id": uuid.uuid4(),
            "provider": "anthropic",
            "model_id": model_id,
            "effective_from": SEED_EFFECTIVE_FROM,
            "effective_to": None,
            "currency": "USD",
            "input_per_mtok": Decimal(input_r),
            "output_per_mtok": Decimal(output_r),
            "cache_read_per_mtok": Decimal(cache_read),
            "cache_write_5m_per_mtok": Decimal(cache_5m),
            "cache_write_1h_per_mtok": Decimal(cache_1h),
            "batch_discount": Decimal("0.500"),
            "source_url": ANTHROPIC_PRICING_SOURCE,
            "recorded_at": SEED_EFFECTIVE_FROM,
        }
        for (
            model_id,
            input_r,
            output_r,
            cache_read,
            cache_5m,
            cache_1h,
        ) in ANTHROPIC_SEED
    ]
    op.bulk_insert(model_pricing, rows)


def downgrade() -> None:
    op.drop_index(
        "ix_metrics_daily_rollup_organization_id",
        table_name="metrics_daily_rollup",
    )
    op.drop_table("metrics_daily_rollup")

    op.drop_index("ix_metrics_event_user_occurred_at", table_name="metrics_event")
    op.drop_index("ix_metrics_event_is_demo", table_name="metrics_event")
    op.drop_index("ix_metrics_event_kind", table_name="metrics_event")
    op.drop_index("ix_metrics_event_document_id", table_name="metrics_event")
    op.drop_index("ix_metrics_event_organization_id", table_name="metrics_event")
    op.drop_index("ix_metrics_event_user_id", table_name="metrics_event")
    op.drop_index("ix_metrics_event_occurred_at", table_name="metrics_event")
    op.drop_table("metrics_event")

    op.drop_index("ix_model_pricing_effective_from", table_name="model_pricing")
    op.drop_index("ix_model_pricing_model_id", table_name="model_pricing")
    op.drop_index("ix_model_pricing_provider", table_name="model_pricing")
    op.drop_table("model_pricing")
