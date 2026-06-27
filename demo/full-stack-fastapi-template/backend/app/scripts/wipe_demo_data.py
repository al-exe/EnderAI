"""Wipe ALL demo (``is_demo``) data and reset ``User.demo_seeded_at``.

The demo experience is V2-only (documents, agent profiles, metrics, sessions),
but historically the database may also hold deprecated V1 demo rows (topics /
cases / skills). This script removes every ``is_demo`` row across the schema,
plus the child rows that hang off demo parents but have no ``is_demo`` column of
their own (document shares/favorites/changelogs, specialist↔document links, and
V1 case records/events). It then clears ``User.demo_seeded_at`` for every user so
each account re-clones the refreshed catalog the next time demo mode is toggled.

Destructive, but reversible: every row removed is regenerable seed data. Re-run
``app.scripts.seed_demo_metrics_alex`` (or toggle demo mode) to repopulate.

Deletions run children-first using ``metadata.sorted_tables`` (FK-safe) inside a
single transaction. The default is a dry run that only reports counts; pass
``--yes`` to commit.

Usage::

    # dry run (counts only, no writes)
    uv run python -m app.scripts.wipe_demo_data
    # apply
    uv run python -m app.scripts.wipe_demo_data --yes
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlmodel import Session, SQLModel

from app import models  # noqa: F401  (register all tables on SQLModel.metadata)
from app.core.db import engine


def _count(session: Session, table: Any, whereclause: Any) -> int:
    return int(
        session.execute(
            select(func.count()).select_from(table).where(whereclause)
        ).scalar_one()
    )


def wipe_demo_data(session: Session, *, apply: bool) -> dict[str, int]:
    md = SQLModel.metadata
    tables = {t.name: t for t in md.sorted_tables}

    doc = tables["v2_document"]
    topic = tables["topic"]
    specialist = tables["agent_specialist"]
    case_record = tables["case_record"]

    demo_doc_ids = select(doc.c.id).where(doc.c.is_demo.is_(True))
    demo_topic_ids = select(topic.c.id).where(topic.c.is_demo.is_(True))
    demo_specialist_ids = select(specialist.c.id).where(specialist.c.is_demo.is_(True))
    demo_case_ids = select(case_record.c.id).where(
        case_record.c.topic_id.in_(demo_topic_ids)
    )

    # (table, whereclause) for child rows that lack an is_demo column but belong
    # to a demo parent. Ordered children-first so FK constraints hold.
    child_targets: list[tuple[str, Any]] = [
        (
            "agent_specialist_document_link",
            tables["agent_specialist_document_link"].c.specialist_id.in_(
                demo_specialist_ids
            )
            | tables["agent_specialist_document_link"].c.document_id.in_(demo_doc_ids),
        ),
        (
            "v2_document_share",
            tables["v2_document_share"].c.document_id.in_(demo_doc_ids),
        ),
        (
            "v2_document_favorite",
            tables["v2_document_favorite"].c.document_id.in_(demo_doc_ids),
        ),
        (
            "v2_document_evolution_changelog",
            tables["v2_document_evolution_changelog"].c.document_id.in_(demo_doc_ids),
        ),
        ("case_event", tables["case_event"].c.case_id.in_(demo_case_ids)),
        ("case_record", case_record.c.topic_id.in_(demo_topic_ids)),
    ]

    counts: dict[str, int] = {}

    # 1) child rows without is_demo (must precede their demo parents)
    for name, whereclause in child_targets:
        table = tables[name]
        counts[name] = _count(session, table, whereclause)
        if apply and counts[name]:
            session.execute(delete(table).where(whereclause))

    # 2) every is_demo table, children-first (reverse FK-dependency order)
    for table in reversed(md.sorted_tables):
        if "is_demo" not in table.columns:
            continue
        whereclause = table.c.is_demo.is_(True)
        counts[table.name] = _count(session, table, whereclause)
        if apply and counts[table.name]:
            session.execute(delete(table).where(whereclause))

    # 3) reset demo_seeded_at so accounts re-clone the refreshed catalog
    user = tables["user"]
    counts["user.demo_seeded_at_reset"] = _count(
        session, user, user.c.demo_seeded_at.is_not(None)
    )
    if apply and counts["user.demo_seeded_at_reset"]:
        session.execute(
            update(user)
            .where(user.c.demo_seeded_at.is_not(None))
            .values(demo_seeded_at=None)
        )

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete. Without this flag the script only reports counts.",
    )
    args = parser.parse_args()

    with Session(engine) as session:
        counts = wipe_demo_data(session, apply=args.yes)
        if args.yes:
            session.commit()

    total = sum(v for k, v in counts.items() if not k.endswith("_reset"))
    mode = "DELETED" if args.yes else "WOULD DELETE (dry run)"
    lines = [f"=== wipe_demo_data: {mode} ==="]
    lines += [f"  {name:42s} {n}" for name, n in counts.items() if n]
    lines.append(f"  {'TOTAL demo rows':42s} {total}")
    if not args.yes:
        lines.append("\nDry run only — re-run with --yes to apply.")
    sys.stdout.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
