"""Initialize models

Revision ID: e2412789c190
Revises:
Create Date: 2023-11-24 22:55:43.195942

"""
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision = "e2412789c190"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user",
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("full_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "hashed_password", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_email"), "user", ["email"], unique=True)
    # The legacy item table was removed from the canonical backend model.
    # Keep this revision in place for Alembic history, but stop creating item on fresh installs.


def downgrade():
    op.execute("drop table if exists item")
    op.drop_index(op.f("ix_user_email"), table_name="user")
    op.drop_table("user")
