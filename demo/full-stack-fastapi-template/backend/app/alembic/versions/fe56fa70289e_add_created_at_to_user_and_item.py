"""Add created_at to User

Revision ID: fe56fa70289e
Revises: 1a31ce608336
Create Date: 2026-01-23 15:50:37.171462

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fe56fa70289e'
down_revision = '1a31ce608336'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('created_at', sa.DateTime(timezone=True), nullable=True))
    # The legacy item table no longer exists on fresh canonical installs.


def downgrade():
    op.drop_column('user', 'created_at')
