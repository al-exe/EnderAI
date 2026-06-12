"""Add Taskforce Fleet sessions.

Revision ID: 8c4f2a7d9e10
Revises: 9c3a7e1d5b24
Create Date: 2026-06-12 09:00:00.000000
"""

import time

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError

revision = "8c4f2a7d9e10"
down_revision = "9c3a7e1d5b24"
branch_labels = None
depends_on = None


def _ddl_with_lock_retry(
    sql: str, *, attempts: int = 12, delay_seconds: float = 5.0
) -> None:
    """Run a DDL statement against taskforce_session_archive, retrying on lock
    timeout.

    taskforce_session_archive is written on every observe/discover call in
    prod, so even brief locks (ACCESS EXCLUSIVE for ADD COLUMN, SHARE ROW
    EXCLUSIVE for ADD CONSTRAINT) can queue behind a constant stream of
    overlapping writer transactions and never get a turn within a single
    lock_timeout window. Each attempt runs in its own autocommit transaction
    with a short lock_timeout, so a failed attempt doesn't poison the
    migration transaction and we get several chances to slot into a gap,
    while still bounding the total wait instead of hanging the deploy.
    """
    with op.get_context().autocommit_block():
        bind = op.get_bind()
        bind.execute(sa.text("SET lock_timeout = '2s'"))
        for attempt in range(1, attempts + 1):
            try:
                bind.execute(sa.text(sql))
                return
            except OperationalError as exc:
                if "lock timeout" not in str(exc).lower() or attempt == attempts:
                    raise
                time.sleep(delay_seconds)


def upgrade() -> None:
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
    _ddl_with_lock_retry(
        "ALTER TABLE taskforce_session_archive "
        "ADD COLUMN IF NOT EXISTS fleet_session_id UUID"
    )

    # ADD CONSTRAINT ... NOT VALID takes a brief lock with no validation scan;
    # VALIDATE CONSTRAINT then takes only SHARE UPDATE EXCLUSIVE, which
    # doesn't block concurrent reads/writes.
    _ddl_with_lock_retry(
        "ALTER TABLE taskforce_session_archive "
        "ADD CONSTRAINT fk_taskforce_session_archive_fleet_session_id "
        "FOREIGN KEY (fleet_session_id) REFERENCES taskforce_fleet_session(id) "
        "ON DELETE SET NULL NOT VALID"
    )
    _ddl_with_lock_retry(
        "ALTER TABLE taskforce_session_archive "
        "VALIDATE CONSTRAINT fk_taskforce_session_archive_fleet_session_id"
    )

    # CREATE INDEX CONCURRENTLY avoids the SHARE lock a plain CREATE INDEX
    # would hold against writers for the duration of the build.
    _ddl_with_lock_retry(
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
