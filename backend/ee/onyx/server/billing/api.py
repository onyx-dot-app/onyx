"""Unified Billing API endpoints.

These endpoints provide Stripe billing functionality for both cloud and
self-hosted deployments. The service layer routes requests appropriately:

- Self-hosted: Routes through cloud data plane proxy
  Flow: Backend /admin/billing/* → Cloud DP /proxy/* → Control plane

- Cloud (MULTI_TENANT): Routes directly to control plane
  Flow: Backend /admin/billing/* → Control plane

License claiming is handled separately by /license/claim endpoint (self-hosted only).

Migration Note (ENG-3533):
This /admin/billing/* API replaces the older /tenants/* billing endpoints:
- /tenants/billing-information            -> /admin/billing/billing-information
- /tenants/create-customer-portal-session -> /admin/billing/create-customer-portal-session
- /tenants/create-subscription-session    -> /admin/billing/create-checkout-session
- /tenants/stripe-publishable-key         -> /admin/billing/stripe-publishable-key

See: https://linear.app/onyx-app/issue/ENG-3533/migrate-tenantsbilling-adminbilling
"""

import asyncio

import httpx
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ee.onyx.auth.users import current_admin_user
from ee.onyx.db.license import get_license
from ee.onyx.server.billing.models import BillingInformationResponse
from ee.onyx.server.billing.models import CreateCheckoutSessionRequest
from ee.onyx.server.billing.models import CreateCheckoutSessionResponse
from ee.onyx.server.billing.models import CreateCustomerPortalSessionRequest
from ee.onyx.server.billing.models import CreateCustomerPortalSessionResponse
from ee.onyx.server.billing.models import SeatUpdateRequest
from ee.onyx.server.billing.models import SeatUpdateResponse
from ee.onyx.server.billing.models import StripePublishableKeyResponse
from ee.onyx.server.billing.models import SubscriptionStatusResponse
from ee.onyx.server.billing.service import BillingServiceError
from ee.onyx.server.billing.service import (
    create_checkout_session as create_checkout_service,
)
from ee.onyx.server.billing.service import (
    create_customer_portal_session as create_portal_service,
)
from ee.onyx.server.billing.service import (
    get_billing_information as get_billing_service,
)
from ee.onyx.server.billing.service import update_seat_count as update_seat_service
from onyx.auth.users import User
from onyx.configs.app_configs import STRIPE_PUBLISHABLE_KEY_OVERRIDE
from onyx.configs.app_configs import STRIPE_PUBLISHABLE_KEY_URL
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session
from onyx.redis.redis_pool import get_shared_redis_client
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/admin/billing")

# Cache for Stripe publishable key to avoid hitting S3 on every request
_stripe_publishable_key_cache: str | None = None
_stripe_key_lock = asyncio.Lock()

# Redis key for billing circuit breaker (self-hosted only)
# When set, billing requests to Stripe are disabled until user manually retries
BILLING_CIRCUIT_BREAKER_KEY = "billing_circuit_open"
# Circuit breaker auto-expires after 1 hour (user can manually retry sooner)
BILLING_CIRCUIT_BREAKER_TTL_SECONDS = 3600


def _is_billing_circuit_open() -> bool:
    """Check if the billing circuit breaker is open (self-hosted only)."""
    if MULTI_TENANT:
        return False
    try:
        redis_client = get_shared_redis_client()
        is_open = bool(redis_client.exists(BILLING_CIRCUIT_BREAKER_KEY))
        logger.info(
            f"Circuit breaker check: key={BILLING_CIRCUIT_BREAKER_KEY}, is_open={is_open}"
        )
        return is_open
    except Exception as e:
        logger.error(f"Failed to check circuit breaker: {e}")
        return False


