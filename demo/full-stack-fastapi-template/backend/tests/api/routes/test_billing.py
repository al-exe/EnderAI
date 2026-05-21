import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import UserCreate
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def _stripe_signature(payload: bytes, secret: str) -> str:
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.".encode() + payload
    signature = hmac.new(
        secret.encode(),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


def test_billing_status_for_user_without_customer(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/billing/status",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["has_customer"] is False
    assert response.json()["is_subscription_active"] is False


def test_billing_status_sanitizes_admin_tier(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "STRIPE_PRICE_ID", "price_admin_test")
    email = random_email()
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=email, password=password),
    )
    user.stripe_subscription_status = "active"
    user.stripe_price_id = "price_admin_test"
    db.add(user)
    db.commit()
    headers = user_authentication_headers(client=client, email=email, password=password)

    response = client.get(
        f"{settings.API_V1_STR}/billing/status",
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_subscription_active"] is True
    assert body["subscription_tier"] == "max"


def test_checkout_session_creates_customer_and_returns_url(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    email = random_email()
    password = random_lower_string()
    crud.create_user(
        session=db,
        user_create=UserCreate(email=email, password=password, full_name="Buyer"),
    )
    headers = user_authentication_headers(client=client, email=email, password=password)

    monkeypatch.setattr(settings, "STRIPE_TASKFORCE_PRO", "price_pro_live")
    from app.api.routes import billing

    checkout_args = {}
    monkeypatch.setattr(
        billing.stripe_client,
        "create_customer",
        lambda **_: {"id": "cus_test"},
    )
    monkeypatch.setattr(
        billing.stripe_client,
        "create_checkout_session",
        lambda **kwargs: checkout_args.update(kwargs)
        or {"url": "https://checkout.stripe.test/session"},
    )

    response = client.post(
        f"{settings.API_V1_STR}/billing/checkout-session",
        headers=headers,
        json={"tier": "pro"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"url": "https://checkout.stripe.test/session"}
    assert checkout_args["price_id"] == "price_pro_live"

    user = crud.get_user_by_email(session=db, email=email)
    assert user is not None
    db.refresh(user)
    assert user.stripe_customer_id == "cus_test"


def test_checkout_session_uses_max_price(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "STRIPE_TASKFORCE_MAX", "price_max_live")
    from app.api.routes import billing

    checkout_args = {}
    monkeypatch.setattr(
        billing.stripe_client,
        "create_customer",
        lambda **_: {"id": "cus_max_test"},
    )
    monkeypatch.setattr(
        billing.stripe_client,
        "create_checkout_session",
        lambda **kwargs: checkout_args.update(kwargs)
        or {"url": "https://checkout.stripe.test/session"},
    )

    response = client.post(
        f"{settings.API_V1_STR}/billing/checkout-session",
        headers=normal_user_token_headers,
        json={"tier": "max"},
    )

    assert response.status_code == 200, response.text
    assert checkout_args["price_id"] == "price_max_live"


def test_checkout_session_rejects_unconfigured_tier(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "STRIPE_TASKFORCE_MAX", None)

    response = client.post(
        f"{settings.API_V1_STR}/billing/checkout-session",
        headers=normal_user_token_headers,
        json={"tier": "max"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Stripe price ID is not configured for Taskforce Max"
    )


def test_subscription_webhook_updates_billing_state(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    webhook_secret = "whsec_test"
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", webhook_secret)
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=random_lower_string()),
    )
    user.stripe_customer_id = "cus_subscription_test"
    db.add(user)
    db.commit()

    payload = json.dumps(
        {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_test",
                    "customer": "cus_subscription_test",
                    "status": "active",
                    "cancel_at_period_end": False,
                    "current_period_end": 1_800_000_000,
                    "items": {
                        "data": [
                            {
                                "price": {"id": "price_test"},
                                "current_period_end": 1_800_000_000,
                            }
                        ]
                    },
                }
            },
        }
    ).encode()

    response = client.post(
        f"{settings.API_V1_STR}/billing/stripe/webhook",
        content=payload,
        headers={"stripe-signature": _stripe_signature(payload, webhook_secret)},
    )

    assert response.status_code == 200, response.text
    db.refresh(user)
    assert user.stripe_subscription_id == "sub_test"
    assert user.stripe_subscription_status == "active"
    assert user.stripe_price_id == "price_test"
    assert user.stripe_subscription_current_period_end is not None


def test_webhook_rejects_invalid_signature(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "whsec_test")

    response = client.post(
        f"{settings.API_V1_STR}/billing/stripe/webhook",
        content=b'{"type":"invoice.paid","data":{"object":{}}}',
        headers={"stripe-signature": "t=1,v1=invalid"},
    )

    assert response.status_code == 400
