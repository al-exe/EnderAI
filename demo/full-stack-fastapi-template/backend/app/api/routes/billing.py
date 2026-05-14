import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.stripe_billing import (
    StripeBillingClient,
    StripeBillingError,
    get_invoice_subscription_id,
    get_subscription_period_end,
    get_subscription_price_id,
    verify_webhook_signature,
)
from app.models import BillingSessionPublic, BillingStatusPublic, Message, User

router = APIRouter(prefix="/billing", tags=["billing"])

ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}
stripe_client = StripeBillingClient()


def _settings_url() -> str:
    return f"{settings.FRONTEND_HOST.rstrip('/')}/settings?tab=billing"


def _to_billing_status(user: User) -> BillingStatusPublic:
    status_value = user.stripe_subscription_status
    return BillingStatusPublic(
        has_customer=user.stripe_customer_id is not None,
        subscription_status=status_value,
        subscription_current_period_end=user.stripe_subscription_current_period_end,
        subscription_cancel_at_period_end=(
            user.stripe_subscription_cancel_at_period_end
        ),
        price_id=user.stripe_price_id,
        is_subscription_active=status_value in ACTIVE_SUBSCRIPTION_STATUSES,
    )


def _to_stripe_error(exc: StripeBillingError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


def _get_customer_id(user: User) -> str:
    if not user.stripe_customer_id:
        raise HTTPException(
            status_code=400,
            detail="No Stripe customer exists for this user yet",
        )
    return user.stripe_customer_id


def _object_id(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        identifier = value.get("id")
        return identifier if isinstance(identifier, str) else None
    return None


def _find_user_for_stripe_event(
    session: SessionDep,
    *,
    user_id: str | None = None,
    customer_id: str | None = None,
    subscription_id: str | None = None,
) -> User | None:
    if user_id:
        try:
            user = session.get(User, uuid.UUID(user_id))
        except ValueError:
            user = None
        if user:
            return user

    if subscription_id:
        user = session.exec(
            select(User).where(User.stripe_subscription_id == subscription_id)
        ).first()
        if user:
            return user

    if customer_id:
        return session.exec(
            select(User).where(User.stripe_customer_id == customer_id)
        ).first()

    return None


def _apply_subscription_payload(
    user: User,
    subscription: dict[str, Any],
) -> None:
    subscription_id = _object_id(subscription.get("id"))
    customer_id = _object_id(subscription.get("customer"))
    subscription_status = subscription.get("status")
    if customer_id:
        user.stripe_customer_id = customer_id
    if subscription_id:
        user.stripe_subscription_id = subscription_id
    if isinstance(subscription_status, str):
        user.stripe_subscription_status = subscription_status
        if subscription_status in ACTIVE_SUBSCRIPTION_STATUSES:
            user.is_active = True
    user.stripe_subscription_current_period_end = get_subscription_period_end(
        subscription
    )
    user.stripe_subscription_cancel_at_period_end = bool(
        subscription.get("cancel_at_period_end")
    )
    price_id = get_subscription_price_id(subscription)
    if price_id:
        user.stripe_price_id = price_id


def _handle_checkout_session_completed(
    session: SessionDep,
    checkout_session: dict[str, Any],
) -> None:
    metadata = checkout_session.get("metadata")
    user_id = checkout_session.get("client_reference_id")
    if not isinstance(user_id, str) and isinstance(metadata, dict):
        user_id = metadata.get("user_id")
    user = _find_user_for_stripe_event(
        session,
        user_id=user_id if isinstance(user_id, str) else None,
        customer_id=_object_id(checkout_session.get("customer")),
        subscription_id=_object_id(checkout_session.get("subscription")),
    )
    if not user:
        return

    customer_id = _object_id(checkout_session.get("customer"))
    subscription_id = _object_id(checkout_session.get("subscription"))
    if customer_id:
        user.stripe_customer_id = customer_id
    if subscription_id:
        user.stripe_subscription_id = subscription_id
    if settings.STRIPE_PRICE_ID:
        user.stripe_price_id = settings.STRIPE_PRICE_ID
    session.add(user)


def _handle_subscription_event(
    session: SessionDep,
    subscription: dict[str, Any],
) -> None:
    metadata = subscription.get("metadata")
    user_id = metadata.get("user_id") if isinstance(metadata, dict) else None
    subscription_id = _object_id(subscription.get("id"))
    customer_id = _object_id(subscription.get("customer"))
    user = _find_user_for_stripe_event(
        session,
        user_id=user_id if isinstance(user_id, str) else None,
        customer_id=customer_id,
        subscription_id=subscription_id,
    )
    if not user:
        return

    _apply_subscription_payload(user, subscription)
    session.add(user)


def _handle_invoice_event(
    session: SessionDep,
    invoice: dict[str, Any],
    *,
    status_value: str,
) -> None:
    user = _find_user_for_stripe_event(
        session,
        customer_id=_object_id(invoice.get("customer")),
        subscription_id=get_invoice_subscription_id(invoice),
    )
    if not user:
        return
    user.stripe_subscription_status = status_value
    if status_value in ACTIVE_SUBSCRIPTION_STATUSES:
        user.is_active = True
    session.add(user)


@router.get("/status", response_model=BillingStatusPublic)
def read_billing_status(current_user: CurrentUser) -> BillingStatusPublic:
    return _to_billing_status(current_user)


@router.post("/checkout-session", response_model=BillingSessionPublic)
def create_checkout_session(
    *,
    session: SessionDep,
    current_user: CurrentUser,
) -> BillingSessionPublic:
    if (
        current_user.stripe_subscription_status in ACTIVE_SUBSCRIPTION_STATUSES
        and current_user.stripe_subscription_id
    ):
        raise HTTPException(
            status_code=400,
            detail="This user already has an active Stripe subscription",
        )

    try:
        if current_user.stripe_customer_id:
            customer_id = current_user.stripe_customer_id
        else:
            customer = stripe_client.create_customer(
                email=current_user.email,
                name=current_user.full_name,
                user_id=str(current_user.id),
            )
            customer_id = _object_id(customer.get("id"))
            if not customer_id:
                raise StripeBillingError("Stripe did not return a customer ID")
            current_user.stripe_customer_id = customer_id
            session.add(current_user)
            session.commit()
            session.refresh(current_user)

        checkout_session = stripe_client.create_checkout_session(
            customer_id=customer_id,
            user_id=str(current_user.id),
            success_url=_settings_url(),
            cancel_url=_settings_url(),
        )
    except StripeBillingError as exc:
        raise _to_stripe_error(exc)

    url = checkout_session.get("url")
    if not isinstance(url, str):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Stripe did not return a checkout URL",
        )
    return BillingSessionPublic(url=url)


@router.post("/portal-session", response_model=BillingSessionPublic)
def create_portal_session(
    *,
    current_user: CurrentUser,
) -> BillingSessionPublic:
    try:
        portal_session = stripe_client.create_billing_portal_session(
            customer_id=_get_customer_id(current_user),
            return_url=_settings_url(),
        )
    except StripeBillingError as exc:
        raise _to_stripe_error(exc)

    url = portal_session.get("url")
    if not isinstance(url, str):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Stripe did not return a billing portal URL",
        )
    return BillingSessionPublic(url=url)


@router.post("/stripe/webhook", response_model=Message)
async def receive_stripe_webhook(
    *,
    request: Request,
    session: SessionDep,
) -> Message:
    payload = await request.body()
    signature_header = request.headers.get("stripe-signature")
    if not signature_header:
        raise HTTPException(status_code=400, detail="Missing Stripe signature header")

    event = verify_webhook_signature(payload, signature_header)
    event_type = event.get("type")
    data = event.get("data")
    event_object = data.get("object") if isinstance(data, dict) else None
    if not isinstance(event_type, str) or not isinstance(event_object, dict):
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook event")

    if event_type == "checkout.session.completed":
        _handle_checkout_session_completed(session, event_object)
    elif event_type in {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }:
        _handle_subscription_event(session, event_object)
    elif event_type == "invoice.paid":
        _handle_invoice_event(session, event_object, status_value="active")
    elif event_type == "invoice.payment_failed":
        _handle_invoice_event(session, event_object, status_value="past_due")

    session.commit()
    return Message(message="Stripe webhook processed")
