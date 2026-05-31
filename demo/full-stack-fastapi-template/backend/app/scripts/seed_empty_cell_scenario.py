"""Seed and run the TF-204 Empty-Cell proof scenario.

This is a manual one-shot for a live database. It creates the non-demo
Acme/Alice/Bob fixture, produces Alice's proof document through the real
Taskforce observe path, links that document to the Payments specialist, then
starts Bob's Claude Code session so the real discover path emits
``document.consulted``.

Usage:
  TASKFORCE_OBSERVE_SHADOW=0 python -m app.scripts.seed_empty_cell_scenario
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid

from sqlmodel import Session, col, select

from app.core.agents.seed import (
    EMPTY_CELL_ALICE_DOC_TITLE,
    EMPTY_CELL_ALICE_PROMPT,
    EMPTY_CELL_BOB_PROMPT,
    EMPTY_CELL_DEFAULT_PASSWORD,
    link_empty_cell_payments_specialist,
    seed_empty_cell_proof_accounts,
)
from app.core.db import engine
from app.core.taskforce.observe import observe
from app.core.taskforce.session import session_start
from app.models import (
    METRICS_EVENT_DOCUMENT_CONSULTED,
    MetricsEvent,
    TaskforceCommandRun,
    TaskforceDetailsSectionInput,
    TaskforceObserveRequest,
    TaskforceSessionStartRequest,
    User,
    V2Document,
)


def _shadow_disabled() -> bool:
    return os.environ.get("TASKFORCE_OBSERVE_SHADOW", "1") in {
        "0",
        "false",
        "False",
    }


def _existing_alice_document(
    session: Session, *, owner_id: uuid.UUID
) -> V2Document | None:
    return session.exec(
        select(V2Document)
        .where(V2Document.owner_id == owner_id)
        .where(V2Document.title == EMPTY_CELL_ALICE_DOC_TITLE)
        .where(V2Document.visibility == "organization")
        .where(V2Document.produced_by_client == "codex")
        .where(col(V2Document.is_demo).is_(False))
        .order_by(col(V2Document.created_at).desc())
    ).first()


async def _produce_alice_document(session: Session, *, alice: User) -> V2Document:
    if not _shadow_disabled():
        raise SystemExit(
            "TASKFORCE_OBSERVE_SHADOW must be 0 to produce the proof document"
        )

    response = await observe(
        session,
        actor=alice,
        demo=False,
        request=TaskforceObserveRequest(
            kind="final",
            prompt=EMPTY_CELL_ALICE_PROMPT,
            client="codex",
            visibility="organization",
            files_touched=[
                "app/api/routes/billing.py",
                "app/core/stripe_billing.py",
                "tests/api/routes/test_billing.py",
            ],
            commands_run=[
                TaskforceCommandRun(
                    cmd="pytest tests/api/routes/test_billing.py -k stripe"
                )
            ],
            summary_points=[
                EMPTY_CELL_ALICE_DOC_TITLE,
                (
                    "Persist each Stripe refund webhook event id before issuing "
                    "the refund side effect."
                ),
                (
                    "Duplicate webhook delivery must return success after the "
                    "dedupe hit without creating a second refund."
                ),
            ],
            details_sections=[
                TaskforceDetailsSectionInput(
                    anchor_id="stripe-event-idempotency",
                    markdown=(
                        "# Stripe event-id idempotency\n\n"
                        "Refund webhooks share the same retry behavior as payment "
                        "webhooks: Stripe can redeliver the same event after a "
                        "timeout. The handler must insert the Stripe `event.id` "
                        "into a durable processed-events table before issuing the "
                        "refund. On conflict, short-circuit and return 200 without "
                        "running the refund side effect again.\n\n"
                        "Touched files: app/api/routes/billing.py, "
                        "app/core/stripe_billing.py, tests/api/routes/test_billing.py."
                    ),
                )
            ],
            decisions=[
                (
                    "Use a database uniqueness guard on Stripe event id instead "
                    "of process-local locks."
                )
            ],
            outcome="shipped",
            specialist_slug="payments",
        ),
    )
    if response.document_id is None:
        raise SystemExit(f"observe did not create a document: {response.reason}")

    document = session.get(V2Document, response.document_id)
    if document is None:
        raise SystemExit(f"created document {response.document_id} was not found")
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alice-email", default="alice@acme.example")
    parser.add_argument("--bob-email", default="bob@acme.example")
    parser.add_argument("--organization", default="Acme")
    parser.add_argument("--password", default=EMPTY_CELL_DEFAULT_PASSWORD)
    args = parser.parse_args()

    with Session(engine) as session:
        seed = seed_empty_cell_proof_accounts(
            session,
            organization_name=args.organization,
            alice_email=args.alice_email,
            bob_email=args.bob_email,
            password=args.password,
        )
        document = _existing_alice_document(session, owner_id=seed.alice.id)
        if document is None:
            document = asyncio.run(_produce_alice_document(session, alice=seed.alice))

        link = link_empty_cell_payments_specialist(
            session,
            specialist=seed.specialist,
            document=document,
        )

        bob_session = session_start(
            session,
            actor=seed.bob,
            request=TaskforceSessionStartRequest(
                prompt=EMPTY_CELL_BOB_PROMPT,
                client="claude-code",
                files=[
                    "app/api/routes/billing.py",
                    "app/core/stripe_billing.py",
                ],
                recent_commands=['rg "refund|webhook|idempotency" app tests'],
                min_score=0.0,
                demo=False,
            ),
        )

        consulted = session.exec(
            select(MetricsEvent)
            .where(MetricsEvent.kind == METRICS_EVENT_DOCUMENT_CONSULTED)
            .where(MetricsEvent.user_id == seed.bob.id)
            .where(MetricsEvent.document_id == document.id)
            .order_by(col(MetricsEvent.occurred_at).desc())
        ).first()
        if consulted is None:
            raise SystemExit(
                "Bob's session did not consult Alice's proof document; "
                "no changes were committed"
            )

        session.commit()

        payload = {
            "organization_id": str(seed.organization.id),
            "alice": {"id": str(seed.alice.id), "email": seed.alice.email},
            "bob": {"id": str(seed.bob.id), "email": seed.bob.email},
            "specialist": {
                "id": str(seed.specialist.id),
                "slug": seed.specialist.slug,
            },
            "document": {
                "id": str(document.id),
                "title": document.title,
                "produced_by_client": document.produced_by_client,
                "visibility": document.visibility,
            },
            "link_id": str(link.id),
            "bob_session_id": str(bob_session.session_id),
            "consulted_event": {
                "id": str(consulted.id),
                "consumed_by_client": consulted.payload.get("consumed_by_client"),
                "specialist_slug": consulted.payload.get("specialist_slug"),
                "net_saved_tokens": consulted.payload.get("net_saved_tokens"),
                "usd_amount": str(consulted.usd_amount or ""),
            },
            "matched_document_ids": [
                str(match.document_id) for match in bob_session.matches
            ],
        }
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
