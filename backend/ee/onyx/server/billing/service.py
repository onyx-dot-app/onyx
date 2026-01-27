"""Service layer for billing operations.

This module provides functions for billing operations that route differently
based on deployment type:

- Self-hosted (not MULTI_TENANT): Routes through cloud data plane proxy
  Flow: Self-hosted backend → Cloud DP /proxy/* → Control plane

- Cloud (MULTI_TENANT): Routes directly to control plane
  Flow: Cloud backend → Control plane
"""

import httpx

from ee.onyx.configs.app_configs import CLOUD_DATA_PLANE_URL
from ee.onyx.server.billing.models import BillingInformationResponse
from ee.onyx.server.billing.models import CreateCheckoutSessionResponse
from ee.onyx.server.billing.models import CreateCustomerPortalSessionResponse
from ee.onyx.server.billing.models import SeatUpdateResponse
from ee.onyx.server.billing.models import SubscriptionStatusResponse
from ee.onyx.server.tenants.access import generate_data_plane_token
from onyx.configs.app_configs import CONTROL_PLANE_API_BASE_URL
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


class BillingServiceError(Exception):
    """Exception raised for billing service errors."""

    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


def _get_proxy_headers(license_data: str | None) -> dict[str, str]:
    """Build headers for proxy requests (self-hosted).

    Self-hosted instances authenticate with their license.
    """
    headers = {"Content-Type": "application/json"}
    if license_data:
        headers["Authorization"] = f"Bearer {license_data}"
    return headers


def _get_direct_headers() -> dict[str, str]:
    """Build headers for direct control plane requests (cloud).

    Cloud instances authenticate with JWT.
    """
    token = generate_data_plane_token()
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


def _get_base_url() -> str:
    """Get the base URL based on deployment type."""
    if MULTI_TENANT:
        return CONTROL_PLANE_API_BASE_URL
    return f"{CLOUD_DATA_PLANE_URL}/proxy"


def _get_headers(license_data: str | None) -> dict[str, str]:
    """Get appropriate headers based on deployment type."""
    if MULTI_TENANT:
        return _get_direct_headers()
    return _get_proxy_headers(license_data)


async def create_checkout_session(
    billing_period: str = "monthly",
    email: str | None = None,
    license_data: str | None = None,
    redirect_url: str | None = None,
    tenant_id: str | None = None,
) -> CreateCheckoutSessionResponse:
    """Create a Stripe checkout session.

    Args:
        billing_period: "monthly" or "annual"
        email: Customer email for new subscriptions
        license_data: Existing license for renewals (self-hosted)
        redirect_url: URL to redirect after successful checkout
        tenant_id: Tenant ID (cloud only, for renewals)

    Returns:
        CreateCheckoutSessionResponse with checkout URL
    """
    base_url = _get_base_url()
    url = f"{base_url}/create-checkout-session"
    headers = _get_headers(license_data)

    body: dict = {"billing_period": billing_period}
    if email:
        body["email"] = email
    if redirect_url:
        body["redirect_url"] = redirect_url
    if tenant_id and MULTI_TENANT:
        body["tenant_id"] = tenant_id

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
            return CreateCheckoutSessionResponse(url=data["url"])

    except httpx.HTTPStatusError as e:
        detail = "Failed to create checkout session"
        try:
            error_data = e.response.json()
            detail = error_data.get("detail", detail)
        except Exception:
            pass
        logger.error(
            f"Checkout session creation failed: {e.response.status_code} - {detail}"
        )
        raise BillingServiceError(detail, e.response.status_code)

    except httpx.RequestError:
        logger.exception("Failed to connect to billing service")
        raise BillingServiceError("Failed to connect to billing service", 502)


async def create_customer_portal_session(
    license_data: str | None = None,
    return_url: str | None = None,
    tenant_id: str | None = None,
) -> CreateCustomerPortalSessionResponse:
    """Create a Stripe customer portal session.

    Args:
        license_data: License blob for authentication (self-hosted)
        return_url: URL to return to after portal session
        tenant_id: Tenant ID (cloud only)

    Returns:
        CreateCustomerPortalSessionResponse with portal URL
    """
    base_url = _get_base_url()
    url = f"{base_url}/create-customer-portal-session"
    headers = _get_headers(license_data)

    body: dict = {}
    if return_url:
        body["return_url"] = return_url
    if tenant_id and MULTI_TENANT:
        body["tenant_id"] = tenant_id

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
            return CreateCustomerPortalSessionResponse(url=data["url"])

    except httpx.HTTPStatusError as e:
        detail = "Failed to create customer portal session"
        try:
            error_data = e.response.json()
            detail = error_data.get("detail", detail)
        except Exception:
            pass
        logger.error(
            f"Portal session creation failed: {e.response.status_code} - {detail}"
        )
        raise BillingServiceError(detail, e.response.status_code)

    except httpx.RequestError:
        logger.exception("Failed to connect to billing service")
        raise BillingServiceError("Failed to connect to billing service", 502)


async def get_billing_information(
    license_data: str | None = None,
    tenant_id: str | None = None,
) -> BillingInformationResponse | SubscriptionStatusResponse:
    """Fetch billing information.

    Args:
        license_data: License blob for authentication (self-hosted)
        tenant_id: Tenant ID (cloud only)

    Returns:
        BillingInformationResponse or SubscriptionStatusResponse if no subscription
    """
    base_url = _get_base_url()
    url = f"{base_url}/billing-information"
    headers = _get_headers(license_data)

    params = {}
    if tenant_id and MULTI_TENANT:
        params["tenant_id"] = tenant_id

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers, params=params or None)
            response.raise_for_status()
            data = response.json()

            # Check if no subscription
            if isinstance(data, dict) and data.get("subscribed") is False:
                return SubscriptionStatusResponse(subscribed=False)

            return BillingInformationResponse(**data)

    except httpx.HTTPStatusError as e:
        detail = "Failed to fetch billing information"
        try:
            error_data = e.response.json()
            detail = error_data.get("detail", detail)
        except Exception:
            pass
        logger.error(f"Billing info fetch failed: {e.response.status_code} - {detail}")
        raise BillingServiceError(detail, e.response.status_code)

    except httpx.RequestError:
        logger.exception("Failed to connect to billing service")
        raise BillingServiceError("Failed to connect to billing service", 502)


async def update_seat_count(
    new_seat_count: int,
    license_data: str | None = None,
    tenant_id: str | None = None,
) -> SeatUpdateResponse:
    """Update the seat count for the current subscription.

    Args:
        new_seat_count: New number of seats
        license_data: License blob for authentication (self-hosted)
        tenant_id: Tenant ID (cloud only)

    Returns:
        SeatUpdateResponse with updated seat information
    """
    base_url = _get_base_url()
    url = f"{base_url}/seats/update"
    headers = _get_headers(license_data)

    body: dict = {"new_seat_count": new_seat_count}
    if tenant_id and MULTI_TENANT:
        body["tenant_id"] = tenant_id

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()

            return SeatUpdateResponse(
                success=data.get("success", False),
                current_seats=data.get("current_seats", 0),
                used_seats=data.get("used_seats", 0),
                message=data.get("message"),
            )

    except httpx.HTTPStatusError as e:
        detail = "Failed to update seat count"
        try:
            error_data = e.response.json()
            detail = error_data.get("detail", detail)
        except Exception:
            pass
        logger.error(f"Seat update failed: {e.response.status_code} - {detail}")
        raise BillingServiceError(detail, e.response.status_code)

    except httpx.RequestError:
        logger.exception("Failed to connect to billing service")
        raise BillingServiceError("Failed to connect to billing service", 502)
