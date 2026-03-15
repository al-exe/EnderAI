import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import AgentCredential
from tests.utils.user import authentication_token_from_email


def test_create_agent_credential_returns_token_and_metadata(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/agent-credentials/",
        headers=normal_user_token_headers,
        json={"label": "Codex laptop"},
    )

    assert r.status_code == 201
    payload = r.json()
    assert payload["access_token"]
    assert payload["token_type"] == "bearer"
    assert payload["credential"]["label"] == "Codex laptop"
    assert payload["credential"]["revoked_at"] is None
    assert payload["credential"]["current_token_expires_at"] is not None

    credential = db.get(AgentCredential, uuid.UUID(payload["credential"]["id"]))
    assert credential is not None
    assert credential.user_id is not None
    assert credential.token_version == 1

    list_res = client.get(
        f"{settings.API_V1_STR}/agent-credentials/",
        headers=normal_user_token_headers,
    )
    assert list_res.status_code == 200
    list_payload = list_res.json()
    assert list_payload["count"] >= 1
    assert any(
        entry["id"] == payload["credential"]["id"] for entry in list_payload["data"]
    )


def test_agent_credential_token_authenticates_and_updates_last_used_at(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    create_res = client.post(
        f"{settings.API_V1_STR}/agent-credentials/",
        headers=normal_user_token_headers,
        json={"label": "Hosted Codex"},
    )
    token = create_res.json()["access_token"]
    credential_id = create_res.json()["credential"]["id"]

    auth_res = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert auth_res.status_code == 200

    db.expire_all()
    credential = db.get(AgentCredential, uuid.UUID(credential_id))
    assert credential is not None
    assert credential.last_used_at is not None


def test_rotate_agent_credential_invalidates_old_token(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    create_res = client.post(
        f"{settings.API_V1_STR}/agent-credentials/",
        headers=normal_user_token_headers,
        json={"label": "Rotate me"},
    )
    payload = create_res.json()
    credential_id = payload["credential"]["id"]
    old_token = payload["access_token"]

    rotate_res = client.post(
        f"{settings.API_V1_STR}/agent-credentials/{credential_id}/rotate",
        headers=normal_user_token_headers,
    )
    assert rotate_res.status_code == 200
    new_payload = rotate_res.json()
    assert new_payload["access_token"] != old_token

    old_auth_res = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert old_auth_res.status_code == 403
    assert old_auth_res.json() == {"detail": "Could not validate credentials"}

    new_auth_res = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers={"Authorization": f"Bearer {new_payload['access_token']}"},
    )
    assert new_auth_res.status_code == 200

    db.expire_all()
    credential = db.get(AgentCredential, uuid.UUID(credential_id))
    assert credential is not None
    assert credential.token_version == 2


def test_revoke_agent_credential_invalidates_token_and_marks_credential(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    create_res = client.post(
        f"{settings.API_V1_STR}/agent-credentials/",
        headers=normal_user_token_headers,
        json={"label": "Revoke me"},
    )
    payload = create_res.json()
    credential_id = payload["credential"]["id"]
    token = payload["access_token"]

    revoke_res = client.delete(
        f"{settings.API_V1_STR}/agent-credentials/{credential_id}",
        headers=normal_user_token_headers,
    )
    assert revoke_res.status_code == 200
    assert revoke_res.json() == {"message": "Agent credential revoked successfully"}

    auth_res = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert auth_res.status_code == 403
    assert auth_res.json() == {"detail": "Could not validate credentials"}

    db.expire_all()
    credential = db.get(AgentCredential, uuid.UUID(credential_id))
    assert credential is not None
    assert credential.revoked_at is not None


def test_user_cannot_manage_another_users_agent_credential(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    create_res = client.post(
        f"{settings.API_V1_STR}/agent-credentials/",
        headers=normal_user_token_headers,
        json={"label": "Private credential"},
    )
    credential_id = create_res.json()["credential"]["id"]

    other_user_headers = authentication_token_from_email(
        client=client,
        email="other-agent-user@example.com",
        db=db,
    )
    rotate_res = client.post(
        f"{settings.API_V1_STR}/agent-credentials/{credential_id}/rotate",
        headers=other_user_headers,
    )
    assert rotate_res.status_code == 404
    assert rotate_res.json() == {"detail": "Agent credential not found"}

    revoke_res = client.delete(
        f"{settings.API_V1_STR}/agent-credentials/{credential_id}",
        headers=other_user_headers,
    )
    assert revoke_res.status_code == 404
    assert revoke_res.json() == {"detail": "Agent credential not found"}