def _open_billing_circuit() -> None:
    """Open the billing circuit breaker after a failure (self-hosted only)."""
    if MULTI_TENANT:
        return
    try:
        redis_client = get_shared_redis_client()
        # Use set() with ex parameter instead of setex() because setex is not
        # in TenantRedis's methods_to_wrap list (so key wouldn't be prefixed)
        redis_client.set(
            BILLING_CIRCUIT_BREAKER_KEY,
            "1",
            ex=BILLING_CIRCUIT_BREAKER_TTL_SECONDS,
        )
        # Verify it was set
        exists = redis_client.exists(BILLING_CIRCUIT_BREAKER_KEY)
        logger.warning(
            f"Billing circuit breaker opened (TTL={BILLING_CIRCUIT_BREAKER_TTL_SECONDS}s, "
            f"verified={exists}). Stripe billing requests are disabled until manually reset."
        )
    except Exception as e:
        logger.error(f"Failed to open circuit breaker: {e}")


def _close_billing_circuit() -> None:
    """Close the billing circuit breaker (re-enable Stripe requests)."""
    if MULTI_TENANT:
        return
    try:
        redis_client = get_shared_redis_client()
        redis_client.delete(BILLING_CIRCUIT_BREAKER_KEY)
        logger.info(
            "Billing circuit breaker closed. Stripe billing requests re-enabled."
        )
    except Exception as e:
        logger.error(f"Failed to close circuit breaker: {e}")


def _get_license_data(db_session: Session) -> str | None:
    """Get license data from database if exists (self-hosted only)."""
    if MULTI_TENANT:
        return None
    license_record = get_license(db_session)
    return license_record.license_data if license_record else None


def _get_tenant_id() -> str | None:
    """Get tenant ID for cloud deployments."""
    if MULTI_TENANT:
        return get_current_tenant_id()
    return None


