"""CRUD for /v2/byok. Provider validation is monkeypatched — we never
hit the real OpenAI/Anthropic /v1/models endpoints during tests."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.search import byok as byok_module
from app.models import ByokCredential
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import random_email

API = settings.API_V1_STR


@pytest.fixture(autouse=True)
def _byok_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        byok_module.settings,
        "BYOK_ENCRYPTION_KEY",
        Fernet.generate_key().decode("utf-8"),
    )

    async def _ok(provider: str, api_key: str) -> None:
        return None

    monkeypatch.setattr(byok_module, "validate_api_key", _ok)


def _auth(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(client=client, email=random_email(), db=db)


def test_create_and_list_byok(client: TestClient, db: Session) -> None:
    headers = _auth(client, db)

    resp = client.post(
        f"{API}/v2/byok",
        headers=headers,
        json={"provider": "openai", "api_key": "sk-test-12345abcd"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["provider"] == "openai"
    assert body["key_fingerprint"].endswith("abcd")
    assert "api_key" not in body  # never echoed back

    resp = client.get(f"{API}/v2/byok", headers=headers)
    assert resp.status_code == 200
    listed = resp.json()["credentials"]
    assert len(listed) == 1
    assert listed[0]["provider"] == "openai"


def test_replace_byok_overwrites_ciphertext(
    client: TestClient, db: Session
) -> None:
    headers = _auth(client, db)
    client.post(
        f"{API}/v2/byok",
        headers=headers,
        json={"provider": "openai", "api_key": "sk-old-aaaaaaaa"},
    )
    client.post(
        f"{API}/v2/byok",
        headers=headers,
        json={"provider": "openai", "api_key": "sk-new-bbbbbbbb"},
    )

    creds = db.exec(
        select(ByokCredential).where(ByokCredential.provider == "openai")
    ).all()
    matches = [
        c
        for c in creds
        if byok_module.decrypt_api_key(c.encrypted_api_key) == "sk-new-bbbbbbbb"
    ]
    assert len(matches) >= 1


def test_revoke_byok_idempotent(client: TestClient, db: Session) -> None:
    headers = _auth(client, db)
    client.post(
        f"{API}/v2/byok",
        headers=headers,
        json={"provider": "anthropic", "api_key": "sk-ant-aaaaaaa"},
    )

    resp1 = client.delete(f"{API}/v2/byok/anthropic", headers=headers)
    resp2 = client.delete(f"{API}/v2/byok/anthropic", headers=headers)
    assert resp1.status_code == 200
    assert resp2.status_code == 200  # idempotent — second delete is a no-op


def test_create_byok_503_when_encryption_key_missing(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(byok_module.settings, "BYOK_ENCRYPTION_KEY", None)
    headers = _auth(client, db)
    resp = client.post(
        f"{API}/v2/byok",
        headers=headers,
        json={"provider": "openai", "api_key": "sk-anything"},
    )
    assert resp.status_code == 503


def test_create_byok_400_when_provider_rejects(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _rejects(provider: str, api_key: str) -> None:
        raise byok_module.ByokValidationError(provider, 401, "invalid key")

    monkeypatch.setattr(byok_module, "validate_api_key", _rejects)
    headers = _auth(client, db)
    resp = client.post(
        f"{API}/v2/byok",
        headers=headers,
        json={"provider": "openai", "api_key": "sk-bogus"},
    )
    assert resp.status_code == 400
