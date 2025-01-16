from typing import cast

import requests
import stripe

from ee.onyx.configs.app_configs import STRIPE_PRICE_ID
from ee.onyx.configs.app_configs import STRIPE_SECRET_KEY
from ee.onyx.server.tenants.access import generate_data_plane_token
from onyx.configs.app_configs import CONTROL_PLANE_API_BASE_URL
from onyx.utils.logger import setup_logger

stripe.api_key = STRIPE_SECRET_KEY

logger = setup_logger()


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


def fetch_billing_information(tenant_id: str) -> dict:
    logger.info("Fetching billing information")
    token = generate_data_plane_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = f"{CONTROL_PLANE_API_BASE_URL}/billing-information"
    params = {"tenant_id": tenant_id}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    billing_info = response.json()
    return billing_info


def register_tenant_users(tenant_id: str, number_of_users: int) -> stripe.Subscription:
    """
    Send a request to the control service to register the number of users for a tenant.
    """

    if not STRIPE_PRICE_ID:
        raise Exception("STRIPE_PRICE_ID is not set")

    response = fetch_tenant_stripe_information(tenant_id)
    stripe_subscription_id = cast(str, response.get("stripe_subscription_id"))

    subscription = stripe.Subscription.retrieve(stripe_subscription_id)
    updated_subscription = stripe.Subscription.modify(
        stripe_subscription_id,
        items=[
            {
                "id": subscription["items"]["data"][0].id,
                "price": STRIPE_PRICE_ID,
                "quantity": number_of_users,
            }
        ],
        metadata={"tenant_id": str(tenant_id)},
    )
    return updated_subscription