@router.post("/create-checkout-session")
async def create_checkout_session(
    request: CreateCheckoutSessionRequest | None = None,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> CreateCheckoutSessionResponse:
    """Create a Stripe checkout session for new subscription or renewal.

    For new customers, no license/tenant is required.
    For renewals, existing license (self-hosted) or tenant_id (cloud) is used.

    After checkout completion:
    - Self-hosted: Use /license/claim to retrieve the license
    - Cloud: Subscription is automatically activated
    """
    license_data = _get_license_data(db_session)
    tenant_id = _get_tenant_id()
    billing_period = request.billing_period if request else "monthly"
    seats = request.seats if request else None
    email = request.email if request else None

    # Build redirect URL for after checkout completion
    redirect_url = f"{WEB_DOMAIN}/admin/billing?checkout=success"

    try:
        return await create_checkout_service(
            billing_period=billing_period,
            seats=seats,
            email=email,
            license_data=license_data,
            redirect_url=redirect_url,
            tenant_id=tenant_id,
        )
    except BillingServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/create-customer-portal-session")
async def create_customer_portal_session(
    request: CreateCustomerPortalSessionRequest | None = None,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> CreateCustomerPortalSessionResponse:
    """Create a Stripe customer portal session for managing subscription.

    Requires existing license (self-hosted) or active tenant (cloud).
    """
    license_data = _get_license_data(db_session)
    tenant_id = _get_tenant_id()

    # Self-hosted requires license
    if not MULTI_TENANT and not license_data:
        raise HTTPException(status_code=400, detail="No license found")

    return_url = request.return_url if request else f"{WEB_DOMAIN}/admin/billing"

    try:
        return await create_portal_service(
            license_data=license_data,
            return_url=return_url,
            tenant_id=tenant_id,
        )
    except BillingServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/billing-information")
async def get_billing_information(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> BillingInformationResponse | SubscriptionStatusResponse:
    """Get billing information for the current subscription.

    Returns subscription status and details from Stripe.
    For self-hosted: If the circuit breaker is open (previous failure),
    returns a 503 error without making the request.
    """
    license_data = _get_license_data(db_session)
    tenant_id = _get_tenant_id()

    # Self-hosted without license = no subscription
    if not MULTI_TENANT and not license_data:
        return SubscriptionStatusResponse(subscribed=False)

    # Check circuit breaker (self-hosted only)
    if _is_billing_circuit_open():
        raise HTTPException(
            status_code=503,
            detail="Stripe connection temporarily disabled. Click 'Connect to Stripe' to retry.",
        )

    try:
        return await get_billing_service(
            license_data=license_data,
            tenant_id=tenant_id,
        )
    except BillingServiceError as e:
        # Open circuit breaker on connection failures (self-hosted only)
        if e.status_code in (502, 503, 504):
            _open_billing_circuit()
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/seats/update")
async def update_seats(
    request: SeatUpdateRequest,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> SeatUpdateResponse:
    """Update the seat count for the current subscription.

    Handles Stripe proration and license regeneration via control plane.
    For self-hosted, auto-stores the regenerated license if returned.
    """
    license_data = _get_license_data(db_session)
    tenant_id = _get_tenant_id()

    # Self-hosted requires license
    if not MULTI_TENANT and not license_data:
        raise HTTPException(status_code=400, detail="No license found")

    try:
        result = await update_seat_service(
            new_seat_count=request.new_seat_count,
            license_data=license_data,
            tenant_id=tenant_id,
        )

        # Note: Don't store license here - the control plane may still be processing
        # the subscription update. The frontend should call /license/claim after a
        # short delay to get the freshly generated license.

        return result
    except BillingServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/stripe-publishable-key")
async def get_stripe_publishable_key() -> StripePublishableKeyResponse:
    """Fetch the Stripe publishable key.

    Priority: env var override (for testing) > S3 bucket (production).
    This endpoint is public (no auth required) since publishable keys are safe to expose.
    The key is cached in memory to avoid hitting S3 on every request.
    """
    global _stripe_publishable_key_cache

    # Fast path: return cached value without lock
    if _stripe_publishable_key_cache:
        return StripePublishableKeyResponse(
            publishable_key=_stripe_publishable_key_cache
        )

    # Use lock to prevent concurrent S3 requests
    async with _stripe_key_lock:
        # Double-check after acquiring lock (another request may have populated cache)
        if _stripe_publishable_key_cache:
            return StripePublishableKeyResponse(
                publishable_key=_stripe_publishable_key_cache
            )

        # Check for env var override first (for local testing with pk_test_* keys)
        if STRIPE_PUBLISHABLE_KEY_OVERRIDE:
            key = STRIPE_PUBLISHABLE_KEY_OVERRIDE.strip()
            if not key.startswith("pk_"):
                raise HTTPException(
                    status_code=500,
                    detail="Invalid Stripe publishable key format",
                )
            _stripe_publishable_key_cache = key
            return StripePublishableKeyResponse(publishable_key=key)

        # Fall back to S3 bucket
        if not STRIPE_PUBLISHABLE_KEY_URL:
            raise HTTPException(
                status_code=500,
                detail="Stripe publishable key is not configured",
            )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(STRIPE_PUBLISHABLE_KEY_URL)
                response.raise_for_status()
                key = response.text.strip()

                # Validate key format
                if not key.startswith("pk_"):
                    raise HTTPException(
                        status_code=500,
                        detail="Invalid Stripe publishable key format",
                    )

                _stripe_publishable_key_cache = key
                return StripePublishableKeyResponse(publishable_key=key)
        except httpx.HTTPError:
            raise HTTPException(
                status_code=500,
                detail="Failed to fetch Stripe publishable key",
            )


class ResetConnectionResponse(BaseModel):
    success: bool
    message: str


@router.post("/reset-connection")
async def reset_stripe_connection(
    _: User = Depends(current_admin_user),
) -> ResetConnectionResponse:
    """Reset the Stripe connection circuit breaker.

    Called when user clicks "Connect to Stripe" to retry after a previous failure.
    This clears the circuit breaker flag, allowing billing requests to proceed again.
    Self-hosted only - cloud deployments don't use the circuit breaker.
    """
    if MULTI_TENANT:
        return ResetConnectionResponse(
            success=True,
            message="Circuit breaker not applicable for cloud deployments",
        )

    _close_billing_circuit()
    return ResetConnectionResponse(
        success=True,
        message="Stripe connection reset. Billing requests re-enabled.",
    )
