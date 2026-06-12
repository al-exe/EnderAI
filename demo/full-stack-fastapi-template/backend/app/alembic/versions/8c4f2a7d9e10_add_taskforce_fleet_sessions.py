"""Add Taskforce Fleet sessions.

Revision ID: 8c4f2a7d9e10
Revises: 9c3a7e1d5b24
Create Date: 2026-06-12 09:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "8c4f2a7d9e10"
down_revision = "9c3a7e1d5b24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # taskforce_session_archive is written on every observe/discover call in
    # prod. Bound how long we'll wait for locks so a busy table fails fast
    # with a clear error instead of hanging the deploy until Render's
    # port-scan times out.
    op.execute("SET lock_timeout = '5s'")

    op.create_table(
        "taskforce_fleet_session",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_taskforce_fleet_session_actor_id",
        "taskforce_fleet_session",
        ["actor_id"],
    )
    op.create_index(
        "ix_taskforce_fleet_session_organization_id",
        "taskforce_fleet_session",
        ["organization_id"],
    )
    op.add_column(
        "taskforce_session_archive",
        sa.Column(
            "fleet_session_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    # ADD CONSTRAINT ... NOT VALID takes a brief ACCESS EXCLUSIVE lock with no
    # validation scan; VALIDATE CONSTRAINT then takes only SHARE UPDATE
    # EXCLUSIVE, which doesn't block concurrent reads/writes. This avoids
    # holding a long SHARE ROW EXCLUSIVE lock on the live table.
    op.execute(
        "ALTER TABLE taskforce_session_archive "
        "ADD CONSTRAINT fk_taskforce_session_archive_fleet_session_id "
        "FOREIGN KEY (fleet_session_id) REFERENCES taskforce_fleet_session(id) "
        "ON DELETE SET NULL NOT VALID"
    )
    op.execute(
        "ALTER TABLE taskforce_session_archive "
        "VALIDATE CONSTRAINT fk_taskforce_session_archive_fleet_session_id"
    )

    # CREATE INDEX CONCURRENTLY can't run inside a transaction, and avoids the
    # SHARE lock a plain CREATE INDEX would hold against writers for the
    # duration of the build.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_taskforce_session_archive_fleet_session_id "
            "ON taskforce_session_archive (fleet_session_id)"
        )


def downgrade() -> None:
    op.drop_index(
        "ix_taskforce_session_archive_fleet_session_id",
        table_name="taskforce_session_archive",
    )
    op.drop_constraint(
        "fk_taskforce_session_archive_fleet_session_id",
        "taskforce_session_archive",
        type_="foreignkey",
    )
    op.drop_column("taskforce_session_archive", "fleet_session_id")
    op.drop_index(
        "ix_taskforce_fleet_session_organization_id",
        table_name="taskforce_fleet_session",
    )
    op.drop_index(
        "ix_taskforce_fleet_session_actor_id",
        table_name="taskforce_fleet_session",
    )
    op.drop_table("taskforce_fleet_session")
