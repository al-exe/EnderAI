"""TF-208 / pipeline-surfaces P1 — org session ledger API tests.

Exercises ``GET /v2/taskforce/ledger``: the raw tier of the pipeline — a
paginated, org-scoped feed of sessions grouped from real ``metrics_event``
rows (no Session table). Reuses the org-membership + document helpers from the
C1/C2 tests so the sessions under test are real, never seeded.
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

_LEDGER = f"{settings.API_V1_STR}/v2/taskforce/ledger"
_DOCUMENTS = f"{settings.API_V1_STR}/v2/taskforce/documents"


def _stamp_produced_by_client(db: Session, doc_id: str, client_name: str) -> None:
    document = db.exec(
        select(V2Document).where(V2Document.id == uuid.UUID(doc_id))
    ).one()
    document.produced_by_client = client_name
    db.add(document)
    db.commit()


def _alice_doc_bob_reuse(
    client: TestClient, db: Session
) -> tuple[str, dict[str, str], str, dict[str, str], str]:
    """Alice produces a Codex doc; Bob reuses it from Claude Code.

    Returns (alice_email, alice_headers, bob_email, bob_headers, doc_id). The
    reuse fires a real ``document.consulted`` event tagged with a session_id —
    exactly one ledger row, flagged cross-boundary.
    """

    alice_email, alice_headers = _signup(client)
    bob_email, bob_headers = _signup(client)
    _join_same_org(
        client,
        db,
        owner_headers=alice_headers,
        member_email=bob_email,
        member_headers=bob_headers,
    )

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
    _stamp_produced_by_client(db, doc_id, "codex")

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
    return alice_email, alice_headers, bob_email, bob_headers, doc_id


def test_ledger_lists_cross_tool_session(client: TestClient, db: Session) -> None:
    _, _, bob_email, bob_headers, doc_id = _alice_doc_bob_reuse(client, db)
    bob = _user_by_email(db, bob_email)

    resp = client.get(_LEDGER, headers=bob_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == "organization"
    assert body["organization_id"] == str(bob.organization_id)
    assert body["total"] >= 1

    row = next(
        r
        for r in body["rows"]
        if any(d["document_id"] == doc_id for d in r["documents"])
    )
    assert row["actor_id"] == str(bob.id)
    assert row["actor_name"]  # display name resolved
    assert row["client"] == "claude-code"
    assert row["cross_boundary"] is True
    assert row["session_id"]
    assert isinstance(row["net_saved_tokens"], int)
    doc = next(d for d in row["documents"] if d["document_id"] == doc_id)
    assert doc["href"] == f"/v2/library/{doc_id}"
    assert "document.consulted" in row["kinds"]


def test_ledger_cross_boundary_filter(client: TestClient, db: Session) -> None:
    _, _, _, bob_headers, doc_id = _alice_doc_bob_reuse(client, db)

    resp = client.get(_LEDGER, headers=bob_headers, params={"cross_boundary": True})
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert rows, "cross-boundary filter should keep the cross-tool reuse session"
    assert all(r["cross_boundary"] is True for r in rows)
    assert any(any(d["document_id"] == doc_id for d in r["documents"]) for r in rows)


def test_document_sessions_lists_document_provenance(
    client: TestClient, db: Session
) -> None:
    _, _, bob_email, bob_headers, doc_id = _alice_doc_bob_reuse(client, db)
    bob = _user_by_email(db, bob_email)

    resp = client.get(f"{_DOCUMENTS}/{doc_id}/sessions", headers=bob_headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == "organization"
    assert body["organization_id"] == str(bob.organization_id)
    assert body["total"] >= 1
    assert body["rows"]
    assert all(
        any(doc["document_id"] == doc_id for doc in row["documents"])
        for row in body["rows"]
    )
    row = body["rows"][0]
    assert row["actor_id"] == str(bob.id)
    assert row["client"] == "claude-code"
    assert row["cross_boundary"] is True
    assert "document.consulted" in row["kinds"]


def test_ledger_client_filter(client: TestClient, db: Session) -> None:
    _, _, _, bob_headers, _ = _alice_doc_bob_reuse(client, db)

    hit = client.get(_LEDGER, headers=bob_headers, params={"client": "claude-code"})
    assert hit.status_code == 200, hit.text
    assert hit.json()["total"] >= 1
    assert all(r["client"] == "claude-code" for r in hit.json()["rows"])

    miss = client.get(_LEDGER, headers=bob_headers, params={"client": "cursor"})
    assert miss.status_code == 200, miss.text
    assert miss.json()["total"] == 0


def test_ledger_scopes_to_caller_org(client: TestClient, db: Session) -> None:
    # Bob's org has the reuse session; an unrelated outsider in a different org
    # must not see it.
    _alice_doc_bob_reuse(client, db)
    _, outsider_headers = _signup(client)

    resp = client.get(_LEDGER, headers=outsider_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 0


def test_ledger_requires_organization(client: TestClient, db: Session) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    user.organization_id = None
    db.add(user)
    db.commit()

    resp = client.get(_LEDGER, headers=headers)
    assert resp.status_code == 422, resp.text


def test_ledger_pagination(client: TestClient, db: Session) -> None:
    _, _, _, bob_headers, _ = _alice_doc_bob_reuse(client, db)

    page = client.get(_LEDGER, headers=bob_headers, params={"limit": 1, "offset": 0})
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["limit"] == 1
    assert len(body["rows"]) <= 1
