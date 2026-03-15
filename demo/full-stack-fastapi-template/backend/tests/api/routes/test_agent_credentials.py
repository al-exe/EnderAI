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
    assert payload["backend_access_token"] == payload["access_token"]
    assert payload["mcp_access_token"]
    assert payload["mcp_access_token"] != payload["backend_access_token"]
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


def test_backend_agent_token_authenticates_and_updates_last_used_at(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    create_res = client.post(
        f"{settings.API_V1_STR}/agent-credentials/",
        headers=normal_user_token_headers,
        json={"label": "Hosted Codex"},
    )
    token = create_res.json()["backend_access_token"]
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


def test_mcp_agent_token_validates_and_can_call_backend(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    create_res = client.post(
        f"{settings.API_V1_STR}/agent-credentials/",
        headers=normal_user_token_headers,
        json={"label": "Hosted Codex MCP"},
    )
    mcp_token = create_res.json()["mcp_access_token"]
    credential_id = create_res.json()["credential"]["id"]

    validate_res = client.post(
        f"{settings.API_V1_STR}/agent-credentials/validate-mcp-token",
        headers={"Authorization": f"Bearer {mcp_token}"},
    )
    assert validate_res.status_code == 200
    validate_payload = validate_res.json()
    assert validate_payload["valid"] is True
    assert validate_payload["credential_id"] == credential_id

    backend_res = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers={"Authorization": f"Bearer {mcp_token}"},
    )
    assert backend_res.status_code == 200

    db.expire_all()
    credential = db.get(AgentCredential, uuid.UUID(credential_id))
    assert credential is not None
    assert credential.last_used_at is not None


def test_backend_agent_token_cannot_validate_as_mcp_token(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    create_res = client.post(
        f"{settings.API_V1_STR}/agent-credentials/",
        headers=normal_user_token_headers,
        json={"label": "Wrong token kind"},
    )
    backend_token = create_res.json()["backend_access_token"]

    validate_res = client.post(
        f"{settings.API_V1_STR}/agent-credentials/validate-mcp-token",
        headers={"Authorization": f"Bearer {backend_token}"},
    )
    assert validate_res.status_code == 403
    assert validate_res.json() == {"detail": "Could not validate credentials"}


def test_rotate_agent_credential_invalidates_old_tokens(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    create_res = client.post(
        f"{settings.API_V1_STR}/agent-credentials/",
        headers=normal_user_token_headers,
        json={"label": "Rotate me"},
    )
    payload = create_res.json()
    credential_id = payload["credential"]["id"]
    old_backend_token = payload["backend_access_token"]
    old_mcp_token = payload["mcp_access_token"]

    rotate_res = client.post(
        f"{settings.API_V1_STR}/agent-credentials/{credential_id}/rotate",
        headers=normal_user_token_headers,
    )
    assert rotate_res.status_code == 200
    new_payload = rotate_res.json()
    assert new_payload["backend_access_token"] != old_backend_token
    assert new_payload["mcp_access_token"] != old_mcp_token

    old_auth_res = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers={"Authorization": f"Bearer {old_backend_token}"},
    )
    assert old_auth_res.status_code == 403
    assert old_auth_res.json() == {"detail": "Could not validate credentials"}

    old_mcp_validate_res = client.post(
        f"{settings.API_V1_STR}/agent-credentials/validate-mcp-token",
        headers={"Authorization": f"Bearer {old_mcp_token}"},
    )
    assert old_mcp_validate_res.status_code == 403
    assert old_mcp_validate_res.json() == {
        "detail": "Could not validate credentials"
    }

    new_auth_res = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers={"Authorization": f"Bearer {new_payload['backend_access_token']}"},
    )
    assert new_auth_res.status_code == 200

    new_mcp_validate_res = client.post(
        f"{settings.API_V1_STR}/agent-credentials/validate-mcp-token",
        headers={"Authorization": f"Bearer {new_payload['mcp_access_token']}"},
    )
    assert new_mcp_validate_res.status_code == 200

    db.expire_all()
    credential = db.get(AgentCredential, uuid.UUID(credential_id))
    assert credential is not None
    assert credential.token_version == 2


def test_revoke_agent_credential_invalidates_tokens_and_marks_credential(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    create_res = client.post(
        f"{settings.API_V1_STR}/agent-credentials/",
        headers=normal_user_token_headers,
        json={"label": "Revoke me"},
    )
    payload = create_res.json()
    credential_id = payload["credential"]["id"]
    backend_token = payload["backend_access_token"]
    mcp_token = payload["mcp_access_token"]

    revoke_res = client.delete(
        f"{settings.API_V1_STR}/agent-credentials/{credential_id}",
        headers=normal_user_token_headers,
    )
    assert revoke_res.status_code == 200
    assert revoke_res.json() == {"message": "Agent credential revoked successfully"}

    auth_res = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers={"Authorization": f"Bearer {backend_token}"},
    )
    assert auth_res.status_code == 403
    assert auth_res.json() == {"detail": "Could not validate credentials"}

    mcp_validate_res = client.post(
        f"{settings.API_V1_STR}/agent-credentials/validate-mcp-token",
        headers={"Authorization": f"Bearer {mcp_token}"},
    )
    assert mcp_validate_res.status_code == 403
    assert mcp_validate_res.json() == {"detail": "Could not validate credentials"}

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
