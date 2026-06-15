"""Coverage for the Fleet per-turn activity timeline API (TF-247)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import Organization, TaskforceSessionEvent, User
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def _signup(client: TestClient) -> tuple[str, dict[str, str]]:
    email = random_email()
    password = random_lower_string()
    response = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={"email": email, "password": password, "full_name": "Activity Tester"},
    )
    assert 200 <= response.status_code < 300, response.text
    return email, user_authentication_headers(
        client=client,
        email=email,
        password=password,
    )


def _user_by_email(db: Session, email: str) -> User:
    return db.exec(select(User).where(User.email == email)).one()


def _discover(client: TestClient, headers: dict[str, str], prompt: str, session_id: str):
    return client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={"prompt": prompt, "session_id": session_id, "min_score": 0.0},
    )


def _activity(client: TestClient, headers: dict[str, str], session_id: str):
    response = client.get(
        f"{settings.API_V1_STR}/v2/taskforce/session-activity",
        headers=headers,
        params={"session_id": session_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_discover_appends_prompt_events_and_dedupes(
    client: TestClient,
) -> None:
    _, headers = _signup(client)
    session_id = f"activity-{uuid.uuid4()}"

    assert _discover(client, headers, "Wire the fleet activity timeline", session_id).status_code == 200
    # Re-firing the same prompt must not create a duplicate row.
    assert _discover(client, headers, "Wire the fleet activity timeline", session_id).status_code == 200
    assert _discover(client, headers, "Now add the ledger deep link", session_id).status_code == 200

    body = _activity(client, headers, session_id)
    prompts = [
        entry["text"] for entry in body["entries"] if entry["kind"] == "prompt"
    ]
    assert prompts == [
        "Now add the ledger deep link",
        "Wire the fleet activity timeline",
    ]


def test_observe_appends_actual_events_and_dedupes_repeated_snapshots(
    client: TestClient,
) -> None:
    _, headers = _signup(client)
    session_id = f"activity-{uuid.uuid4()}"

    assert _discover(client, headers, "Investigate the cache TTL", session_id).status_code == 200

    payload = {
        "kind": "checkpoint",
        "prompt": "Investigate the cache TTL",
        "client": "activity-test",
        "session_id": session_id,
        "transcript": [
            {
                "role": "user",
                "content": "Investigate the cache TTL",
                "source_id": "turn-user-1",
                "occurred_at": "2026-06-15T18:00:00Z",
            },
            {
                "role": "assistant",
                "content": "Set the widget cache TTL to 900 seconds.",
                "source_id": "turn-agent-1",
                "occurred_at": "2026-06-15T18:01:00Z",
            },
        ],
        "commands_run": [
            {
                "cmd": "pytest tests/test_cache.py",
                "exit_code": 0,
                "output": "1 passed",
                "source_id": "tool-1",
                "occurred_at": "2026-06-15T18:00:30Z",
            }
        ],
        "files_touched": ["config/widget_cache.yaml"],
        "checkpoint_index": 1,
        "summary_points": ["Set the widget cache TTL to 900 seconds."],
        "duration_ms": 1000,
    }
    for _ in range(2):
        observe = client.post(
            f"{settings.API_V1_STR}/v2/taskforce/observe",
            headers=headers,
            json=payload,
        )
        assert observe.status_code == 202, observe.text

    body = _activity(client, headers, session_id)
    assert [entry["kind"] for entry in body["entries"]].count("prompt") == 1
    assert [entry["kind"] for entry in body["entries"]].count("reply") == 1
    assert [entry["kind"] for entry in body["entries"]].count("command") == 1
    assert [entry["kind"] for entry in body["entries"]].count("edit") == 1
    reply = next(entry for entry in body["entries"] if entry["kind"] == "reply")
    assert reply["text"] == "Set the widget cache TTL to 900 seconds."
    assert reply["occurred_at"] == "2026-06-15T18:01:00Z"
    command = next(entry for entry in body["entries"] if entry["kind"] == "command")
    assert command["output"] == "1 passed"


def test_ledger_href_gated_on_organization(
    client: TestClient,
    db: Session,
) -> None:
    # No-org user: the Ledger is org-only, so there is no deep link.
    email, solo_headers = _signup(client)
    solo_user = _user_by_email(db, email)
    solo_user.organization_id = None
    db.add(solo_user)
    db.commit()
    solo_session = f"activity-{uuid.uuid4()}"
    assert _discover(client, solo_headers, "Solo turn", solo_session).status_code == 200
    solo_body = _activity(client, solo_headers, solo_session)
    assert solo_body["entries"][0]["ledger_href"] is None

    # Org user: deep link points at the Ledger session, anchored by timestamp.
    email, org_headers = _signup(client)
    user = _user_by_email(db, email)
    org = Organization(name=f"acme-{uuid.uuid4().hex[:8]}")
    db.add(org)
    db.commit()
    db.refresh(org)
    user.organization_id = org.id
    db.add(user)
    db.commit()

    org_session = f"activity-{uuid.uuid4()}"
    assert _discover(client, org_headers, "Org turn", org_session).status_code == 200
    org_body = _activity(client, org_headers, org_session)
    href = org_body["entries"][0]["ledger_href"]
    assert href is not None
    assert f"session_id={org_session}" in href
    assert "event_id=" in href


def test_session_activity_is_owner_scoped(
    client: TestClient,
    db: Session,
) -> None:
    _, owner_headers = _signup(client)
    _, other_headers = _signup(client)
    session_id = f"activity-{uuid.uuid4()}"

    assert _discover(client, owner_headers, "Owner only", session_id).status_code == 200

    # A different user querying the same session_id sees nothing.
    other_body = _activity(client, other_headers, session_id)
    assert other_body["entries"] == []

    # And the row really exists for the owner.
    rows = db.exec(
        select(TaskforceSessionEvent).where(
            TaskforceSessionEvent.session_id == session_id
        )
    ).all()
    assert len(rows) == 1
