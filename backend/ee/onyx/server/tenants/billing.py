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

    When ``idempotency_key`` is provided, retried HTTP requests will not
    double-charge — Stripe deduplicates by the key for ~24 h.
    """
    response = fetch_tenant_stripe_information(tenant_id)
    stripe_subscription_id = cast(str, response.get("stripe_subscription_id"))

    subscription = stripe.Subscription.retrieve(stripe_subscription_id)
    subscription_item = subscription["items"]["data"][0]

    # Use existing price to preserve the customer's current plan
    current_price_id = subscription_item.price.id

    modify_kwargs: dict = {
        "items": [
            {
                "id": subscription_item.id,
                "price": current_price_id,
                "quantity": number_of_users,
            }
        ],
        "metadata": {"tenant_id": str(tenant_id)},
    }
    if idempotency_key is not None:
        modify_kwargs["idempotency_key"] = idempotency_key

    updated_subscription = stripe.Subscription.modify(
        stripe_subscription_id,
        **modify_kwargs,
    )
    return updated_subscription


def _seat_billing_idempotency_key(tenant_id: str, target_quantity: int) -> str:
    """Stable idempotency key for an auto-bill seat increase.

    Same ``(tenant_id, target_quantity)`` produces the same key, so retried
    HTTP requests for the same logical operation are deduplicated by Stripe
    (~24h window).
    """
    return f"seat-bill-{tenant_id}-{target_quantity}"


def attempt_seat_billing_increase(
    tenant_id: str,
    target_quantity: int,
) -> tuple[bool, str | None]:
    """Attempt to set the tenant's Stripe seat quantity to ``target_quantity``.

    Returns ``(True, None)`` on success.

    Returns ``(False, reason)`` for billing-side declines that should reject
    the originating signup:
      - ``"card_declined"`` — Stripe ``CardError`` (insufficient funds, etc.)
      - ``"subscription_invalid"`` — Stripe ``InvalidRequestError`` (e.g.,
        no active subscription for this tenant)

    Other Stripe errors (network, rate-limit, auth, generic API) propagate
    so the caller fails closed rather than silently allowing a signup that
    bypasses billing.

    Idempotent: if the existing Stripe subscription quantity is already
    >= ``target_quantity``, the call is a no-op and returns success without
    reissuing the modify.
    """
    try:
        response = fetch_tenant_stripe_information(tenant_id)
        stripe_subscription_id = cast(str, response.get("stripe_subscription_id"))
        if not stripe_subscription_id:
            return False, "subscription_invalid"

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
        return False, "card_declined"
    except stripe.InvalidRequestError as e:
        logger.warning(
            "Stripe rejected seat-billing increase for tenant %s: %s",
            tenant_id,
            str(e),
        )
        return False, "subscription_invalid"


def enforce_cloud_seat_limit(
    seats_needed: int = 1,
    tenant_id: str | None = None,
    db_session: Session | None = None,
) -> None:
    """Cloud (multi-tenant) signup-time seat enforcer.

    Computes ``target_quantity = current_active_users + seats_needed`` for
    the target tenant and asks the control plane (via Stripe) to bill the
    new total. Raises ``OnyxError(SEAT_LIMIT_EXCEEDED)`` when the auto-bill
    is declined; returns silently on success.

    Concurrency: when ``db_session`` is the shared-schema session that the
    caller will commit after inserting the seat-consuming row(s), the
    ``pg_advisory_xact_lock`` acquired here is held until that commit. Two
    concurrent signups for the same tenant therefore serialize across the
    full count → bill → insert window, closing the TOCTOU gap that the
    Stripe idempotency key alone does not.

    Without ``db_session`` the lock is taken on a short-lived shared-schema
    session and released as soon as the bill returns — best-effort: it
    serializes the count + bill against other holders of the same lock,
    but the caller's later insert is not protected. Use the ``db_session``
    overload from any path that performs the seat-consuming write.

    Trial tenants short-circuit — the trial-invite cap in
    ``bulk_invite_users`` is the only seat backstop for trial accounts.
    """
    tenant = tenant_id or get_current_tenant_id()
    if is_tenant_on_trial_fn(tenant):
        return

    # Local import keeps the billing module loadable on environments that
    # don't have the EE tenant package on the import path (e.g., CE tests
    # that import billing only via ``fetch_ee_implementation_or_noop``).
    from ee.onyx.server.tenants.user_mapping import get_tenant_count

    if db_session is not None:
        # Lock the caller's transaction for this tenant. The lock will be
        # released by the caller's commit/rollback, after their insert.
        acquire_seat_lock(db_session, tenant)
        current_count = get_tenant_count(tenant)
        target_quantity = current_count + seats_needed
        success, reason = attempt_seat_billing_increase(tenant, target_quantity)
    else:
        # Best-effort fallback: serialize the count + bill on a short-lived
        # shared-schema session. The caller's later insert is unprotected.
        with get_session_with_shared_schema() as locked_session:
            acquire_seat_lock(locked_session, tenant)
            current_count = get_tenant_count(tenant)
            target_quantity = current_count + seats_needed
            success, reason = attempt_seat_billing_increase(tenant, target_quantity)
            locked_session.commit()

    if success:
        return

    if reason == "card_declined":
        message = (
            "Could not add a new seat: your payment method was declined. "
            "Please update your billing details and try again."
        )
    elif reason == "subscription_invalid":
        message = (
            "Could not add a new seat: this tenant does not have an active "
            "subscription. Please contact your Onyx administrator."
        )
    else:
        message = "Could not add a new seat (billing declined)."

    raise OnyxError(OnyxErrorCode.SEAT_LIMIT_EXCEEDED, message)
