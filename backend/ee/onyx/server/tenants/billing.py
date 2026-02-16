from typing import cast
from typing import Literal

import requests
import stripe

from ee.onyx.configs.app_configs import STRIPE_SECRET_KEY
from ee.onyx.server.tenants.access import generate_data_plane_token
from ee.onyx.server.tenants.models import BillingInformation
from ee.onyx.server.tenants.models import SubscriptionStatusResponse
from onyx.configs.app_configs import CONTROL_PLANE_API_BASE_URL
from onyx.utils.logger import setup_logger

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


def register_tenant_users(tenant_id: str, number_of_users: int) -> stripe.Subscription:
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

    updated_subscription = stripe.Subscription.modify(
        stripe_subscription_id,
        items=[
            {
                "id": subscription_item.id,
                "price": current_price_id,
                "quantity": number_of_users,
            }
        ],
        metadata={"tenant_id": str(tenant_id)},
    )
    return updated_subscription
