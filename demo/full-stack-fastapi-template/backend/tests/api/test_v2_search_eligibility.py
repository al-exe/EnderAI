"""GET /v2/search/eligibility — covers the Free/Pro/Max × BYOK matrix
end-to-end at the HTTP layer."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core import tiering
from app.core.search import byok as byok_module
from app.models import User
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import random_email

API = settings.API_V1_STR
PRO_PRICE = "price_pro_test"
MAX_PRICE = "price_max_test"


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tiering.settings, "STRIPE_PRICE_ID_PRO", PRO_PRICE)
    monkeypatch.setattr(tiering.settings, "STRIPE_PRICE_ID_MAX", MAX_PRICE)
    monkeypatch.setattr(
        byok_module.settings,
        "BYOK_ENCRYPTION_KEY",
        Fernet.generate_key().decode("utf-8"),
    )

    async def _ok(provider: str, api_key: str) -> None:
        return None

    monkeypatch.setattr(byok_module, "validate_api_key", _ok)


def _auth(client: TestClient, db: Session, *, email: str | None = None) -> tuple[dict[str, str], User]:
    email = email or random_email()
    headers = authentication_token_from_email(client=client, email=email, db=db)
    user = db.exec(select(User).where(User.email == email)).one()
    return headers, user


def _set_tier(db: Session, user: User, *, status: str | None, price: str | None) -> None:
    user.stripe_subscription_status = status
    user.stripe_price_id = price
    db.add(user)
    db.commit()


def test_eligibility_free_default(client: TestClient, db: Session) -> None:
    headers, _ = _auth(client, db)
    resp = client.get(f"{API}/v2/search/eligibility", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == "free"
    assert body["allowed"] is False
    assert body["reason"] == "upgrade_required"


def test_eligibility_max_routes_to_managed(client: TestClient, db: Session) -> None:
    headers, user = _auth(client, db)
    _set_tier(db, user, status="active", price=MAX_PRICE)
    resp = client.get(f"{API}/v2/search/eligibility", headers=headers)
    body = resp.json()
    assert body["tier"] == "max"
    assert body["allowed"] is True
    assert body["route"] == "managed"


def test_eligibility_pro_needs_byok(client: TestClient, db: Session) -> None:
    headers, user = _auth(client, db)
    _set_tier(db, user, status="active", price=PRO_PRICE)
    resp = client.get(f"{API}/v2/search/eligibility", headers=headers)
    body = resp.json()
    assert body["tier"] == "pro"
    assert body["allowed"] is False
    assert body["reason"] == "byok_required"


def test_eligibility_pro_with_byok_routes_to_byok(
    client: TestClient, db: Session
) -> None:
    headers, user = _auth(client, db)
    _set_tier(db, user, status="active", price=PRO_PRICE)
    create = client.post(
        f"{API}/v2/byok",
        headers=headers,
        json={"provider": "openai", "api_key": "sk-test-aaaaaaaaaaaaa"},
    )
    assert create.status_code == 201, create.text
    resp = client.get(f"{API}/v2/search/eligibility", headers=headers)
    body = resp.json()
    assert body["allowed"] is True
    assert body["route"] == "byok:openai"
    assert len(body["byok"]) == 1
    assert body["byok"][0]["provider"] == "openai"
