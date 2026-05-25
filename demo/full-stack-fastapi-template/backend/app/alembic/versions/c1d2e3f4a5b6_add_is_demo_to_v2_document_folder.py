"""add is_demo to v2_document_folder (TF-199)

Mirrors the is_demo column V2Document already has. Without it, folders
cannot be scoped to demo-mode users, so demo-mode Library views had to
hard-return empty lists. Now folders can be created, listed, renamed,
moved, and deleted in demo mode while staying fully isolated from live
content.

The column defaults to ``false`` so all existing folder rows belong to
the live scope (which is what they were before this migration, since
demo-mode folders weren't possible).

Revision ID: c1d2e3f4a5b6
Revises: f1a2b3c4d5e6
Create Date: 2026-05-24 23:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "v2_document_folder",
        sa.Column(
            "is_demo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_v2_document_folder_is_demo",
        "v2_document_folder",
        ["is_demo"],
    )


def downgrade() -> None:
    op.drop_index("ix_v2_document_folder_is_demo", table_name="v2_document_folder")
    op.drop_column("v2_document_folder", "is_demo")
