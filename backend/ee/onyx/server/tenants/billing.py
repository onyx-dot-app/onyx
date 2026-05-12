from enum import Enum as PyEnum
from typing import cast
from typing import Literal

import requests
import stripe
from sqlalchemy.orm import Session

from ee.onyx.configs.app_configs import STRIPE_SECRET_KEY
from ee.onyx.db.license import acquire_seat_lock
from ee.onyx.server.tenants.access import generate_data_plane_token
from ee.onyx.server.tenants.models import BillingInformation
from ee.onyx.server.tenants.models import SubscriptionStatusResponse
from onyx.configs.app_configs import CONTROL_PLANE_API_BASE_URL
from onyx.db.engine.sql_engine import get_session_with_shared_schema
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.usage_limits import is_tenant_on_trial_fn
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

stripe.api_key = STRIPE_SECRET_KEY

logger = setup_logger()


class SeatBillingDeclineReason(str, PyEnum):
    CARD_DECLINED = "card_declined"
    SUBSCRIPTION_INVALID = "subscription_invalid"


def fetch_stripe_checkout_session(
    tenant_id: str,
    billing_period: Literal["monthly", "annual"] = "monthly",
    seats: int | None = None,
) -> str:
    token = generate_data_plane_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = f"{CONTROL_PLANE_API_BASE_URL}/create-checkout-session"
    payload = {
        "tenant_id": tenant_id,
        "billing_period": billing_period,
        "seats": seats,
    }
    response = requests.post(url, headers=headers, json=payload)
    if not response.ok:
        try:
            data = response.json()
            error_msg = (
                data.get("error")
                or f"Request failed with status {response.status_code}"
            )
        except (ValueError, requests.exceptions.JSONDecodeError):
            error_msg = f"Request failed with status {response.status_code}: {response.text[:200]}"
        raise Exception(error_msg)
    data = response.json()
    if data.get("error"):
        raise Exception(data["error"])
    return data["sessionId"]


def fetch_tenant_stripe_information(tenant_id: str) -> dict:
    token = generate_data_plane_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = f"{CONTROL_PLANE_API_BASE_URL}/tenant-stripe-information"
    params = {"tenant_id": tenant_id}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()


def fetch_billing_information(
    tenant_id: str,
) -> BillingInformation | SubscriptionStatusResponse:
    token = generate_data_plane_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = f"{CONTROL_PLANE_API_BASE_URL}/billing-information"
    params = {"tenant_id": tenant_id}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()

    response_data = response.json()

    # Check if the response indicates no subscription
    if (
        isinstance(response_data, dict)
        and "subscribed" in response_data
        and not response_data["subscribed"]
    ):
        return SubscriptionStatusResponse(**response_data)

    # Otherwise, parse as BillingInformation
    return BillingInformation(**response_data)


def fetch_customer_portal_session(tenant_id: str, return_url: str | None = None) -> str:
    """
    Fetch a Stripe customer portal session URL from the control plane.
    NOTE: This is currently only used for multi-tenant (cloud) deployments.
    Self-hosted proxy endpoints will be added in a future phase.
    """
    token = generate_data_plane_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = f"{CONTROL_PLANE_API_BASE_URL}/create-customer-portal-session"
    payload = {"tenant_id": tenant_id}
    if return_url:
        payload["return_url"] = return_url
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()["url"]


def register_tenant_users(
    tenant_id: str,
    number_of_users: int,
    idempotency_key: str | None = None,
) -> stripe.Subscription:
    """
    Update the number of seats for a tenant's subscription.
    Preserves the existing price (monthly, annual, or grandfathered).
    """
    response = fetch_tenant_stripe_information(tenant_id)
    stripe_subscription_id = cast(str, response.get("stripe_subscription_id"))

    subscription = stripe.Subscription.retrieve(stripe_subscription_id)
    subscription_item = subscription["items"]["data"][0]

    # Use existing price to preserve the customer's current plan
    current_price_id = subscription_item.price.id

    items = [
        {
            "id": subscription_item.id,
            "price": current_price_id,
            "quantity": number_of_users,
        }
    ]
    metadata = {"tenant_id": str(tenant_id)}

    if idempotency_key is None:
        return stripe.Subscription.modify(
            stripe_subscription_id,
            items=items,
            metadata=metadata,
        )
    return stripe.Subscription.modify(
        stripe_subscription_id,
        items=items,
        metadata=metadata,
        idempotency_key=idempotency_key,
    )


