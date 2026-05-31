"""TF-202 / C3 — cross-boundary reuse API tests.

Exercises ``GET /v2/taskforce/cross-boundary-reuse``: the empty-cell proof
read surface. Reuses the org-membership + document helpers introduced for the
C1/C2 tests so the events under test are real (produced by one teammate,
consulted by another), never seeded.
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import V2Document
from tests.api.test_taskforce_api import (
    _create_document,
    _join_same_org,
    _signup,
    _user_by_email,
)


def _stamp_produced_by_client(db: Session, doc_id: str, client_name: str) -> None:
    document = db.exec(
        select(V2Document).where(V2Document.id == uuid.UUID(doc_id))
    ).one()
    document.produced_by_client = client_name
    db.add(document)
    db.commit()


def test_cross_boundary_reuse_surfaces_cross_person_event(
    client: TestClient, db: Session
) -> None:
    alice_email, alice_headers = _signup(client)
    bob_email, bob_headers = _signup(client)
    _join_same_org(
        client,
        db,
        owner_headers=alice_headers,
        member_email=bob_email,
        member_headers=bob_headers,
    )
    alice = _user_by_email(db, alice_email)
    bob = _user_by_email(db, bob_email)
    assert alice.organization_id == bob.organization_id

    doc_id = _create_document(
        client,
        alice_headers,
        title="Stripe webhook idempotency strategy",
        description=(
            "Refund and payment webhook retries must use durable event-id "
            "dedupe before side effects."
        ),
        visibility="organization",
        details_markdown_sections=[
            {
                "anchor_id": "decision",
                "markdown": "Store processed Stripe event ids before refunds.",
            }
        ],
    )
    # C1 normally stamps this on produce; set it directly so the row carries
    # a cross-vendor origin tool.
    _stamp_produced_by_client(db, doc_id, "codex")

    # Bob (Claude Code) reuses Alice's org-visible document.
    start = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/session/start",
        headers=bob_headers,
        json={
            "prompt": "Handle refund webhook retries with Stripe event idempotency",
            "client": "claude-code",
            "min_score": 0.0,
        },
    )
    assert start.status_code == 201, start.text
    assert doc_id in {m["document_id"] for m in start.json()["matches"]}

    resp = client.get(
        f"{settings.API_V1_STR}/v2/taskforce/cross-boundary-reuse",
        headers=bob_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == "organization"
    assert body["organization_id"] == str(bob.organization_id)
    assert body["proven_event_count"] >= 1
    assert body["proven_net_saved_tokens"] >= 0

    row = next(e for e in body["events"] if e["document_id"] == doc_id)
    assert row["owner_id"] == str(alice.id)
    assert row["consumer_id"] == str(bob.id)
    assert row["owner_name"]  # producer display name (Alice)
    assert row["consumer_name"]  # reuser display name (Bob)
    assert row["produced_by_client"] == "codex"
    assert row["consumed_by_client"] == "claude-code"
    assert row["document_href"] == f"/v2/documents/{doc_id}"
    assert isinstance(row["net_saved_tokens"], int)


def test_cross_boundary_reuse_excludes_self_use(client: TestClient) -> None:
    email, headers = _signup(client)
    doc_id = _create_document(
        client,
        headers,
        title="Solo Stripe webhook idempotency note",
        description="Durable Stripe event-id dedupe for refund webhooks.",
        visibility="organization",
    )

    # Owner consults their own document — same person, not cross-boundary.
    start = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/session/start",
        headers=headers,
        json={
            "prompt": "Stripe refund webhook idempotency",
            "client": "claude-code",
            "min_score": 0.0,
        },
    )
    assert start.status_code == 201, start.text

    resp = client.get(
        f"{settings.API_V1_STR}/v2/taskforce/cross-boundary-reuse",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert all(e["document_id"] != doc_id for e in resp.json()["events"])


def test_cross_boundary_reuse_requires_organization(
    client: TestClient, db: Session
) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    user.organization_id = None
    db.add(user)
    db.commit()

    resp = client.get(
        f"{settings.API_V1_STR}/v2/taskforce/cross-boundary-reuse",
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
