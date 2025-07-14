import stripe
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException

from ee.onyx.auth.users import current_admin_user
from ee.onyx.configs.app_configs import STRIPE_SECRET_KEY
from ee.onyx.server.tenants.access import control_plane_dep
from ee.onyx.server.tenants.billing import fetch_billing_information
from ee.onyx.server.tenants.billing import fetch_stripe_checkout_session
from ee.onyx.server.tenants.billing import fetch_tenant_stripe_information
from ee.onyx.server.tenants.models import BillingInformation
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

stripe.api_key = STRIPE_SECRET_KEY
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
    tenant_id = get_current_tenant_id()

    try:
        stripe_info = fetch_tenant_stripe_information(tenant_id)
        stripe_customer_id = stripe_info.get("stripe_customer_id")
        if not stripe_customer_id:
            raise HTTPException(status_code=400, detail="Stripe customer ID not found")
        logger.info(stripe_customer_id)

        portal_session = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=f"{WEB_DOMAIN}/admin/billing",
        )
        logger.info(portal_session)
        return {"url": portal_session.url}
    except Exception as e:
        logger.exception("Failed to create customer portal session")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create-subscription-session")
async def create_subscription_session(
    _: User = Depends(current_admin_user),
) -> SubscriptionSessionResponse:
    try:
        tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Tenant ID not found")
        session_id = fetch_stripe_checkout_session(tenant_id)
        return SubscriptionSessionResponse(sessionId=session_id)

    except Exception as e:
        logger.exception("Failed to create resubscription session")
        raise HTTPException(status_code=500, detail=str(e))
