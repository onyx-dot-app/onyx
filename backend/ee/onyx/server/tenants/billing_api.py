from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException

from ee.onyx.auth.users import current_admin_user
from ee.onyx.server.tenants.access import control_plane_dep
from ee.onyx.server.tenants.billing import fetch_billing_information
from ee.onyx.server.tenants.billing import fetch_customer_portal_session
from ee.onyx.server.tenants.billing import fetch_stripe_checkout_session
from ee.onyx.server.tenants.models import BillingInformation
from ee.onyx.server.tenants.models import CreateSubscriptionSessionRequest
from ee.onyx.server.tenants.models import ProductGatingFullSyncRequest
from ee.onyx.server.tenants.models import ProductGatingRequest
from ee.onyx.server.tenants.models import ProductGatingResponse
from ee.onyx.server.tenants.models import SubscriptionSessionResponse
from ee.onyx.server.tenants.models import SubscriptionStatusResponse
from ee.onyx.server.tenants.product_gating import overwrite_full_gated_set
from ee.onyx.server.tenants.product_gating import store_product_gating
from onyx.auth.users import User
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/tenants")


@router.post("/product-gating")
def gate_product(
    product_gating_request: ProductGatingRequest, _: None = Depends(control_plane_dep)
) -> ProductGatingResponse:
    """
    Gating the product means that the product is not available to the tenant.
    They will be directed to the billing page.
    We gate the product when their subscription has ended.
    """
    try:
        store_product_gating(
            product_gating_request.tenant_id, product_gating_request.application_status
        )
        return ProductGatingResponse(updated=True, error=None)

    except Exception as e:
        logger.exception("Failed to gate product")
        return ProductGatingResponse(updated=False, error=str(e))


@router.post("/product-gating/full-sync")
def gate_product_full_sync(
    product_gating_request: ProductGatingFullSyncRequest,
    _: None = Depends(control_plane_dep),
) -> ProductGatingResponse:
    """
    Bulk operation to overwrite the entire gated tenant set.
    This replaces all currently gated tenants with the provided list.
    Gated tenants are not available to access the product and will be
    directed to the billing page when their subscription has ended.
    """
    try:
        overwrite_full_gated_set(product_gating_request.gated_tenant_ids)
        return ProductGatingResponse(updated=True, error=None)

    except Exception as e:
        logger.exception("Failed to gate products during full sync")
        return ProductGatingResponse(updated=False, error=str(e))


@router.get("/billing-information")
async def billing_information(
    _: User = Depends(current_admin_user),
) -> BillingInformation | SubscriptionStatusResponse:
    logger.info("Fetching billing information")
    tenant_id = get_current_tenant_id()
    return fetch_billing_information(tenant_id)


@router.post("/create-customer-portal-session")
async def create_customer_portal_session(
    _: User = Depends(current_admin_user),
) -> dict:
    """
    Create a Stripe customer portal session via the control plane.
    NOTE: This is currently only used for multi-tenant (cloud) deployments.
    Self-hosted proxy endpoints will be added in a future phase.
    """
    tenant_id = get_current_tenant_id()
    return_url = f"{WEB_DOMAIN}/admin/billing"

    try:
        portal_url = fetch_customer_portal_session(tenant_id, return_url)
        return {"url": portal_url}
    except Exception as e:
        logger.exception("Failed to create customer portal session")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create-subscription-session")
async def create_subscription_session(
    request: CreateSubscriptionSessionRequest | None = None,
    _: User = Depends(current_admin_user),
) -> SubscriptionSessionResponse:
    try:
        tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Tenant ID not found")

        billing_period = request.billing_period if request else "monthly"
        session_id = fetch_stripe_checkout_session(tenant_id, billing_period)
        return SubscriptionSessionResponse(sessionId=session_id)

    except Exception as e:
        logger.exception("Failed to create subscription session")
        raise HTTPException(status_code=500, detail=str(e))
