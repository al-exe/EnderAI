"""Backfill case summary_current from legacy case_data

Revision ID: 6f2b5e6c3a11
Revises: 3c0e5c2e1d12
Create Date: 2026-03-22 15:10:00.000000

"""

from alembic import op


revision = "6f2b5e6c3a11"
down_revision = "3c0e5c2e1d12"
branch_labels = None
depends_on = None


def upgrade():
    # Move any stranded legacy JSON summary into the canonical summary_current column
    # before removing the duplicate JSON key entirely.
    op.execute(
        """
        update public.case_record
        set summary_current = nullif(btrim(case_data ->> 'summary_current'), '')
        where nullif(btrim(coalesce(summary_current, '')), '') is null
          and nullif(btrim(coalesce(case_data ->> 'summary_current', '')), '') is not null
        """
    )
    op.execute(
        """
        update public.case_record
        set case_data = case_data - 'summary_current'
        where case_data ? 'summary_current'
        """
    )


def downgrade():
    op.execute(
        """
        update public.case_record
        set case_data = jsonb_set(
            case_data,
            '{summary_current}',
            to_jsonb(summary_current::text),
            true
        )
        where summary_current is not null
        """
    )
