"""Integration coverage for the Taskforce session inbox (reply-to-idle-agent).

The Sessions "Reply to agent" box enqueues a prompt; the agent's Stop hook
claims it and re-injects it. These tests exercise the three routes end-to-end:
enqueue (frontend), list pending (frontend), and claim (Stop hook).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import TaskforceSessionArchive, User
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

API = settings.API_V1_STR


def _signup(client: TestClient) -> dict[str, str]:
    email = random_email()
    password = random_lower_string()
    response = client.post(
        f"{API}/users/signup",
        json={"email": email, "password": password, "full_name": "Inbox Tester"},
    )
    assert 200 <= response.status_code < 300, response.text
    return user_authentication_headers(
        client=client, email=email, password=password
    )


def _signup_with_email(client: TestClient) -> tuple[str, dict[str, str]]:
    email = random_email()
    password = random_lower_string()
    response = client.post(
        f"{API}/users/signup",
        json={"email": email, "password": password, "full_name": "Inbox Tester"},
    )
    assert 200 <= response.status_code < 300, response.text
    return email, user_authentication_headers(
        client=client, email=email, password=password
    )


def _create_archive(db: Session, *, email: str, session_id: str) -> None:
    user = db.exec(select(User).where(User.email == email)).one()
    now = datetime.now(timezone.utc)
    archive = TaskforceSessionArchive(
        session_id=session_id,
        actor_id=user.id,
        organization_id=user.organization_id,
        client="claude-code",
        model_id="claude-opus-4-8",
        imported_at=now,
        last_seen_at=now,
    )
    db.add(archive)
    db.commit()


def test_enqueue_list_claim_round_trip(client: TestClient, db: Session) -> None:
    email, headers = _signup_with_email(client)
    session_id = "sess-roundtrip"
    _create_archive(db, email=email, session_id=session_id)

    # Enqueue two prompts.
    first = client.post(
        f"{API}/v2/taskforce/session/{session_id}/inbox",
        headers=headers,
        json={"body": "run the failing tests again"},
    )
    assert first.status_code == 201, first.text
    assert first.json()["body"] == "run the failing tests again"
    assert first.json()["delivered_at"] is None

    client.post(
        f"{API}/v2/taskforce/session/{session_id}/inbox",
        headers=headers,
        json={"body": "then open the PR"},
    )

    # Both show as pending, oldest first.
    listed = client.get(
        f"{API}/v2/taskforce/session/{session_id}/inbox", headers=headers
    )
    assert listed.status_code == 200, listed.text
    pending = listed.json()["pending"]
    assert [m["body"] for m in pending] == [
        "run the failing tests again",
        "then open the PR",
    ]

    # The Stop hook claims them one at a time, in order.
    claim1 = client.post(
        f"{API}/v2/taskforce/session/inbox/claim",
        headers=headers,
        json={"session_id": session_id},
    )
    assert claim1.status_code == 200, claim1.text
    assert claim1.json()["message"] == "run the failing tests again"

    claim2 = client.post(
        f"{API}/v2/taskforce/session/inbox/claim",
        headers=headers,
        json={"session_id": session_id},
    )
    assert claim2.json()["message"] == "then open the PR"

    # Queue drained → empty claim (hook falls through to a normal stop).
    claim3 = client.post(
        f"{API}/v2/taskforce/session/inbox/claim",
        headers=headers,
        json={"session_id": session_id},
    )
    assert claim3.status_code == 200
    assert claim3.json()["message"] is None
    assert claim3.json()["message_id"] is None

    # Nothing pending anymore.
    after = client.get(
        f"{API}/v2/taskforce/session/{session_id}/inbox", headers=headers
    )
    assert after.json()["pending"] == []


def test_claim_is_one_shot(client: TestClient, db: Session) -> None:
    email, headers = _signup_with_email(client)
    session_id = "sess-oneshot"
    _create_archive(db, email=email, session_id=session_id)

    client.post(
        f"{API}/v2/taskforce/session/{session_id}/inbox",
        headers=headers,
        json={"body": "only once"},
    )
    first = client.post(
        f"{API}/v2/taskforce/session/inbox/claim",
        headers=headers,
        json={"session_id": session_id},
    )
    assert first.json()["message"] == "only once"

    # A second claim must never re-deliver the same message.
    second = client.post(
        f"{API}/v2/taskforce/session/inbox/claim",
        headers=headers,
        json={"session_id": session_id},
    )
    assert second.json()["message"] is None


def test_enqueue_unknown_session_is_404(client: TestClient) -> None:
    headers = _signup(client)
    response = client.post(
        f"{API}/v2/taskforce/session/does-not-exist/inbox",
        headers=headers,
        json={"body": "hello?"},
    )
    assert response.status_code == 404


def test_inbox_is_actor_scoped(client: TestClient, db: Session) -> None:
    owner_email, owner_headers = _signup_with_email(client)
    other_headers = _signup(client)
    session_id = "sess-scoped"
    _create_archive(db, email=owner_email, session_id=session_id)

    # A different user cannot enqueue to someone else's session.
    forbidden = client.post(
        f"{API}/v2/taskforce/session/{session_id}/inbox",
        headers=other_headers,
        json={"body": "not my agent"},
    )
    assert forbidden.status_code == 404

    # The owner enqueues; the other user's claim never sees it.
    client.post(
        f"{API}/v2/taskforce/session/{session_id}/inbox",
        headers=owner_headers,
        json={"body": "owner only"},
    )
    other_claim = client.post(
        f"{API}/v2/taskforce/session/inbox/claim",
        headers=other_headers,
        json={"session_id": session_id},
    )
    assert other_claim.json()["message"] is None

    owner_claim = client.post(
        f"{API}/v2/taskforce/session/inbox/claim",
        headers=owner_headers,
        json={"session_id": session_id},
    )
    assert owner_claim.json()["message"] == "owner only"


def test_empty_body_is_rejected(client: TestClient, db: Session) -> None:
    email, headers = _signup_with_email(client)
    session_id = "sess-empty"
    _create_archive(db, email=email, session_id=session_id)

    response = client.post(
        f"{API}/v2/taskforce/session/{session_id}/inbox",
        headers=headers,
        json={"body": ""},
    )
    assert response.status_code == 422