def _seat_billing_idempotency_key(tenant_id: str, target_quantity: int) -> str:
    """Stable per-(tenant, target) key so HTTP retries don't double-bill."""
    return f"seat-bill-{tenant_id}-{target_quantity}"


def attempt_seat_billing_increase(
    tenant_id: str,
    target_quantity: int,
) -> tuple[bool, SeatBillingDeclineReason | None]:
    """Set Stripe seat quantity to ``target_quantity``.

    On decline returns ``(False, SeatBillingDeclineReason.X)``. Other
    Stripe errors propagate (fail closed). No-op when current quantity
    is already ``>= target_quantity``.

    NOT a concurrency serializer — the idempotency key only dedupes
    HTTP retries. For cap enforcement under concurrency call
    ``enforce_cloud_seat_limit(db_session=...)``, which holds the
    per-tenant advisory lock across {count, bill, insert}.
    """
    try:
        response = fetch_tenant_stripe_information(tenant_id)
        stripe_subscription_id = cast(str, response.get("stripe_subscription_id"))
        if not stripe_subscription_id:
            return False, SeatBillingDeclineReason.SUBSCRIPTION_INVALID

        subscription = stripe.Subscription.retrieve(stripe_subscription_id)
        subscription_item = subscription["items"]["data"][0]
        current_quantity = int(subscription_item.get("quantity", 0))
        if current_quantity >= target_quantity:
            return True, None

        register_tenant_users(
            tenant_id,
            target_quantity,
            idempotency_key=_seat_billing_idempotency_key(tenant_id, target_quantity),
        )
        return True, None
    except stripe.CardError as e:
        logger.warning(
            "Card declined while billing seat increase for tenant %s: %s",
            tenant_id,
            e.user_message or str(e),
        )
        return False, SeatBillingDeclineReason.CARD_DECLINED
    except stripe.InvalidRequestError as e:
        logger.warning(
            "Stripe rejected seat-billing increase for tenant %s: %s",
            tenant_id,
            str(e),
        )
        return False, SeatBillingDeclineReason.SUBSCRIPTION_INVALID


def enforce_cloud_seat_limit(
    seats_needed: int = 1,
    tenant_id: str | None = None,
    db_session: Session | None = None,
) -> None:
    """Cloud signup-time seat enforcer. Auto-bills via Stripe; raises
    ``OnyxError(SEAT_LIMIT_EXCEEDED)`` on decline.

    Pass ``db_session`` (shared-schema) to hold the advisory lock across
    {count, bill, caller's insert} — the only mode that closes the
    cloud TOCTOU. Without it, lock is held only across {count, bill}.

    Trial tenants short-circuit; ``NUM_FREE_TRIAL_USER_INVITES`` is the
    only trial backstop.
    """
    tenant = tenant_id or get_current_tenant_id()
    if is_tenant_on_trial_fn(tenant):
        return

    # Local import avoids circular import with user_mapping (which calls
    # back into this module from add_users_to_tenant).
    from ee.onyx.server.tenants.user_mapping import get_tenant_count

    if db_session is not None:
        acquire_seat_lock(db_session, tenant)
        current_count = get_tenant_count(tenant)
        target_quantity = current_count + seats_needed
        success, reason = attempt_seat_billing_increase(tenant, target_quantity)
    else:
        with get_session_with_shared_schema() as locked_session:
            acquire_seat_lock(locked_session, tenant)
            current_count = get_tenant_count(tenant)
            target_quantity = current_count + seats_needed
            success, reason = attempt_seat_billing_increase(tenant, target_quantity)
            locked_session.commit()

    if success:
        return

    if reason == SeatBillingDeclineReason.CARD_DECLINED:
        message = (
            "Could not add a new seat: your payment method was declined. "
            "Please update your billing details and try again."
        )
    elif reason == SeatBillingDeclineReason.SUBSCRIPTION_INVALID:
        message = (
            "Could not add a new seat: this tenant does not have an active "
            "subscription. Please contact your Onyx administrator."
        )
    else:
        message = "Could not add a new seat (billing declined)."

    raise OnyxError(OnyxErrorCode.SEAT_LIMIT_EXCEEDED, message)
