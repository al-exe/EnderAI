"""Manual one-shot: backfill Ledger session archives from metrics_event (TF-218).

Old sessions exist only as ``metrics_event`` rows; this creates best-effort
``taskforce_session_archive`` rows so they show a title + provenance in the
Ledger list. Idempotent (skips already-archived sessions). Does NOT fabricate
transcripts.

Do not import or run this from application startup, migrations, or deploy hooks.
Usage:
  python -m app.scripts.backfill_session_archives
  python -m app.scripts.backfill_session_archives --organization-id <uuid> --demo --write
"""

from __future__ import annotations

import argparse
import sys
import uuid

from sqlmodel import Session

from app.core.db import engine
from app.core.taskforce.archive import backfill_session_archives


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization-id", type=uuid.UUID, default=None)
    demo = parser.add_mutually_exclusive_group()
    demo.add_argument(
        "--demo",
        dest="is_demo",
        action="store_const",
        const=True,
        default=None,
        help="Only backfill demo sessions.",
    )
    demo.add_argument(
        "--live",
        dest="is_demo",
        action="store_const",
        const=False,
        help="Only backfill live (non-demo) sessions.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist archive rows. Without this flag, runs dry.",
    )
    args = parser.parse_args()

    with Session(engine) as session:
        report = backfill_session_archives(
            session,
            organization_id=args.organization_id,
            is_demo=args.is_demo,
            dry_run=not args.write,
        )
        if args.write:
            session.commit()

    mode = "write" if args.write else "dry-run"
    sys.stdout.write(
        f"backfill_session_archives {mode} complete: "
        f"sessions_seen={report.sessions_seen} "
        f"archives_created={report.archives_created} "
        f"skipped_existing={report.skipped_existing}\n"
    )


if __name__ == "__main__":
    main()
