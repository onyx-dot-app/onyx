"""Billing API endpoints for cloud multi-tenant deployments.

DEPRECATED: These /tenants/* billing endpoints are being replaced by /admin/billing/*
which provides a unified API for both self-hosted and cloud deployments.

TODO(ENG-3533): Migrate frontend to use /admin/billing/* endpoints and remove this file.
https://linear.app/onyx-app/issue/ENG-3533/migrate-tenantsbilling-adminbilling

Current endpoints to migrate:
- GET  /tenants/billing-information     -> GET  /admin/billing/information
- POST /tenants/create-customer-portal-session -> POST /admin/billing/portal-session
- POST /tenants/create-subscription-session    -> POST /admin/billing/checkout-session
- GET  /tenants/stripe-publishable-key  -> (keep as-is, shared endpoint)

The routes the control plane calls (product gating, tier update) live in
control_plane_api.py. The playground mounts those and not this file.
"""

import asyncio

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ee.onyx.server.billing.api import update_seats as _admin_update_seats
from ee.onyx.server.billing.models import SeatUpdateRequest, SeatUpdateResponse
from ee.onyx.server.tenants.billing import (
    fetch_billing_information,
    fetch_customer_portal_session,
    fetch_stripe_checkout_session,
)
from ee.onyx.server.tenants.models import (
    BillingInformation,
    CreateCheckoutSessionRequest,
    CreateSubscriptionSessionRequest,
    StripePublishableKeyResponse,
    SubscriptionSessionResponse,
    SubscriptionStatusResponse,
)
from onyx.auth.permissions import require_permission
from onyx.auth.users import User
from onyx.configs.app_configs import (
    STRIPE_PUBLISHABLE_KEY_OVERRIDE,
    STRIPE_PUBLISHABLE_KEY_URL,
    WEB_DOMAIN,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    get_current_tenant_id,
)

logger = setup_logger()

router = APIRouter(prefix="/tenants")

# Cache for Stripe publishable key to avoid hitting S3 on every request
_stripe_publishable_key_cache: str | None = None
_stripe_key_lock = asyncio.Lock()


@router.get("/billing-information")
async def billing_information(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> BillingInformation | SubscriptionStatusResponse:
    logger.info("Fetching billing information")
    tenant_id = get_current_tenant_id()
    return fetch_billing_information(tenant_id)


@router.post("/seats/update")
async def update_seats(
    request: SeatUpdateRequest,
    user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SeatUpdateResponse:
    """Cloud alias for /admin/billing/seats/update (ENG-3533 migration)."""
    return await _admin_update_seats(request, user, db_session)


@router.post("/create-customer-portal-session")
async def create_customer_portal_session(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> dict:
    """Create a Stripe customer portal session via the control plane."""
    tenant_id = get_current_tenant_id()
    return_url = f"{WEB_DOMAIN}/admin/billing"

    try:
        portal_url = fetch_customer_portal_session(tenant_id, return_url)
        return {"stripe_customer_portal_url": portal_url}
    except OnyxError:
        raise
    except Exception:
        logger.exception("Failed to create customer portal session")
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "Failed to create customer portal session",
        )


@router.post("/create-checkout-session")
async def create_checkout_session(
    request: CreateCheckoutSessionRequest | None = None,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> dict:
    """Create a Stripe checkout session via the control plane."""
    tenant_id = get_current_tenant_id()
    billing_period = request.billing_period if request else "monthly"
    seats = request.seats if request else None

    try:
        result = fetch_stripe_checkout_session(tenant_id, billing_period, seats)
        return {"stripe_checkout_url": result.url}
    except OnyxError:
        raise
    except Exception:
        logger.exception("Failed to create checkout session")
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "Failed to create checkout session",
        )


@router.post("/create-subscription-session")
async def create_subscription_session(
    request: CreateSubscriptionSessionRequest | None = None,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> SubscriptionSessionResponse:
    try:
        tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()
        if not tenant_id:
            raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, "Tenant ID not found")

        billing_period = request.billing_period if request else "monthly"
        result = fetch_stripe_checkout_session(tenant_id, billing_period)
        return SubscriptionSessionResponse(
            sessionId=result.session_id,
            url=result.url,
            requires_payment_method_update=result.requires_payment_method_update,
        )

    except OnyxError:
        raise
    except Exception:
        logger.exception("Failed to create subscription session")
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "Failed to create subscription session",
        )


@router.get("/stripe-publishable-key")
async def get_stripe_publishable_key() -> StripePublishableKeyResponse:
    """
    Fetch the Stripe publishable key.
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
                raise OnyxError(
                    OnyxErrorCode.INTERNAL_ERROR,
                    "Invalid Stripe publishable key format",
                )
            _stripe_publishable_key_cache = key
            return StripePublishableKeyResponse(publishable_key=key)

        # Fall back to S3 bucket
        if not STRIPE_PUBLISHABLE_KEY_URL:
            raise OnyxError(
                OnyxErrorCode.INTERNAL_ERROR,
                "Stripe publishable key is not configured",
            )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(STRIPE_PUBLISHABLE_KEY_URL)
                response.raise_for_status()
                key = response.text.strip()

                # Validate key format
                if not key.startswith("pk_"):
                    raise OnyxError(
                        OnyxErrorCode.INTERNAL_ERROR,
                        "Invalid Stripe publishable key format",
                    )

                _stripe_publishable_key_cache = key
                return StripePublishableKeyResponse(publishable_key=key)
        except httpx.HTTPError:
            raise OnyxError(
                OnyxErrorCode.INTERNAL_ERROR,
                "Failed to fetch Stripe publishable key",
            )
