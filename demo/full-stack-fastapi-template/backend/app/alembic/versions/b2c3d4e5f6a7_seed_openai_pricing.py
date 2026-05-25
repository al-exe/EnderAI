"""seed openai pricing rows

Phase 1 of the Taskforce Metrics engine seeded only Anthropic models
(see ``c5d8e2f4a1b6_add_taskforce_metrics_tables.py``). Now that
BYOK OpenAI is shipping with Search and harness hooks may report
``model_id`` values like ``gpt-4o-mini`` or ``text-embedding-3-small``,
we need pricing rows for them — otherwise ``_price_usage()`` returns
``(None, $0)`` and the Metrics page silently underrepresents spend.

Numbers below reflect publicly-listed OpenAI pricing from the
chat-completions and embeddings pages. Operators should refresh the
``effective_to`` on these rows and add a new ``effective_from`` row
when OpenAI revises pricing.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-20 06:00:00.000000
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


SEED_EFFECTIVE_FROM = datetime(2026, 5, 20, tzinfo=timezone.utc)
OPENAI_PRICING_SOURCE = "https://platform.openai.com/docs/pricing"

# (model_id, input, output, cache_read, cache_write_5m, cache_write_1h, batch_discount)
# All values USD per million tokens. cache_read = 0.5 × input is the
# OpenAI prompt-cache discount. Embeddings have no output cost — we
# encode that as 0 so _price_usage() doesn't accidentally bill for
# phantom output tokens.
OPENAI_SEED: list[tuple[str, str, str, str | None, str | None, str | None, str]] = [
    # Chat / reasoning models
    ("gpt-4o", "2.5000", "10.0000", "1.2500", None, None, "0.500"),
    ("gpt-4o-mini", "0.1500", "0.6000", "0.0750", None, None, "0.500"),
    ("gpt-4.1", "2.0000", "8.0000", "0.5000", None, None, "0.500"),
    ("gpt-4.1-mini", "0.4000", "1.6000", "0.1000", None, None, "0.500"),
    ("gpt-4.1-nano", "0.1000", "0.4000", "0.0250", None, None, "0.500"),
    ("o3", "2.0000", "8.0000", "0.5000", None, None, "0.500"),
    ("o3-mini", "1.1000", "4.4000", "0.5500", None, None, "0.500"),
    ("o4-mini", "1.1000", "4.4000", "0.2750", None, None, "0.500"),
    # Embedding models — no output cost.
    ("text-embedding-3-small", "0.0200", "0.0000", None, None, None, "0.500"),
    ("text-embedding-3-large", "0.1300", "0.0000", None, None, None, "0.500"),
]


def upgrade() -> None:
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
            "provider": "openai",
            "model_id": model_id,
            "effective_from": SEED_EFFECTIVE_FROM,
            "effective_to": None,
            "currency": "USD",
            "input_per_mtok": Decimal(input_r),
            "output_per_mtok": Decimal(output_r),
            "cache_read_per_mtok": (
                Decimal(cache_read) if cache_read is not None else None
            ),
            "cache_write_5m_per_mtok": (
                Decimal(cache_5m) if cache_5m is not None else None
            ),
            "cache_write_1h_per_mtok": (
                Decimal(cache_1h) if cache_1h is not None else None
            ),
            "batch_discount": Decimal(batch),
            "source_url": OPENAI_PRICING_SOURCE,
            "recorded_at": SEED_EFFECTIVE_FROM,
        }
        for (
            model_id,
            input_r,
            output_r,
            cache_read,
            cache_5m,
            cache_1h,
            batch,
        ) in OPENAI_SEED
    ]
    op.bulk_insert(model_pricing, rows)


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM model_pricing "
            "WHERE provider = 'openai' AND effective_from = :ts"
        ).bindparams(ts=SEED_EFFECTIVE_FROM)
    )
