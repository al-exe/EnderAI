"""Unify Fleet activity and Ledger transcripts into session events.

Revision ID: f6a1b2c3d4e5
Revises: b4e8f1a2c3d4
Create Date: 2026-06-15 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f6a1b2c3d4e5"
down_revision = "b4e8f1a2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "taskforce_session_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fleet_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("source_event_id", sa.String(length=255), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("who", sa.String(length=120), nullable=True),
        sa.Column("text", sa.String(length=4000), nullable=True),
        sa.Column("cmd", sa.String(length=2000), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("output", sa.String(length=4000), nullable=True),
        sa.Column("file", sa.String(length=1024), nullable=True),
        sa.Column("added", sa.Integer(), nullable=True),
        sa.Column("removed", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(length=4000), nullable=True),
        sa.Column("repo", sa.String(length=255), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["fleet_session_id"],
            ["taskforce_fleet_session.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_id",
            "is_demo",
            "session_id",
            "source_event_id",
            name="uq_taskforce_session_event_source",
        ),
    )
    for column in (
        "session_id",
        "actor_id",
        "organization_id",
        "fleet_session_id",
        "is_demo",
        "kind",
        "occurred_at",
    ):
        op.create_index(
            f"ix_taskforce_session_event_{column}",
            "taskforce_session_event",
            [column],
        )

    # Preserve the accurate prompt timestamps captured by /discover.
    op.execute(
        """
        INSERT INTO taskforce_session_event (
            id, session_id, actor_id, organization_id, fleet_session_id,
            is_demo, source_event_id, source_order, kind, role, who, text,
            occurred_at, created_at
        )
        SELECT
            id, session_id, actor_id, organization_id, fleet_session_id,
            is_demo, 'legacy-activity:' || id::text, 0, 'prompt', 'user', '@user',
            prompt, occurred_at, created_at
        FROM taskforce_session_activity
        """
    )

    # Add actual transcript/command/edit content from Ledger, skipping prompt
    # copies already represented by the more accurately timed activity rows.
    op.execute(
        """
        INSERT INTO taskforce_session_event (
            id, session_id, actor_id, organization_id, fleet_session_id,
            is_demo, source_event_id, source_order, kind, role, who, text, cmd, exit_code,
            output, file, added, removed, note, repo, occurred_at, created_at
        )
        SELECT
            (
                substr(md5(a.id::text || ':' || e.ordinality::text), 1, 8) || '-' ||
                substr(md5(a.id::text || ':' || e.ordinality::text), 9, 4) || '-' ||
                substr(md5(a.id::text || ':' || e.ordinality::text), 13, 4) || '-' ||
                substr(md5(a.id::text || ':' || e.ordinality::text), 17, 4) || '-' ||
                substr(md5(a.id::text || ':' || e.ordinality::text), 21, 12)
            )::uuid,
            a.session_id,
            a.actor_id,
            a.organization_id,
            a.fleet_session_id,
            a.is_demo,
            'legacy-archive:' || a.id::text || ':' || e.ordinality::text,
            e.ordinality - 1,
            e.value->>'kind',
            e.value->>'role',
            e.value->>'who',
            e.value->>'text',
            e.value->>'cmd',
            CASE
                WHEN e.value->>'exit_code' ~ '^-?[0-9]+$'
                THEN (e.value->>'exit_code')::integer
                ELSE NULL
            END,
            e.value->>'output',
            e.value->>'file',
            CASE
                WHEN e.value->>'added' ~ '^-?[0-9]+$'
                THEN (e.value->>'added')::integer
                ELSE NULL
            END,
            CASE
                WHEN e.value->>'removed' ~ '^-?[0-9]+$'
                THEN (e.value->>'removed')::integer
                ELSE NULL
            END,
            e.value->>'note',
            e.value->>'repo',
            COALESCE(
                NULLIF(e.value->>'occurred_at', '')::timestamptz,
                a.updated_at,
                a.created_at,
                now()
            ),
            COALESCE(a.updated_at, a.created_at, now())
        FROM taskforce_session_archive a
        CROSS JOIN LATERAL jsonb_array_elements(a.transcript_events)
            WITH ORDINALITY AS e(value, ordinality)
        WHERE e.value->>'kind' IN ('prompt', 'reply', 'command', 'edit', 'note')
          AND NOT (
              e.value->>'kind' = 'prompt'
              AND EXISTS (
                  SELECT 1
                  FROM taskforce_session_activity activity
                  WHERE activity.actor_id = a.actor_id
                    AND activity.is_demo = a.is_demo
                    AND activity.session_id = a.session_id
                    AND trim(activity.prompt) = trim(e.value->>'text')
              )
          )
        """
    )

    op.drop_table("taskforce_session_activity")
    op.drop_column("taskforce_session_archive", "raw_transcript")
    op.drop_column("taskforce_session_archive", "transcript_events")


def downgrade() -> None:
    op.add_column(
        "taskforce_session_archive",
        sa.Column(
            "transcript_events",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "taskforce_session_archive",
        sa.Column(
            "raw_transcript",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_table(
        "taskforce_session_activity",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fleet_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("prompt", sa.String(length=255), nullable=False),
        sa.Column("response_summary", sa.String(length=2000), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["fleet_session_id"],
            ["taskforce_fleet_session.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        """
        INSERT INTO taskforce_session_activity (
            id, session_id, actor_id, organization_id, fleet_session_id,
            is_demo, prompt, occurred_at, created_at
        )
        SELECT
            id, session_id, actor_id, organization_id, fleet_session_id,
            is_demo, left(text, 255), occurred_at, created_at
        FROM taskforce_session_event
        WHERE kind = 'prompt' AND text IS NOT NULL
        """
    )
    for column in (
        "occurred_at",
        "is_demo",
        "fleet_session_id",
        "organization_id",
        "actor_id",
        "session_id",
    ):
        op.create_index(
            f"ix_taskforce_session_activity_{column}",
            "taskforce_session_activity",
            [column],
        )

    for column in (
        "occurred_at",
        "kind",
        "is_demo",
        "fleet_session_id",
        "organization_id",
        "actor_id",
        "session_id",
    ):
        op.drop_index(
            f"ix_taskforce_session_event_{column}",
            table_name="taskforce_session_event",
        )
    op.drop_table("taskforce_session_event")
