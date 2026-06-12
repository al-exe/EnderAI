"""add rediscovery_cost_tokens to v2_document (TF-177)

Adds a cached "if you had to redo this investigation from scratch" token
estimate to v2_document. Powers the Phase 3 ``avoided_rediscovery``
metric: consultation savings = ``max(0, rediscovery_cost - summary_read)``.

The column defaults to 0 (cheap to add, no row-level locking concerns)
and the existing-row backfill recomputes the structural formula from
``main_body`` + ``details_markdown_sections``. Both columns are
recomputed on every doc mutation via
``refresh_v2_document_token_counts``.

Revision ID: a3b7c1d9e2f4
Revises: b2c3d4e5f6a7
Create Date: 2026-05-21 00:00:00.000000
"""

from types import SimpleNamespace

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a3b7c1d9e2f4"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "v2_document",
        sa.Column(
            "rediscovery_cost_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    # Backfill: recompute the structural formula for every existing row so
    # the metric is meaningful on day one rather than starting at zero.
    # Select only columns available at this revision. Importing/querying the
    # current V2Document model makes fresh installs fail when later columns
    # have been added to the model but not yet created by Alembic.
    from app.core.taskforce.rediscovery import compute_rediscovery_cost

    bind = op.get_bind()
    document_table = sa.table(
        "v2_document",
        sa.column("id"),
        sa.column("main_body"),
        sa.column("details_markdown_sections"),
        sa.column("rediscovery_cost_tokens"),
    )
    documents = bind.execute(
        sa.select(
            document_table.c.id,
            document_table.c.main_body,
            document_table.c.details_markdown_sections,
        )
    )
    for row in documents:
        document = SimpleNamespace(
            main_body=row.main_body or [],
            details_markdown_sections=row.details_markdown_sections or [],
        )
        bind.execute(
            document_table.update()
            .where(document_table.c.id == row.id)
            .values(rediscovery_cost_tokens=compute_rediscovery_cost(document))
        )


def downgrade() -> None:
    op.drop_column("v2_document", "rediscovery_cost_tokens")
