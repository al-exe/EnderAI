"""Add workflow_bucket table

Revision ID: 8d7f9c3a1b2e
Revises: fe56fa70289e
Create Date: 2026-02-04 09:41:00.000000

"""

# revision identifiers, used by Alembic.
revision = "8d7f9c3a1b2e"
down_revision = "fe56fa70289e"
branch_labels = None
depends_on = None


def upgrade():
    # Legacy workflow_bucket creation was removed.
    # workflow_key now lives directly on canonical Topic records, so this revision
    # is kept as a no-op only to preserve Alembic history for existing databases.
    return None


def downgrade():
    return None
