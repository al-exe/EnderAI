"""Manual one-shot: seed TF-198 demo agent specialists.

Do not import or run this from application startup, migrations, or deploy hooks.
Usage: ``python -m app.scripts.seed_agents --email alexlee4190@gmail.com``.
"""

from __future__ import annotations

import argparse
import sys

from sqlmodel import Session, select

from app.core.agents.seed import seed_agents
from app.core.db import engine
from app.models import User


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default="alexlee4190@gmail.com")
    args = parser.parse_args()

    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == args.email)).first()
        if user is None:
            raise SystemExit(f"User {args.email} not found")
        result = seed_agents(session, user)
        session.commit()
        sys.stdout.write(
            "seed_agents complete: "
            f"specialists={result.specialists_created} "
            f"documents_created={result.documents_created} "
            f"links={result.links_created}\n"
        )


if __name__ == "__main__":
    main()
