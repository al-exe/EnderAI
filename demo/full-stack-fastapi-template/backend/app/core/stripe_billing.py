import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import httpx
from fastapi import HTTPException, status

from app.core.config import settings


class StripeBillingError(Exception):
    def __init__(self, message: str, status_code: int = status.HTTP_502_BAD_GATEWAY):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _string_id(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        identifier = value.get("id")
        return identifier if isinstance(identifier, str) else None
    return None


def datetime_from_stripe_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, int | float):
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


def get_subscription_price_id(subscription: dict[str, Any]) -> str | None:
    items = subscription.get("items")
    if not isinstance(items, dict):
        return None
    data = items.get("data")
    if not isinstance(data, list) or not data:
        return None
    first_item = data[0]
    if not isinstance(first_item, dict):
        return None
    price = first_item.get("price")
    if not isinstance(price, dict):
        return None
    return _string_id(price)


def get_subscription_item_id(subscription: dict[str, Any]) -> str | None:
    items = subscription.get("items")
    if not isinstance(items, dict):
        return None
    data = items.get("data")
    if not isinstance(data, list) or not data:
        return None
    first_item = data[0]
    if not isinstance(first_item, dict):
        return None
    return _string_id(first_item)


def get_subscription_period_end(subscription: dict[str, Any]) -> datetime | None:
    top_level_period_end = datetime_from_stripe_timestamp(
        subscription.get("current_period_end")
    )
    if top_level_period_end:
        return top_level_period_end

    items = subscription.get("items")
    if not isinstance(items, dict):
        return None
    data = items.get("data")
    if not isinstance(data, list):
        return None
    period_ends: list[int] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        period_end = item.get("current_period_end")
        if isinstance(period_end, int):
            period_ends.append(period_end)
    if not period_ends:
        return None
    return datetime_from_stripe_timestamp(max(period_ends))


def get_invoice_subscription_id(invoice: dict[str, Any]) -> str | None:
    subscription_id = _string_id(invoice.get("subscription"))
    if subscription_id:
        return subscription_id

    parent = invoice.get("parent")
    if not isinstance(parent, dict):
        return None
    subscription_details = parent.get("subscription_details")
    if not isinstance(subscription_details, dict):
        return None
    return _string_id(subscription_details.get("subscription"))


def verify_webhook_signature(payload: bytes, signature_header: str) -> dict[str, Any]:
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe webhook secret is not configured",
        )
    values: dict[str, list[str]] = {}
    for part in signature_header.split(","):
        key, separator, value = part.partition("=")
        if separator:
            values.setdefault(key, []).append(value)

    timestamp_values = values.get("t", [])
    signatures = values.get("v1", [])
    if not timestamp_values or not signatures:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature header")

    try:
        timestamp = int(timestamp_values[0])
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid Stripe signature timestamp"
        )

    if abs(time.time() - timestamp) > 300:
        raise HTTPException(status_code=400, detail="Expired Stripe webhook signature")

    signed_payload = f"{timestamp}.".encode() + payload
    expected_signature = hmac.new(
        settings.STRIPE_WEBHOOK_SECRET.encode(),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    if not any(
        hmac.compare_digest(expected_signature, signature) for signature in signatures
    ):
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature")

    try:
        event = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook payload")
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook event")
    return event


class StripeBillingClient:
    def _require_secret_key(self) -> str:
        if not settings.STRIPE_SECRET_KEY:
            raise StripeBillingError(
                "Stripe secret key is not configured",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return settings.STRIPE_SECRET_KEY

    def _request(
        self, path: str, data: dict[str, Any] | None = None, *, method: str = "POST"
    ) -> dict[str, Any]:
        secret_key = self._require_secret_key()
        request_method = method.upper()
        request_kwargs: dict[str, Any] = {
            "url": urljoin(settings.STRIPE_API_BASE_URL.rstrip("/") + "/", path),
            "headers": {"Authorization": f"Bearer {secret_key}"},
            "timeout": 20,
        }
        if request_method == "GET":
            request_kwargs["params"] = data
        else:
            request_kwargs["data"] = data or {}
        try:
            response = httpx.request(request_method, **request_kwargs)
        except httpx.HTTPError as exc:
            raise StripeBillingError("Stripe request failed") from exc

        if response.status_code >= 400:
            detail = "Stripe request failed"
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    detail = error["message"]
            raise StripeBillingError(detail, status.HTTP_502_BAD_GATEWAY)

        try:
            payload = response.json()
        except ValueError as exc:
            raise StripeBillingError("Stripe returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise StripeBillingError("Stripe returned an invalid response")
        return payload

    def create_customer(
        self,
        *,
        email: str,
        name: str | None,
        user_id: str,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "email": email,
            "metadata[user_id]": user_id,
        }
        if name:
            data["name"] = name
        return self._request("/v1/customers", data)

    def retrieve_subscription(self, *, subscription_id: str) -> dict[str, Any]:
        return self._request(f"/v1/subscriptions/{subscription_id}", method="GET")

    def update_subscription_price(
        self,
        *,
        subscription_id: str,
        user_id: str,
        price_id: str,
    ) -> dict[str, Any]:
        subscription = self.retrieve_subscription(subscription_id=subscription_id)
        item_id = get_subscription_item_id(subscription)
        if not item_id:
            raise StripeBillingError("Stripe subscription item was not found")

        return self._request(
            f"/v1/subscriptions/{subscription_id}",
            {
                "items[0][id]": item_id,
                "items[0][price]": price_id,
                "payment_behavior": "allow_incomplete",
                "proration_behavior": "create_prorations",
                "metadata[user_id]": user_id,
                "metadata[taskforce_price_id]": price_id,
            },
        )

    def create_checkout_session(
        self,
        *,
        customer_id: str,
        user_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
    ) -> dict[str, Any]:
        return self._request(
            "/v1/checkout/sessions",
            {
                "mode": "subscription",
                "customer": customer_id,
                "client_reference_id": user_id,
                "line_items[0][price]": price_id,
                "line_items[0][quantity]": 1,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata[user_id]": user_id,
                "metadata[taskforce_price_id]": price_id,
                "subscription_data[metadata][user_id]": user_id,
                "subscription_data[metadata][taskforce_price_id]": price_id,
            },
        )

    def create_billing_portal_session(
        self,
        *,
        customer_id: str,
        return_url: str,
    ) -> dict[str, Any]:
        return self._request(
            "/v1/billing_portal/sessions",
            {
                "customer": customer_id,
                "return_url": return_url,
            },
        )
