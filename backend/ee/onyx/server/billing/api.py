"""Billing API endpoints.

These endpoints provide Stripe billing functionality for both cloud and
self-hosted deployments. The service layer routes requests appropriately:

- Self-hosted: Routes through cloud data plane proxy
  Flow: Backend /admin/billing/* → Cloud DP /proxy/* → Control plane

- Cloud (MULTI_TENANT): Routes directly to control plane
  Flow: Backend /admin/billing/* → Control plane

License claiming is handled separately by /license/claim endpoint (self-hosted only).
"""

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
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
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/admin/billing")


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
    email = request.email if request else None

    # Build redirect URL for after checkout completion
    redirect_url = f"{WEB_DOMAIN}/admin/billing?checkout=success"

    try:
        return await create_checkout_service(
            billing_period=billing_period,
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
    """
    license_data = _get_license_data(db_session)
    tenant_id = _get_tenant_id()

    # Self-hosted without license = no subscription
    if not MULTI_TENANT and not license_data:
        return SubscriptionStatusResponse(subscribed=False)

    try:
        return await get_billing_service(
            license_data=license_data,
            tenant_id=tenant_id,
        )
    except BillingServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/seats/update")
async def update_seats(
    request: SeatUpdateRequest,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> SeatUpdateResponse:
    """Update the seat count for the current subscription.

    Handles Stripe proration and license regeneration via control plane.
    """
    license_data = _get_license_data(db_session)
    tenant_id = _get_tenant_id()

    # Self-hosted requires license
    if not MULTI_TENANT and not license_data:
        raise HTTPException(status_code=400, detail="No license found")

    try:
        return await update_seat_service(
            new_seat_count=request.new_seat_count,
            license_data=license_data,
            tenant_id=tenant_id,
        )
    except BillingServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
