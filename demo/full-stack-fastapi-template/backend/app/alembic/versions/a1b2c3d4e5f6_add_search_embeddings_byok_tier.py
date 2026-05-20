"""add search embeddings, byok credentials, document indexing columns

Phase 1 of the Taskforce V2 Search feature. Creates pgvector extension,
the `source_item_embedding` table that backs hybrid retrieval, the
`byok_credential` table that stores Pro-tier users' encrypted API keys,
and adds `last_indexed_at` + `index_version` drift columns to
`v2_document` so the cron-sweep indexer can find work.

See /home/alexlee/.claude/plans/parsed-dancing-tide.md for the full plan.

Revision ID: a1b2c3d4e5f6
Revises: 6a7b8c9d0e12
Create Date: 2026-05-19 17:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "6a7b8c9d0e12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector extension. Idempotent — safe on re-run.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ---------- source_item_embedding ---------------------------------
    op.create_table(
        "source_item_embedding",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_item_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_anchor_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column(
            "is_demo", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("version_hash", sa.String(length=64), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_kind",
            "source_item_id",
            "chunk_anchor_id",
            name="uq_source_item_embedding_anchor",
        ),
    )
    op.create_index(
        "ix_source_item_embedding_owner",
        "source_item_embedding",
        ["owner_id", "is_demo"],
        unique=False,
    )
    op.create_index(
        "ix_source_item_embedding_org",
        "source_item_embedding",
        ["organization_id", "is_demo"],
        unique=False,
        postgresql_where=sa.text("visibility = 'organization'"),
    )
    op.create_index(
        "ix_source_item_embedding_source_item",
        "source_item_embedding",
        ["source_kind", "source_item_id"],
        unique=False,
    )
    # IVFFlat index for cosine-distance ANN. `lists = 100` is the
    # canonical starter — tune after we have real corpus size.
    op.execute(
        "CREATE INDEX ix_source_item_embedding_vec "
        "ON source_item_embedding USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )

    # ---------- byok_credential ---------------------------------------
    op.create_table(
        "byok_credential",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("encrypted_api_key", sa.LargeBinary(), nullable=False),
        sa.Column("key_fingerprint", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "provider", name="uq_byok_credential_user_provider"
        ),
    )
    op.create_index(
        "ix_byok_credential_user_id",
        "byok_credential",
        ["user_id"],
        unique=False,
    )

    # ---------- v2_document drift columns -----------------------------
    op.add_column(
        "v2_document",
        sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "v2_document",
        sa.Column("index_version", sa.String(length=16), nullable=True),
    )
    # Partial index — only the docs that need indexing live in here, so
    # the cron-sweep's "find drift" query is effectively scanning a tiny
    # working set instead of the whole table.
    op.create_index(
        "ix_v2_document_index_drift",
        "v2_document",
        ["updated_at"],
        unique=False,
        postgresql_where=sa.text(
            "last_indexed_at IS NULL OR last_indexed_at < updated_at"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_v2_document_index_drift", table_name="v2_document")
    op.drop_column("v2_document", "index_version")
    op.drop_column("v2_document", "last_indexed_at")

    op.drop_index("ix_byok_credential_user_id", table_name="byok_credential")
    op.drop_table("byok_credential")

    op.execute("DROP INDEX IF EXISTS ix_source_item_embedding_vec")
    op.drop_index(
        "ix_source_item_embedding_source_item", table_name="source_item_embedding"
    )
    op.drop_index("ix_source_item_embedding_org", table_name="source_item_embedding")
    op.drop_index(
        "ix_source_item_embedding_owner", table_name="source_item_embedding"
    )
    op.drop_table("source_item_embedding")
    # Intentionally NOT dropping the vector extension — other migrations
    # or data might depend on it. Operator can drop it manually if needed.
