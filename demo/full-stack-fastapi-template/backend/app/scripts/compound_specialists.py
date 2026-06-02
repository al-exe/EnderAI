"""Manual one-shot: compound earned agent specialist document links.

Do not import or run this from application startup, migrations, or deploy hooks.
Usage:
  python -m app.scripts.compound_specialists
  python -m app.scripts.compound_specialists --organization-id <uuid> --write
"""

from __future__ import annotations

import argparse
import sys
import uuid

from sqlmodel import Session

from app.core.agents.compounding import (
    MAX_LINKS_PER_SPECIALIST,
    MIN_LINK_SCORE,
    compound_specialists,
)
from app.core.db import engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization-id", type=uuid.UUID, default=None)
    parser.add_argument("--min-link-score", type=float, default=MIN_LINK_SCORE)
    parser.add_argument(
        "--max-links-per-specialist",
        type=int,
        default=MAX_LINKS_PER_SPECIALIST,
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist link upserts/promotions. Without this flag, runs dry.",
    )
    args = parser.parse_args()

    with Session(engine) as session:
        report = compound_specialists(
            session,
            organization_id=args.organization_id,
            min_link_score=args.min_link_score,
            max_links_per_specialist=args.max_links_per_specialist,
            dry_run=not args.write,
        )
        if args.write:
            session.commit()

    mode = "write" if args.write else "dry-run"
    sys.stdout.write(
        f"compound_specialists {mode} complete: "
        + " ".join(f"{key}={value}" for key, value in report.items())
        + "\n"
    )


if __name__ == "__main__":
    main()
