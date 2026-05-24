"""Regression test for Stripe plan-upgrade webhook replay (TF-193).

DEMO BRANCH ONLY — see DEMO_BRANCH.md at repo root.

This test asserts that duplicate delivery of a
``customer.subscription.updated`` plan-upgrade webhook does NOT
re-fire the fulfillment side effect.

On the demo branch (broken):
  - `record_stripe_event_or_skip` is called AFTER `_dispatch_event`
  - Both deliveries pass the dispatch block before either writes the
    WAL row, so fulfillment runs twice
  - This test FAILS on the second assertion (call_count == 2)

After the demo fix:
  - `record_stripe_event_or_skip` is called BEFORE dispatch
  - Duplicate delivery short-circuits with a 200 + dedup log line
  - Fulfillment runs exactly once
  - This test PASSES
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings


def _sign_payload(payload: bytes, secret: str) -> str:
    """Mimic Stripe's webhook signature header (t= + v1= scheme)."""

    timestamp = str(int(time.time()))
    signed = f"{timestamp}.".encode() + payload
    signature = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def _plan_upgrade_event(event_id: str = "evt_test_plan_upgrade_demo") -> dict[str, Any]:
    """Realistic-shape `customer.subscription.updated` plan-upgrade payload."""

    return {
        "id": event_id,
        "type": "customer.subscription.updated",
        "livemode": False,
        "data": {
            "object": {
                "id": "sub_test_demo",
                "status": "active",
                "current_period_end": int(time.time()) + 30 * 86400,
                "items": {
                    "data": [
                        {
                            "id": "si_test_demo",
                            "price": {"id": "price_test_pro"},
                        }
                    ]
                },
                "metadata": {
                    "user_id": "user-demo",
                    "taskforce_price_id": "price_test_pro",
                },
            }
        },
    }


def test_plan_upgrade_webhook_retry_short_circuits_before_dispatch(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    """Duplicate plan-upgrade webhook delivery must not re-fire fulfillment.

    Mocks `_handle_subscription_event` (the plan-upgrade fulfillment
    path) to track how many times it ran. On the broken demo branch
    both deliveries pass dispatch → call_count == 2 (FAILS the
    assertion). After moving `record_stripe_event_or_skip` ahead of
    dispatch with an early return, call_count == 1.
    """

    # Webhook signature requires the secret to be set in settings.
    monkeypatch.setattr(
        settings, "STRIPE_WEBHOOK_SECRET", "whsec_test_demo_branch"
    )

    event = _plan_upgrade_event()
    payload = json.dumps(event).encode("utf-8")
    sig = _sign_payload(payload, "whsec_test_demo_branch")

    headers = {
        "stripe-signature": sig,
        "content-type": "application/json",
    }

    url = f"{settings.API_V1_STR}/billing/stripe/webhook"

    with patch(
        "app.api.routes.billing._handle_subscription_event"
    ) as mock_handler:
        first = client.post(url, content=payload, headers=headers)
        assert first.status_code == 200, first.text

        second = client.post(url, content=payload, headers=headers)
        assert second.status_code == 200, second.text

        # The load-bearing assertion: fulfillment must run EXACTLY ONCE
        # across both deliveries, regardless of which response message
        # comes back. On the broken demo branch this fails with
        # call_count == 2.
        assert mock_handler.call_count == 1, (
            "Plan-upgrade fulfillment ran "
            f"{mock_handler.call_count} times across duplicate "
            "webhook deliveries. The WAL check must short-circuit "
            "BEFORE _dispatch_event."
        )
