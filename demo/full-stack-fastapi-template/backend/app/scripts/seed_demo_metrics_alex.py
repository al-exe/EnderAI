"""Manual one-shot: seed TF-198 Alex demo specialist invocation history.

Do not import or run this from application startup, migrations, or deploy hooks.
Usage: ``python -m app.scripts.seed_demo_metrics_alex``.
"""

from __future__ import annotations

import argparse
import sys

from sqlmodel import Session

from app.core.agents.seed import seed_demo_metrics_for_alex
from app.core.db import engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default="alexlee4190@gmail.com")
    args = parser.parse_args()

    with Session(engine) as session:
        result = seed_demo_metrics_for_alex(session, email=args.email)
        session.commit()
        sys.stdout.write(
            "seed_demo_metrics_alex complete: "
            f"sessions={result.sessions_created} events={result.events_created}\n"
        )


if __name__ == "__main__":
    main()
